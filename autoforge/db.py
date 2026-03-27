"""SQLite database operations for AutoForge."""
import sqlite3
import hashlib
import json
import os
import threading
from datetime import datetime
from typing import Optional


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    perspective TEXT,
    phase TEXT,
    area TEXT,
    priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'pending',
    fingerprint TEXT UNIQUE,
    retry_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    completed_at TEXT,
    result_summary TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now','localtime')),
    total_files INTEGER,
    total_lines INTEGER,
    total_scripts INTEGER,
    total_scenes INTEGER,
    git_diff_lines INTEGER,
    modified_files TEXT,
    phase TEXT,
    perspective TEXT,
    task_id TEXT
);

CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY,
    category TEXT,
    level INTEGER,
    title TEXT,
    file_path TEXT,
    implemented INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS area_attention (
    area TEXT PRIMARY KEY,
    last_touched TEXT,
    touch_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS convergence_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now','localtime')),
    indicator TEXT,
    value REAL,
    action_taken TEXT
);

CREATE TABLE IF NOT EXISTS run_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- Run State ---

    def get_state(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM run_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO run_state (key, value) VALUES (?, ?)",
                (key, value),
            )
            self.conn.commit()

    # --- Tasks ---

    @staticmethod
    def make_fingerprint(title: str, description: str) -> str:
        content = f"{title.strip().lower()}|{(description or '').strip().lower()}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def insert_task(
        self,
        title: str,
        description: str,
        perspective: str = "",
        phase: str = "BUILD",
        area: str = "general",
        priority: int = 5,
    ) -> Optional[str]:
        """Insert a task. Returns task id or None if fingerprint duplicate."""
        fp = self.make_fingerprint(title, description)
        task_id = f"task-{fp}"
        try:
            with self._lock:
                self.conn.execute(
                    """INSERT INTO tasks (id, title, description, perspective, phase, area, priority, fingerprint)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (task_id, title, description, perspective, phase, area, priority, fp),
                )
                self.conn.commit()
            return task_id
        except sqlite3.IntegrityError:
            return None  # duplicate fingerprint

    def get_next_task(
        self, phase: Optional[str] = None, preferred_area: Optional[str] = None
    ) -> Optional[dict]:
        """Get the highest-priority pending task, optionally filtered by phase and area."""
        query = "SELECT * FROM tasks WHERE status = 'pending'"
        params: list = []

        if phase and phase != "EVOLVE":
            query += " AND phase = ?"
            params.append(phase)

        if preferred_area:
            # Prefer tasks in the preferred area, but fall back to any
            query_preferred = query + " AND area = ? ORDER BY priority ASC, created_at ASC LIMIT 1"
            row = self.conn.execute(query_preferred, params + [preferred_area]).fetchone()
            if row:
                return dict(row)

        query += " ORDER BY priority ASC, created_at ASC LIMIT 1"
        row = self.conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def get_next_tasks_by_area(
        self, phase: Optional[str] = None, max_tasks: int = 4, max_per_area: int = 1
    ) -> list[dict]:
        """Get multiple pending tasks, at most max_per_area per area.

        Returns up to max_tasks tasks from different areas to enable parallel execution.
        """
        query = "SELECT * FROM tasks WHERE status = 'pending'"
        params: list = []

        if phase and phase != "EVOLVE":
            query += " AND phase = ?"
            params.append(phase)

        query += " ORDER BY priority ASC, created_at ASC"
        rows = self.conn.execute(query, params).fetchall()

        selected = []
        area_counts: dict[str, int] = {}
        for row in rows:
            task = dict(row)
            area = task.get("area", "general")
            count = area_counts.get(area, 0)
            if count >= max_per_area:
                continue
            area_counts[area] = count + 1
            selected.append(task)
            if len(selected) >= max_tasks:
                break

        return selected

    def mark_task_in_progress(self, task_id: str):
        with self._lock:
            self.conn.execute(
                "UPDATE tasks SET status = 'in_progress' WHERE id = ?", (task_id,)
            )
            self.conn.commit()

    def mark_task_done(self, task_id: str, result_summary: str = ""):
        with self._lock:
            self.conn.execute(
                "UPDATE tasks SET status = 'done', completed_at = ?, result_summary = ? WHERE id = ?",
                (datetime.now().isoformat(), result_summary, task_id),
            )
            self.conn.commit()

    def mark_task_failed(self, task_id: str, reason: str = ""):
        """Mark a task as failed: increment retry count and reset to pending for retry."""
        with self._lock:
            self.conn.execute(
                "UPDATE tasks SET status = 'pending', retry_count = retry_count + 1, result_summary = ? WHERE id = ?",
                (reason, task_id),
            )
            self.conn.commit()

    def mark_task_skipped(self, task_id: str, reason: str = ""):
        with self._lock:
            self.conn.execute(
                "UPDATE tasks SET status = 'skipped', result_summary = ? WHERE id = ?",
                (reason, task_id),
            )
            self.conn.commit()

    def should_skip_task(self, task_id: str, max_retries: int = 3) -> bool:
        row = self.conn.execute(
            "SELECT retry_count FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return row is not None and row["retry_count"] >= max_retries

    def get_pending_count(self, phase: Optional[str] = None) -> int:
        if phase and phase != "EVOLVE":
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'pending' AND phase = ?",
                (phase,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'pending'"
            ).fetchone()
        return row["cnt"]

    def get_recent_completed(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT title, area, perspective FROM tasks WHERE status = 'done' ORDER BY completed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_total_completed(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'done'"
        ).fetchone()
        return row["cnt"]

    def reset_in_progress_tasks(self):
        """Reset tasks that were in_progress (from a crash) back to pending."""
        with self._lock:
            self.conn.execute(
                "UPDATE tasks SET status = 'pending' WHERE status = 'in_progress'"
            )
            self.conn.commit()

    # --- Metrics ---

    def record_metrics(
        self,
        total_files: int,
        total_lines: int,
        total_scripts: int,
        total_scenes: int,
        git_diff_lines: int,
        modified_files: list[str],
        phase: str,
        perspective: str,
        task_id: str = "",
    ):
        with self._lock:
            self.conn.execute(
                """INSERT INTO metrics
                   (total_files, total_lines, total_scripts, total_scenes,
                    git_diff_lines, modified_files, phase, perspective, task_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    total_files,
                    total_lines,
                    total_scripts,
                    total_scenes,
                    git_diff_lines,
                    json.dumps(modified_files),
                    phase,
                    perspective,
                    task_id,
                ),
            )
            self.conn.commit()

    def get_recent_metrics(self, limit: int = 5) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM metrics ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        result = [dict(r) for r in rows]
        for r in result:
            if r.get("modified_files"):
                try:
                    r["modified_files"] = json.loads(r["modified_files"])
                except json.JSONDecodeError:
                    r["modified_files"] = []
        return result

    # --- Area Attention ---

    def touch_area(self, area: str):
        with self._lock:
            self.conn.execute(
                """INSERT INTO area_attention (area, last_touched, touch_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(area) DO UPDATE SET
                     last_touched = excluded.last_touched,
                     touch_count = touch_count + 1""",
                (area, datetime.now().isoformat()),
            )
            self.conn.commit()

    def get_least_touched_areas(self, limit: int = 5) -> list[str]:
        rows = self.conn.execute(
            """SELECT area FROM area_attention
               ORDER BY touch_count ASC, last_touched ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [r["area"] for r in rows]

    def get_all_areas(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM area_attention ORDER BY touch_count ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Convergence ---

    def log_convergence(self, indicator: str, value: float, action: str):
        with self._lock:
            self.conn.execute(
                "INSERT INTO convergence_log (indicator, value, action_taken) VALUES (?, ?, ?)",
                (indicator, value, action),
            )
            self.conn.commit()

    # --- Knowledge ---

    def upsert_knowledge(
        self,
        entry_id: str,
        category: str,
        level: int,
        title: str,
        file_path: str,
        implemented: bool = False,
    ):
        with self._lock:
            self.conn.execute(
                """INSERT INTO knowledge (id, category, level, title, file_path, implemented)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     updated_at = datetime('now','localtime'),
                     implemented = excluded.implemented""",
                (entry_id, category, level, title, file_path, 1 if implemented else 0),
            )
            self.conn.commit()

    def get_knowledge_summary(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) as cnt FROM knowledge").fetchone()["cnt"]
        implemented = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge WHERE implemented = 1"
        ).fetchone()["cnt"]
        by_level = {}
        for row in self.conn.execute(
            "SELECT level, COUNT(*) as cnt FROM knowledge GROUP BY level"
        ).fetchall():
            by_level[f"L{row['level']}"] = row["cnt"]
        return {
            "total": total,
            "implemented": implemented,
            "not_implemented": total - implemented,
            "by_level": by_level,
        }
