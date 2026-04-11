"""Session-level metrics tracking for AutoForge.

Records per-session performance data (timing, success rate, model used)
to enable data-driven harness tuning.
"""
import logging
from typing import Optional

logger = logging.getLogger("autoforge")


def record_session_metric(
    db,
    task_id: str,
    session_type: str,
    agent_backend: str,
    model: str,
    duration_seconds: float,
    exit_code: int,
    quality_passed: Optional[bool] = None,
    review_verdict: Optional[str] = None,
    merge_result: Optional[str] = None,
    phase: str = "",
    perspective: str = "",
):
    """Record a session metric to the database.

    Args:
        db: Database instance.
        task_id: ID of the task (or "" for analyst).
        session_type: "analyst", "builder", or "reviewer".
        agent_backend: Backend name (e.g. "claude_code").
        model: Model used (e.g. "claude-sonnet-4-20250514").
        duration_seconds: Session duration.
        exit_code: Process exit code.
        quality_passed: Whether quality hooks passed (None if not run).
        review_verdict: Reviewer verdict (None if not run).
        merge_result: Merge result for parallel mode (None if sequential).
        phase: Current phase.
        perspective: Current perspective ID.
    """
    db.record_session_metric(
        task_id=task_id,
        session_type=session_type,
        agent_backend=agent_backend,
        model=model,
        duration_seconds=duration_seconds,
        exit_code=exit_code,
        quality_passed=quality_passed,
        review_verdict=review_verdict,
        merge_result=merge_result,
        phase=phase,
        perspective=perspective,
    )


def print_stats(db):
    """Print a summary dashboard of session metrics."""
    stats = db.get_session_stats()
    if not stats:
        print("No session metrics recorded yet.")
        return

    print("\n=== AutoForge Session Metrics ===\n")

    for row in stats:
        print(f"  {row['session_type']:10s}  |  "
              f"total: {row['total']:4d}  |  "
              f"success: {row['successes']:4d}  |  "
              f"rate: {row['success_rate']:.0f}%  |  "
              f"avg time: {row['avg_duration']:.0f}s")

    print()
