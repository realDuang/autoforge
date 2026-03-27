"""Convergence detection for AutoForge."""
import json
from typing import Optional


def detect_convergence(
    recent_metrics: list[dict],
    check_window: int = 5,
    min_diff_lines: int = 50,
    max_file_overlap_ratio: float = 0.8,
    stagnation_threshold: int = 10,
) -> Optional[dict]:
    """
    Analyze recent metrics to detect convergence.
    Returns a dict with convergence info if detected, None otherwise.
    """
    if len(recent_metrics) < check_window:
        return None

    window = recent_metrics[:check_window]  # most recent first

    # Check 1: Git diff sizes shrinking to near zero
    diff_sizes = [m.get("git_diff_lines", 0) for m in window]
    if all(d < min_diff_lines for d in diff_sizes):
        if len(diff_sizes) >= 2:
            trend_declining = all(
                diff_sizes[i] <= diff_sizes[i + 1] + 5
                for i in range(len(diff_sizes) - 1)
            )
            if trend_declining:
                return {
                    "indicator": "shrinking_diffs",
                    "value": diff_sizes[0],
                    "message": f"Git diffs shrinking: {diff_sizes}",
                }

    # Check 2: Same files being modified repeatedly
    file_sets = []
    for m in window:
        files = m.get("modified_files", [])
        if isinstance(files, str):
            try:
                files = json.loads(files)
            except (json.JSONDecodeError, TypeError):
                files = []
        file_sets.append(set(files))

    non_empty = [fs for fs in file_sets if fs]
    if len(non_empty) >= 3:
        overlap = non_empty[0]
        for fs in non_empty[1:]:
            overlap = overlap.intersection(fs)

        if non_empty[-1]:
            overlap_ratio = len(overlap) / len(non_empty[-1])
            if overlap_ratio >= max_file_overlap_ratio:
                return {
                    "indicator": "file_overlap",
                    "value": overlap_ratio,
                    "message": f"Same files modified repeatedly: {overlap}",
                }

    # Check 3: Total lines stagnant
    line_counts = [m.get("total_lines", 0) for m in window]
    if line_counts:
        line_range = max(line_counts) - min(line_counts)
        if line_range < stagnation_threshold and all(lc > 0 for lc in line_counts):
            return {
                "indicator": "stagnant_lines",
                "value": line_range,
                "message": f"Code size stagnant: range={line_range} lines across {check_window} runs",
            }

    return None
