"""AutoForge main orchestrator — the infinite autonomous development loop."""
import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime
from typing import Optional

from .agents import get_backend, SessionResult
from .config import AutoForgeConfig
from .convergence import detect_convergence
from .db import Database
from .hooks import build_hooks_from_config
from .metrics import record_session_metric, print_stats
from .parallel import resolve_worktree_dir, run_worker_pool, cleanup_worktrees
from .permissions import get_profile_for_role
from .prompts import (
    find_related_knowledge_files,
    generate_analyst_prompt,
    generate_builder_prompt,
)
from .reviewer import run_review, ReviewResult
from .runner import request_shutdown, is_shutdown_requested
from .state import gather_project_state, get_git_diff_stat, run_cmd


logger = logging.getLogger("autoforge")


class Orchestrator:
    def __init__(self, config: AutoForgeConfig):
        self.config = config
        self.db = Database(config.db_path)
        self.agent = get_backend(config.agent.backend, config.agent.to_backend_config())
        self.hook_runner = build_hooks_from_config(
            config.hooks,
            build_command=config.tasks.build_command,
            build_timeout=config.tasks.build_timeout,
            quality_commands=config.tasks.quality_commands,
        )
        self._ensure_dirs()
        self._setup_logging()
        self._load_seed()

        # Recover from crash: reset any in_progress tasks
        self.db.reset_in_progress_tasks()

        # If current phase is EVOLVE (e.g. stuck in convergence loop),
        # advance to BUILD so builders can run immediately.
        if self.db.get_state("current_phase", "") == "EVOLVE":
            pending = self.db.get_pending_count()
            if pending > 0:
                self.db.set_state("current_phase", "BUILD")
                self.db.set_state("last_completed_phase", "EVOLVE")
                logger.info(f"Recovery: phase EVOLVE→BUILD ({pending} pending tasks)")

        # Clean up stale worktrees from previous interrupted runs
        wt_base = resolve_worktree_dir(config.workspace_dir, config.parallel.worktree_dir, config.base_dir)
        cleanup_worktrees(config.workspace_dir, wt_base)

    def _ensure_dirs(self):
        for d in [
            self.config.data_dir,
            self.config.knowledge_dir,
            self.config.prompts_dir,
            self.config.logs_dir,
            self.config.workspace_dir,
            os.path.join(self.config.knowledge_dir, "L2_features"),
            os.path.join(self.config.knowledge_dir, "L3_details"),
            os.path.join(self.config.knowledge_dir, "L4_edge_cases"),
        ]:
            os.makedirs(d, exist_ok=True)

    def _setup_logging(self):
        log_file = os.path.join(
            self.config.logs_dir,
            f"run_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.log",
        )
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )
        logger.info(f"AutoForge started. Log: {log_file}")

    def _load_seed(self):
        if os.path.isfile(self.config.seed_file):
            with open(self.config.seed_file, "r", encoding="utf-8") as f:
                self.seed_content = f.read()
            logger.info(f"Seed loaded: {self.config.seed_file} ({len(self.seed_content)} chars)")
        else:
            logger.error(f"Seed file not found: {self.config.seed_file}")
            sys.exit(1)

    def _init_workspace_git(self):
        """Initialize git in workspace if not already done."""
        git_dir = os.path.join(self.config.workspace_dir, ".git")
        if not os.path.isdir(git_dir):
            run_cmd("git init", self.config.workspace_dir)
            run_cmd('git config user.name "AutoForge"', self.config.workspace_dir)
            run_cmd('git config user.email "autoforge@local"', self.config.workspace_dir)
            # Create .gitignore
            gitignore_path = os.path.join(self.config.workspace_dir, ".gitignore")
            if not os.path.isfile(gitignore_path):
                with open(gitignore_path, "w") as f:
                    f.write("# Auto-generated\n")
                run_cmd("git add -A && git commit -m \"Initial commit\"", self.config.workspace_dir)
            logger.info("Git initialized in workspace")

    def _get_current_phase(self) -> str:
        return self.db.get_state("current_phase", "EVOLVE")

    def _set_current_phase(self, phase: str):
        self.db.set_state("current_phase", phase)

    def _get_perspective_index(self) -> int:
        return int(self.db.get_state("perspective_index", "0"))

    def _set_perspective_index(self, idx: int):
        self.db.set_state("perspective_index", str(idx))

    def _get_current_perspective(self) -> dict:
        idx = self._get_perspective_index()
        perspectives = self.config.perspectives
        if not perspectives:
            return {"id": "P1", "name": "general", "label": "General", "desc": "General analysis"}
        p = perspectives[idx % len(perspectives)]
        return {"id": p.id, "name": p.name, "label": p.label, "desc": p.desc}

    def _advance_perspective(self):
        idx = self._get_perspective_index()
        new_idx = (idx + 1) % len(self.config.perspectives)
        self._set_perspective_index(new_idx)
        new_p = self.config.perspectives[new_idx]
        logger.info(f"Perspective rotated → {new_p.label} ({new_p.id})")

    def _advance_phase(self):
        current = self._get_current_phase()
        phases = self.config.phases
        idx = phases.index(current) if current in phases else 0
        new_idx = (idx + 1) % len(phases)
        new_phase = phases[new_idx]
        self._set_current_phase(new_phase)
        self.db.set_state("last_completed_phase", current)
        logger.info(f"Phase advanced: {current} → {new_phase}")

    def _get_permission_profile(self, role: str):
        """Get permission profile for a role, only if permissions are explicitly configured."""
        if not self.config.permissions:
            return None  # No config → backend default (full access, backward compat)
        return get_profile_for_role(role, self.config.permissions.get(role))

    def _get_phase_agent(self, phase: str) -> 'AgentBackend':
        """Get the agent backend for a given phase, applying per-phase overrides."""
        pc = self.config.phase_config.get(phase, {})
        if not pc:
            return self.agent

        override_model = pc.get("model")
        override_backend = pc.get("backend")

        if override_backend and override_backend != self.config.agent.backend:
            cfg = {**self.config.agent.to_backend_config()}
            if override_model:
                cfg["model"] = override_model
            return get_backend(override_backend, cfg)
        elif override_model:
            cfg = {**self.config.agent.to_backend_config(), "model": override_model}
            return get_backend(self.config.agent.backend, cfg)

        return self.agent

    def _get_loop_count(self) -> int:
        return int(self.db.get_state("loop_count", "0"))

    def _increment_loop_count(self) -> int:
        count = self._get_loop_count() + 1
        self.db.set_state("loop_count", str(count))
        return count

    def _git_commit(self, message: str):
        """Stage all changes and commit in workspace."""
        run_cmd("git add -A", self.config.workspace_dir)
        safe_msg = message.replace('"', '\\"').replace("'", "\\'")
        result = run_cmd(
            f'git add -A && git commit -m "{safe_msg}" --allow-empty',
            self.config.workspace_dir,
        )
        if result:
            logger.info(f"Git commit: {message[:80]}")

    def _parse_analyst_tasks(self) -> list[dict]:
        """Parse tasks generated by the analyst session."""
        tasks_file = self.config.next_tasks_path
        if not os.path.isfile(tasks_file):
            logger.warning("Analyst did not create next_tasks.json")
            return []

        try:
            with open(tasks_file, "r", encoding="utf-8") as f:
                content = f.read().strip()

            # Handle case where the file might have markdown code fences
            if content.startswith("```"):
                lines = content.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                content = "\n".join(lines)

            tasks = json.loads(content)
            if not isinstance(tasks, list):
                logger.warning("next_tasks.json is not a JSON array")
                return []

            logger.info(f"Parsed {len(tasks)} tasks from analyst")

            # Clean up the file after parsing
            os.remove(tasks_file)
            return tasks

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to parse next_tasks.json: {e}")
            # Try to salvage partial content
            return []

    def _read_task_result(self) -> str:
        """Read the task result written by the builder."""
        result_file = self.config.task_result_path
        if os.path.isfile(result_file):
            with open(result_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            os.remove(result_file)
            return content
        return ""

    def _run_analyst(self, project_state: dict, loop_count: int):
        """Run the analyst session to generate new tasks."""
        perspective = self._get_current_perspective()
        logger.info(f"=== ANALYST SESSION (Perspective: {perspective['label']}) ===")

        prompt = generate_analyst_prompt(
            seed_content=self.seed_content,
            project_state=project_state,
            knowledge_dir=self.config.knowledge_dir,
            knowledge_db_summary=self.db.get_knowledge_summary(),
            perspective=perspective,
            recent_completed=self.db.get_recent_completed(20),
            least_touched_areas=self.db.get_least_touched_areas(5),
            loop_count=loop_count,
            data_dir=self.config.data_dir,
            phases=self.config.phases,
            language=self.config.language,
            templates_dir=self.config.templates_dir,
        )

        prompt_path = os.path.join(
            self.config.prompts_dir, f"analyst_{loop_count:04d}.md"
        )

        result = self.agent.run_session(
            prompt=prompt,
            working_dir=self.config.workspace_dir,
            timeout_minutes=self.config.agent.timeout_minutes,
            prompt_save_path=prompt_path,
            permission_profile=self._get_permission_profile("analyst"),
        )

        if not result.success:
            logger.error(f"Analyst session failed: {result.stderr[:200]}")
            record_session_metric(
                self.db, task_id="", session_type="analyst",
                agent_backend=self.config.agent.backend, model=self.config.agent.model,
                duration_seconds=result.duration_seconds, exit_code=result.exit_code,
                phase=self._get_current_phase(), perspective=perspective["id"],
            )
            return

        record_session_metric(
            self.db, task_id="", session_type="analyst",
            agent_backend=self.config.agent.backend, model=self.config.agent.model,
            duration_seconds=result.duration_seconds, exit_code=result.exit_code,
            phase=self._get_current_phase(), perspective=perspective["id"],
        )

        # Parse generated tasks
        new_tasks = self._parse_analyst_tasks()
        inserted = 0
        for t in new_tasks:
            phase = t.get("phase", "BUILD")
            if phase not in self.config.phases:
                phase = "BUILD"

            task_id = self.db.insert_task(
                title=t.get("title", "Untitled"),
                description=t.get("description", ""),
                perspective=perspective["id"],
                phase=phase,
                area=t.get("area", "general"),
                priority=t.get("priority", 5),
            )
            if task_id:
                inserted += 1
                # Ensure area exists in attention tracking
                self.db.touch_area(t.get("area", "general"))

        logger.info(
            f"Analyst generated {len(new_tasks)} tasks, {inserted} new (deduped)"
        )

        # Commit knowledge base changes
        self._git_commit(
            f"[AutoForge] Analyst: {perspective['label']} — {inserted} new tasks"
        )

        # Rotate perspective for next analyst run
        self._advance_perspective()

    def _run_builder(self, task: dict, project_state: dict, loop_count: int):
        """Run the builder session to execute a task."""
        task_id = task["id"]
        logger.info(f"=== BUILDER SESSION: {task['title']} ===")
        logger.info(f"  Area: {task.get('area', '?')} | Priority: {task.get('priority', '?')}")

        self.db.mark_task_in_progress(task_id)

        related_kb = find_related_knowledge_files(
            self.config.knowledge_dir, task.get("area", "general"),
            area_keywords=self.config.knowledge.get("area_keywords"),
        )

        prompt = generate_builder_prompt(
            seed_content=self.seed_content,
            task=task,
            project_state=project_state,
            knowledge_dir=self.config.knowledge_dir,
            related_knowledge_files=related_kb,
            data_dir=self.config.data_dir,
            build_command=self.config.tasks.build_command,
            language=self.config.language,
            templates_dir=self.config.templates_dir,
        )

        prompt_path = os.path.join(
            self.config.prompts_dir, f"builder_{loop_count:04d}.md"
        )

        phase_agent = self._get_phase_agent(self._get_current_phase())
        result = phase_agent.run_session(
            prompt=prompt,
            working_dir=self.config.workspace_dir,
            timeout_minutes=self.config.agent.timeout_minutes,
            prompt_save_path=prompt_path,
            permission_profile=self._get_permission_profile("builder"),
        )

        # Read task result
        task_result = self._read_task_result()

        # Record session metric
        record_session_metric(
            self.db, task_id=task_id, session_type="builder",
            agent_backend=phase_agent.name, model=self.config.agent.model,
            duration_seconds=result.duration_seconds, exit_code=result.exit_code,
            phase=self._get_current_phase(), perspective=self._get_current_perspective()["id"],
        )

        if not result.success:
            logger.warning(f"Builder session failed (exit={result.exit_code})")
            self.db.mark_task_failed(task_id, reason=result.stderr[:500])

            if self.db.should_skip_task(task_id, self.config.tasks.max_retries):
                self.db.mark_task_skipped(task_id, reason="Max retries exceeded")
                logger.warning(f"Task skipped (max retries): {task['title']}")
            return False

        # Quality gate via hooks
        qg = self.hook_runner.run_hooks("post_build", self.config.workspace_dir)
        if not qg.passed:
            logger.warning(f"Quality gate failed: {qg.issues}")
            self.db.mark_task_failed(task_id, reason=f"Quality gate: {qg.issues}")
            if self.db.should_skip_task(task_id, self.config.tasks.max_retries):
                self.db.mark_task_skipped(task_id, reason="Quality gate failures")
            return False

        # Optional reviewer
        if self.config.reviewer.enabled:
            review = self._run_review(task, task_result)
            if review.verdict == "REJECT":
                logger.warning(f"Reviewer REJECTED: {review.summary}")
                self.db.mark_task_failed(task_id, reason=f"Reviewer rejected: {review.summary}")
                if self.db.should_skip_task(task_id, self.config.tasks.max_retries):
                    self.db.mark_task_skipped(task_id, reason="Reviewer rejection")
                return False
            elif review.verdict == "REQUEST_CHANGES":
                logger.info(f"Reviewer requested changes: {review.issues}")
                # Mark failed so it gets retried with feedback
                self.db.mark_task_failed(
                    task_id, reason=f"Reviewer feedback: {'; '.join(review.issues)}"
                )
                return False

        # Success!
        summary = task_result[:500] if task_result else "Completed"
        self.db.mark_task_done(task_id, result_summary=summary)
        self.db.touch_area(task.get("area", "general"))

        # Git commit
        commit_msg = f"[AutoForge] {task['title']}"
        if task.get("area"):
            commit_msg = f"[AutoForge][{task['area']}] {task['title']}"
        self._git_commit(commit_msg)

        logger.info(f"Task completed: {task['title']}")
        if qg.warnings:
            logger.info(f"  ({len(qg.warnings)} warnings)")

        return True

    def _run_review(self, task: dict, builder_summary: str) -> ReviewResult:
        """Run the reviewer agent on the builder's changes."""
        logger.info(f"=== REVIEWER SESSION: {task['title']} ===")

        # Use a separate agent backend for the reviewer if configured
        rc = self.config.reviewer
        if rc.backend and rc.backend != self.config.agent.backend:
            reviewer_agent = get_backend(rc.backend, {
                **self.config.agent.to_backend_config(),
                **({"model": rc.model} if rc.model else {}),
            })
        elif rc.model:
            reviewer_agent = get_backend(self.config.agent.backend, {
                **self.config.agent.to_backend_config(),
                "model": rc.model,
            })
        else:
            reviewer_agent = self.agent

        return run_review(
            agent=reviewer_agent,
            task=task,
            builder_summary=builder_summary,
            workspace_dir=self.config.workspace_dir,
            data_dir=self.config.data_dir,
            reviewer_config=rc,
            language=self.config.language,
            templates_dir=self.config.templates_dir,
            timeout_minutes=min(15, self.config.agent.timeout_minutes),
        )

    def _build_single_builder_fn(self, project_state: dict, loop_count: int):
        """Return a builder function for use with run_parallel_builders.

        The returned callable has signature (task, working_dir) -> dict
        and is safe to call from multiple threads.
        """
        def _builder(task: dict, working_dir: str) -> dict:
            task_id = task["id"]
            task_result_filename = f"task_result_{task_id}.md"

            self.db.mark_task_in_progress(task_id)

            related_kb = find_related_knowledge_files(
                self.config.knowledge_dir, task.get("area", "general"),
                area_keywords=self.config.knowledge.get("area_keywords"),
            )

            prompt = generate_builder_prompt(
                seed_content=self.seed_content,
                task=task,
                project_state=project_state,
                knowledge_dir=self.config.knowledge_dir,
                related_knowledge_files=related_kb,
                data_dir=self.config.data_dir,
                task_result_filename=task_result_filename,
                build_command=self.config.tasks.build_command,
                language=self.config.language,
                templates_dir=self.config.templates_dir,
            )

            prompt_path = os.path.join(
                self.config.prompts_dir, f"builder_{loop_count:04d}_{task_id}.md"
            )

            phase_agent = self._get_phase_agent(self._get_current_phase())
            result = phase_agent.run_session(
                prompt=prompt,
                working_dir=working_dir,
                timeout_minutes=self.config.agent.timeout_minutes,
                prompt_save_path=prompt_path,
                permission_profile=self._get_permission_profile("builder"),
            )

            # Read task result from the shared data_dir
            result_path = self.config.task_result_path_for(task_id)
            task_result = ""
            if os.path.isfile(result_path):
                with open(result_path, "r", encoding="utf-8", errors="replace") as f:
                    task_result = f.read()
                os.remove(result_path)

            # Quality gate via hooks (run against the worktree, not main workspace)
            qg = self.hook_runner.run_hooks("post_build", working_dir)

            success = result.success and qg.passed

            return {
                "success": success,
                "result_summary": task_result[:500] if task_result else (
                    f"Quality gate failed: {qg.issues}" if not qg.passed else "Completed"
                ),
            }

        return _builder

    def _run_parallel_builders(
        self, phase: str, project_state: dict, loop_count: int
    ) -> int:
        """Run worker pool that continuously executes tasks until queue is empty.

        Returns total number of successfully completed tasks.
        """
        worktree_base = resolve_worktree_dir(
            self.config.workspace_dir, self.config.parallel.worktree_dir, self.config.base_dir
        )
        builder_fn = self._build_single_builder_fn(project_state, loop_count)
        max_workers = self.config.parallel.max_builders

        logger.info(f"=== WORKER POOL: {max_workers} workers, phase={phase} ===")

        # Track which areas have a running builder to avoid same-area concurrency
        _running_areas: set[str] = set()
        _area_lock = threading.Lock()

        def get_next_task() -> dict | None:
            """Thread-safe task picker: one task per area at a time."""
            with _area_lock:
                # Get candidate tasks sorted by priority
                candidates = self.db.get_next_tasks_by_area(
                    phase=phase, max_tasks=max_workers * 2, max_per_area=1
                )
                for task in candidates:
                    area = task.get("area", "general")
                    if area not in _running_areas:
                        _running_areas.add(area)
                        self.db.mark_task_in_progress(task["id"])
                        logger.info(f"  Dispatching [{area}] {task['title'][:60]}")
                        return task
                return None

        def on_task_complete(result: dict):
            """Called when a builder finishes (success or failure)."""
            task = result["task"]
            task_id = task["id"]
            area = task.get("area", "general")

            # Release the area so another task in this area can run
            with _area_lock:
                _running_areas.discard(area)

            if result.get("success") and result.get("merged"):
                self.db.mark_task_done(task_id, result_summary=result.get("summary", ""))
                self.db.touch_area(area)
            else:
                self.db.mark_task_failed(task_id, reason=result.get("summary", ""))
                if self.db.should_skip_task(task_id, self.config.tasks.max_retries):
                    self.db.mark_task_skipped(task_id, reason="Max retries exceeded")

        # Optionally prefetch analyst tasks in background
        analyst_thread = None
        if self.config.parallel.prefetch_analyst:
            pending_count = self.db.get_pending_count()
            if pending_count < self.config.tasks.tasks_per_phase * 2:
                logger.info("Starting analyst prefetch in background...")
                analyst_thread = threading.Thread(
                    target=self._run_analyst,
                    args=(project_state, loop_count),
                    daemon=True,
                )
                analyst_thread.start()

        success_count = run_worker_pool(
            max_workers=max_workers,
            get_next_task_fn=get_next_task,
            builder_fn=builder_fn,
            on_complete_fn=on_task_complete,
            workspace_dir=self.config.workspace_dir,
            worktree_base=worktree_base,
        )

        if analyst_thread is not None:
            analyst_thread.join(timeout=self.config.agent.timeout_minutes * 60)
            logger.info("Analyst prefetch completed")

        logger.info(f"Worker pool finished: {success_count} tasks succeeded")
        return success_count

    def _record_metrics(self, project_state: dict, task_id: str = ""):
        """Record project metrics for convergence detection.

        Re-gathers total_lines/total_files to get post-build values,
        ensuring convergence detection sees actual changes.
        """
        diff_lines, modified_files = get_git_diff_stat(self.config.workspace_dir)
        perspective = self._get_current_perspective()

        # Re-gather file/line counts so convergence detection sees post-build state
        from .state import count_files, count_lines
        current_files = count_files(self.config.workspace_dir)
        current_lines = count_lines(self.config.workspace_dir)

        self.db.record_metrics(
            total_files=current_files,
            total_lines=current_lines,
            total_scripts=0,
            total_scenes=0,
            git_diff_lines=diff_lines,
            modified_files=modified_files,
            phase=self._get_current_phase(),
            perspective=perspective["id"],
            task_id=task_id,
        )

    def _check_convergence(self) -> bool:
        """Check for convergence and take action if detected."""
        # Skip if we just came from an EVOLVE phase (analyst doesn't change code,
        # so checking convergence right after would always trigger again → deadlock)
        last_phase = self.db.get_state("last_completed_phase", "")
        if last_phase == "EVOLVE":
            return False

        recent = self.db.get_recent_metrics(self.config.convergence.check_window)
        result = detect_convergence(
            recent,
            check_window=self.config.convergence.check_window,
            min_diff_lines=self.config.convergence.min_diff_lines,
            max_file_overlap_ratio=self.config.convergence.max_file_overlap_ratio,
            stagnation_threshold=self.config.convergence.stagnation_line_threshold,
        )

        if result:
            logger.warning(f"⚠ CONVERGENCE DETECTED: {result['message']}")
            self.db.log_convergence(
                indicator=result["indicator"],
                value=result["value"],
                action="perspective_rotation + area_shift",
            )
            self._advance_perspective()
            return True

        return False

    def run(self, max_loops: int | None = None):
        """Main orchestration loop. Runs forever unless max_loops is set."""
        logger.info("=" * 60)
        logger.info("  AutoForge — Infinite Autonomous Development Framework")
        logger.info("=" * 60)
        logger.info(f"Workspace: {self.config.workspace_dir}")
        logger.info(f"Data dir:  {self.config.data_dir}")
        logger.info(f"Model: {self.config.agent.model}")
        logger.info(f"Agent: {self.config.agent.backend}")
        logger.info(f"Phases: {self.config.phases}")
        logger.info(f"Perspectives: {len(self.config.perspectives)}")
        logger.info(f"Parallel: max_builders={self.config.parallel.max_builders}")

        # Check agent availability
        if not self.agent.check_available():
            logger.error(f"Agent backend not available: {self.config.agent.backend} (path: {self.config.agent.path})")
            logger.error("Install it or update agent.path in config")
            sys.exit(1)

        # Initialize workspace git
        self._init_workspace_git()

        # Main loop
        tasks_completed_this_phase = 0
        loop_count = self._get_loop_count()

        while max_loops is None or loop_count < max_loops:
            loop_count = self._increment_loop_count()
            phase = self._get_current_phase()
            perspective = self._get_current_perspective()
            pending = self.db.get_pending_count(phase)
            total_done = self.db.get_total_completed()

            logger.info("")
            logger.info(f"{'='*50}")
            logger.info(f"Loop #{loop_count} | Phase: {phase} | Perspective: {perspective['label']}")
            logger.info(f"Pending tasks: {pending} | Total completed: {total_done}")
            logger.info(f"{'='*50}")

            # 1. Gather project state
            project_state = gather_project_state(self.config.workspace_dir)

            # 2. Check convergence
            if self._check_convergence():
                logger.info("Convergence response: rotating perspective and forcing EVOLVE")
                self._set_current_phase("EVOLVE")
                phase = "EVOLVE"
                tasks_completed_this_phase = 0

            # 3. Phase dispatch
            if phase == "EVOLVE" or pending == 0:
                # Run analyst to generate new tasks
                self._run_analyst(project_state, loop_count)
                self._record_metrics(project_state)
                self._advance_phase()
                tasks_completed_this_phase = 0

            else:
                max_builders = self.config.parallel.max_builders

                if max_builders > 1 and pending >= 2:
                    # Worker pool mode: workers continuously pull tasks until empty
                    success_count = self._run_parallel_builders(
                        phase, project_state, loop_count
                    )
                    self._record_metrics(project_state)
                    tasks_completed_this_phase += success_count
                else:
                    # Sequential mode (original behavior)
                    least_touched = self.db.get_least_touched_areas(3)
                    preferred_area = least_touched[0] if least_touched else None

                    task = self.db.get_next_task(phase=phase, preferred_area=preferred_area)

                    if task is None:
                        logger.info(f"No tasks for phase {phase}, advancing...")
                        self._advance_phase()
                        tasks_completed_this_phase = 0
                        continue

                    success = self._run_builder(task, project_state, loop_count)
                    self._record_metrics(project_state, task_id=task["id"])

                    if success:
                        tasks_completed_this_phase += 1

                # Auto-advance phase after N tasks
                if tasks_completed_this_phase >= self.config.tasks.tasks_per_phase:
                    logger.info(
                        f"Phase quota reached ({tasks_completed_this_phase} tasks), advancing..."
                    )
                    self._advance_phase()
                    tasks_completed_this_phase = 0

            # 4. Cooldown
            cooldown = self.config.tasks.cooldown_seconds
            logger.info(f"Cooldown: {cooldown}s...")
            time.sleep(cooldown)


def main():
    parser = argparse.ArgumentParser(
        description="AutoForge — Infinite Autonomous Development Framework"
    )
    parser.add_argument(
        "-c", "--config",
        default="autoforge_config.json",
        help="Path to configuration file (default: autoforge_config.json)",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize a new AutoForge project",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print session metrics dashboard",
    )
    parser.add_argument(
        "--max-loops",
        type=int,
        default=None,
        help="Maximum number of loops to run (default: unlimited)",
    )

    args = parser.parse_args()

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.getcwd(), config_path)

    if not os.path.isfile(config_path):
        print(f"Config file not found: {config_path}")
        print("Run from the directory containing autoforge_config.json")
        print("Or specify with: python -m autoforge -c /path/to/config.json")
        sys.exit(1)

    config = AutoForgeConfig.load(config_path)

    if args.init:
        print("AutoForge initialized!")
        print(f"  Config:    {config_path}")
        print(f"  Workspace: {config.workspace_dir}")
        print(f"  Data dir:  {config.data_dir}")
        print(f"  Database:  {config.db_path}")
        print(f"  Knowledge: {config.knowledge_dir}")
        print(f"  Logs:      {config.logs_dir}")
        print(f"  Seed:      {config.seed_file}")
        print(f"\nEdit seed.md with your project description, then run:")
        print(f"  python -m autoforge -c {args.config}")
        # Create dirs and DB
        orchestrator = Orchestrator(config)
        orchestrator.db.close()
        return

    if args.stats:
        db = Database(config.db_path)
        print_stats(db)
        db.close()
        return

    orchestrator = Orchestrator(config)

    def _signal_handler(sig, frame):
        logger.info("\nShutdown requested (Ctrl+C) — terminating agent sessions...")
        request_shutdown()
        # Raise KeyboardInterrupt to break out of main loop / sleep
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        orchestrator.run(max_loops=args.max_loops)
    except KeyboardInterrupt:
        logger.info("AutoForge stopped by user")
    except Exception as e:
        logger.error(f"AutoForge crashed: {e}", exc_info=True)
        logger.info("AutoForge will recover on next restart")
    finally:
        orchestrator.db.close()
