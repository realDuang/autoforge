"""Parallel builder execution using git worktrees.

Architecture: Each builder runs in its own worktree. When done, it acquires
a merge lock, merges its changes into main, and releases the lock. This means
merge happens immediately after each builder finishes — not deferred.
"""
import concurrent.futures
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("autoforge")

# Global lock for merge operations — only one thread merges at a time
_merge_lock = threading.Lock()


def _git(args: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command."""
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def resolve_worktree_dir(workspace_dir: str, configured_dir: str, base_dir: str = "") -> str:
    """Resolve the worktree base directory.

    Default: {workspace_dir}/.worktrees — inside the workspace so copilot
    recognizes the git repository correctly.
    """
    if configured_dir:
        return configured_dir
    return os.path.join(workspace_dir, ".worktrees")


def cleanup_worktrees(workspace_dir: str, worktree_base: str):
    """Clean up all stale worktrees and autoforge branches."""
    _git(["worktree", "prune"], cwd=workspace_dir, check=False)

    result = _git(["branch", "--list", "autoforge/*"], cwd=workspace_dir, check=False)
    for line in result.stdout.strip().split("\n"):
        branch = line.strip().lstrip("* ")
        if branch:
            _git(["branch", "-D", branch], cwd=workspace_dir, check=False)

    if os.path.isdir(worktree_base):
        shutil.rmtree(worktree_base, ignore_errors=True)


def _create_worktree(
    workspace_dir: str, worktree_base: str, branch_name: str,
    symlink_dirs: list[str] | None = None,
) -> str:
    """Create a git worktree. Returns the worktree path.

    Args:
        symlink_dirs: Relative directory paths to symlink from the main workspace
            into the worktree. Used for large gitignored files (e.g. game assets)
            that worktrees need at runtime but shouldn't be duplicated.
    """
    safe_name = branch_name.replace("/", "-")
    worktree_path = os.path.normpath(os.path.join(worktree_base, safe_name))
    os.makedirs(worktree_base, exist_ok=True)

    if os.path.isdir(worktree_path):
        _git(["worktree", "remove", worktree_path, "--force"], cwd=workspace_dir, check=False)
    _git(["branch", "-D", branch_name], cwd=workspace_dir, check=False)
    _git(["worktree", "prune"], cwd=workspace_dir, check=False)
    _git(["worktree", "add", worktree_path, "-b", branch_name], cwd=workspace_dir)

    # Create symlinks for large gitignored directories
    for rel_dir in (symlink_dirs or []):
        src = os.path.normpath(os.path.join(workspace_dir, rel_dir))
        dst = os.path.normpath(os.path.join(worktree_path, rel_dir))
        if os.path.isdir(src) and not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                os.symlink(src, dst, target_is_directory=True)
                logger.debug(f"Symlinked {rel_dir} into worktree")
            except OSError as e:
                logger.warning(f"Failed to symlink {rel_dir}: {e}")

    logger.info(f"Created worktree: {worktree_path} (branch: {branch_name})")
    return worktree_path


def _remove_worktree(workspace_dir: str, worktree_path: str, branch_name: str):
    """Remove a worktree and its branch."""
    _git(["worktree", "remove", worktree_path, "--force"], cwd=workspace_dir, check=False)
    _git(["branch", "-D", branch_name], cwd=workspace_dir, check=False)


def _try_auto_resolve_conflicts(workspace_dir: str, conflicts: list[str]) -> bool:
    """Try to auto-resolve merge conflicts by keeping both sides' additions.

    ONLY resolves conflicts in safe file types (data/config/docs).
    Source code files (.cs, .py, .ts, .js, .java, .cpp, etc.) are NEVER
    auto-resolved because keeping both sides creates duplicate definitions.

    Returns True if all conflicts were resolved.
    """
    import re

    # File extensions where "keep both sides" is safe
    _SAFE_EXTENSIONS = {".json", ".md", ".txt", ".cfg", ".toml", ".yaml", ".yml", ".xml", ".csv"}

    for filepath in conflicts:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in _SAFE_EXTENSIONS:
            logger.info(f"Auto-resolve skipped for source file: {filepath}")
            return False  # Refuse to auto-resolve any source code

        full_path = os.path.join(workspace_dir, filepath)
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            if "<<<<<<<" not in content:
                return False  # Not a text conflict

            # Remove conflict markers, keep both sides
            resolved = re.sub(
                r'<<<<<<<[^\n]*\n(.*?)=======\n(.*?)>>>>>>>[^\n]*\n',
                r'\1\2',
                content,
                flags=re.DOTALL,
            )

            if "<<<<<<<" in resolved:
                return False  # Nested conflicts or failed to resolve

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(resolved)

        except Exception as e:
            logger.warning(f"Auto-resolve failed for {filepath}: {e}")
            return False

    return True


# Type for conflict resolution callback: (workspace_dir, conflict_files) -> bool
ConflictResolverFn = Optional[Callable[[str, list[str]], bool]]


def _merge_worktree_to_main(
    workspace_dir: str,
    worktree_path: str,
    branch_name: str,
    commit_msg: str,
    conflict_resolver: ConflictResolverFn = None,
) -> dict:
    """Commit changes in worktree and merge to main. Thread-safe via _merge_lock.

    Returns {"success": bool, "detail": str}.
    """
    # Stage any uncommitted changes (agent may or may not have committed already)
    _git(["add", "-A"], cwd=worktree_path, check=False)
    status = _git(["status", "--porcelain"], cwd=worktree_path, check=False)
    
    if status.stdout.strip():
        # There are uncommitted changes — commit them
        commit_result = _git(["commit", "-m", commit_msg], cwd=worktree_path, check=False)
        if commit_result.returncode != 0:
            logger.warning(f"Commit failed in worktree: {commit_result.stderr.strip()[:200]}")

    # Check if the branch has any commits ahead of main
    ahead = _git(
        ["rev-list", "--count", f"main..{branch_name}"],
        cwd=worktree_path, check=False,
    )
    commits_ahead = int(ahead.stdout.strip()) if ahead.stdout.strip().isdigit() else 0
    if commits_ahead == 0:
        main_head = _git(["rev-parse", "--short", "main"], cwd=worktree_path, check=False)
        branch_head = _git(["rev-parse", "--short", "HEAD"], cwd=worktree_path, check=False)
        logger.warning(
            f"No commits ahead of main (main={main_head.stdout.strip()}, "
            f"branch={branch_head.stdout.strip()}, "
            f"same={main_head.stdout.strip() == branch_head.stdout.strip()})"
        )
        return {"success": False, "detail": "No code changes produced"}

    # Acquire lock — only one merge at a time
    with _merge_lock:
        # First rebase onto latest main so merge is fast-forward
        rebase = _git(["rebase", "main"], cwd=worktree_path, check=False)
        if rebase.returncode != 0:
            _git(["rebase", "--abort"], cwd=worktree_path, check=False)
            # Try merge instead of rebase
            _git(["reset", "--hard", "HEAD"], cwd=worktree_path, check=False)

        # Merge into main
        result = _git(["merge", branch_name, "--no-edit"], cwd=workspace_dir, check=False)

        if result.returncode == 0:
            return {"success": True, "detail": "Merged successfully"}

        # Merge failed — check if it's a real conflict
        stderr = result.stderr.strip() if result.stderr else ""
        stdout = result.stdout.strip() if result.stdout else ""

        # Check for unresolvable errors (file locks, permissions, etc.)
        if "cannot unlink" in stderr or "Invalid argument" in stderr:
            _git(["merge", "--abort"], cwd=workspace_dir, check=False)
            return {"success": False, "detail": f"Merge blocked by file lock: {stderr}"}

        # Check for actual file conflicts
        diff = _git(["diff", "--name-only", "--diff-filter=U"], cwd=workspace_dir, check=False)
        conflicts = [f.strip() for f in diff.stdout.strip().split("\n") if f.strip()]

        if not conflicts:
            _git(["merge", "--abort"], cwd=workspace_dir, check=False)
            return {"success": False, "detail": f"Merge error: {stderr or stdout}"}

        # Try auto-resolving: for text/config files where both sides
        # added lines, accept both additions by choosing the merged version
        resolved = _try_auto_resolve_conflicts(workspace_dir, conflicts)
        if resolved:
            _git(["add", "-A"], cwd=workspace_dir, check=False)
            _git(["commit", "--no-edit", "--allow-empty"], cwd=workspace_dir, check=False)
            logger.info(f"Auto-resolved conflicts in: {conflicts}")
            return {"success": True, "detail": f"Merged (auto-resolved {conflicts})"}
        # Try agent-powered conflict resolution for source code files
        if conflict_resolver is not None:
            logger.info(f"Attempting agent-powered conflict resolution for {len(conflicts)} files")
            try:
                agent_resolved = conflict_resolver(workspace_dir, conflicts)
                if agent_resolved:
                    _git(["add", "-A"], cwd=workspace_dir, check=False)
                    _git(["commit", "--no-edit", "--allow-empty"], cwd=workspace_dir, check=False)
                    logger.info(f"Agent resolved conflicts in: {conflicts}")
                    return {"success": True, "detail": f"Merged (agent-resolved {conflicts})"}
                else:
                    logger.warning(f"Agent failed to resolve conflicts in: {conflicts}")
            except Exception as e:
                logger.warning(f"Agent conflict resolution error: {e}")
            # Agent failed — abort merge
            _git(["merge", "--abort"], cwd=workspace_dir, check=False)
            return {"success": False, "detail": f"Agent could not resolve conflict in {conflicts}"}
        # Unresolvable conflict — abort
        _git(["merge", "--abort"], cwd=workspace_dir, check=False)
        return {"success": False, "detail": f"Merge conflict in {len(conflicts)} files: {conflicts}"}


def has_worktree_changes(worktree_path: str) -> bool:
    """Check if a worktree has any uncommitted or committed changes vs its base."""
    # Check for uncommitted changes first
    status = _git(["status", "--porcelain"], cwd=worktree_path, check=False)
    if status.stdout.strip():
        return True
    # Check for commits ahead of main
    ahead = _git(
        ["rev-list", "--count", "main..HEAD"],
        cwd=worktree_path, check=False,
    )
    count = int(ahead.stdout.strip()) if ahead.stdout.strip().isdigit() else 0
    return count > 0


BuilderFn = Callable[[dict, str], dict]


def _run_single_builder(
    task: dict,
    builder_fn: BuilderFn,
    workspace_dir: str,
    worktree_base: str,
    conflict_resolver: ConflictResolverFn = None,
    symlink_dirs: list[str] | None = None,
) -> dict:
    """Run a single builder in its own worktree, then merge result.

    This is the per-thread entry point. Each thread:
    1. Creates a worktree
    2. Runs the builder function (copilot session)
    3. Commits + merges to main (with lock)
    4. Cleans up the worktree

    Returns: {"task": dict, "success": bool, "merged": bool, "summary": str}
    """
    task_id = task["id"]
    area = task.get("area", "?")
    title_short = task["title"][:50]
    branch = f"autoforge/parallel-{task_id}"
    wt_path = None

    try:
        wt_path = _create_worktree(workspace_dir, worktree_base, branch, symlink_dirs=symlink_dirs)
    except Exception as e:
        logger.error(f"Worktree creation failed for {task_id}: {e}")
        return {"task": task, "success": False, "merged": False, "summary": str(e)}

    try:
        # Run builder (copilot session)
        build_result = builder_fn(task, wt_path)

        if not build_result.get("success", False):
            return {
                "task": task,
                "success": False,
                "merged": False,
                "summary": build_result.get("result_summary", "Builder failed"),
            }

        # Task was confirmed already implemented — no merge needed
        if build_result.get("superseded"):
            logger.info(f"[{area}] ○ {title_short} — superseded (already implemented)")
            return {
                "task": task,
                "success": True,
                "merged": False,
                "superseded": True,
                "summary": build_result.get("result_summary", "Already implemented"),
            }

        # Commit and merge
        commit_msg = f"[AutoForge][{task.get('area', '?')}] {task['title']}"
        merge_result = _merge_worktree_to_main(
            workspace_dir, wt_path, branch, commit_msg,
            conflict_resolver=conflict_resolver,
        )

        if merge_result["success"]:
            logger.info(f"[{area}] ✓ {title_short} — {merge_result['detail']}")
            return {
                "task": task,
                "success": True,
                "merged": True,
                "summary": build_result.get("result_summary", "Completed"),
            }
        else:
            logger.warning(f"[{area}] ✗ {title_short} — {merge_result['detail']}")
            return {
                "task": task,
                "success": False,
                "merged": False,
                "summary": merge_result["detail"],
            }

    except Exception as e:
        logger.error(f"Builder exception for {task_id}: {e}")
        return {"task": task, "success": False, "merged": False, "summary": str(e)}

    finally:
        # Always clean up worktree
        if wt_path:
            try:
                _remove_worktree(workspace_dir, wt_path, branch)
            except Exception:
                pass


TaskResult = dict  # {"task": dict, "success": bool, "merged": bool, "summary": str}
GetNextTaskFn = Callable[[], Optional[dict]]
OnCompleteCallbackFn = Callable[[TaskResult], None]


def run_worker_pool(
    max_workers: int,
    get_next_task_fn: GetNextTaskFn,
    builder_fn: BuilderFn,
    on_complete_fn: OnCompleteCallbackFn,
    workspace_dir: str,
    worktree_base: str,
    conflict_resolver: ConflictResolverFn = None,
    symlink_dirs: list[str] | None = None,
) -> int:
    """Run a pool of workers that continuously pull and execute tasks.

    Workers keep pulling tasks from get_next_task_fn() until it returns None.
    Each task is built in its own worktree and merged immediately.
    on_complete_fn is called (thread-safe) with the result of each task.

    Returns total number of successfully completed tasks.
    """
    # Clean up stale worktrees from previous runs
    cleanup_worktrees(workspace_dir, worktree_base)

    # Ensure main workspace is clean
    _git(["add", "-A"], cwd=workspace_dir, check=False)
    status = _git(["status", "--porcelain"], cwd=workspace_dir, check=False)
    if status.stdout.strip():
        _git(["commit", "-m", "[AutoForge] Pre-parallel cleanup", "--allow-empty"],
             cwd=workspace_dir, check=False)

    success_count = 0
    _count_lock = threading.Lock()
    _task_lock = threading.Lock()

    def _worker(worker_id: int):
        nonlocal success_count
        from .runner import is_shutdown_requested
        while True:
            if is_shutdown_requested():
                logger.info(f"Worker-{worker_id}: shutdown requested, exiting")
                break
            # Get next task (thread-safe)
            with _task_lock:
                task = get_next_task_fn()
            if task is None:
                logger.debug(f"Worker-{worker_id}: no more tasks, exiting")
                break

            logger.info(f"[W{worker_id}] ▶ [{task.get('area', '?')}] {task['title'][:60]}")

            result = _run_single_builder(
                task, builder_fn, workspace_dir, worktree_base,
                conflict_resolver=conflict_resolver,
                symlink_dirs=symlink_dirs,
            )
            on_complete_fn(result)

            if result.get("success") and result.get("merged"):
                with _count_lock:
                    success_count += 1

    # Launch workers with staggered start
    threads = []
    for i in range(max_workers):
        t = threading.Thread(target=_worker, args=(i,), daemon=True)
        threads.append(t)
        t.start()
        if i < max_workers - 1:
            time.sleep(3)  # Stagger copilot launches

    # Wait for all workers to finish
    for t in threads:
        t.join()

    # Final cleanup
    cleanup_worktrees(workspace_dir, worktree_base)

    return success_count
