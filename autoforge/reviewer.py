"""Writer-Reviewer adversarial pattern for AutoForge.

Optionally interposes a review stage between builder completion and merge.
A separate agent (in a clean context) reviews the builder's changes and
can approve, request changes, or reject them.
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from .agents.base import AgentBackend, SessionResult
from .prompts import _load_template
from .state import run_cmd

logger = logging.getLogger("autoforge")


@dataclass
class ReviewResult:
    """Structured result of a code review."""
    verdict: str  # APPROVE, REQUEST_CHANGES, REJECT
    issues: list[str]
    summary: str


def run_review(
    agent: AgentBackend,
    task: dict,
    builder_summary: str,
    workspace_dir: str,
    data_dir: str,
    reviewer_config: object = None,
    language: str = "en",
    templates_dir: str = "",
    timeout_minutes: int = 15,
) -> ReviewResult:
    """Run a review session on the builder's changes."""
    # Get the git diff of recent changes
    git_diff = run_cmd("git diff HEAD~1 HEAD", workspace_dir, timeout=30) or "(no diff available)"
    if len(git_diff) > 10000:
        git_diff = git_diff[:10000] + "\n... (truncated)"

    data_dir_label = data_dir.replace("\\", "/")

    template = _load_template("reviewer", language, templates_dir)
    prompt = template.format_map({
        "task_title": task.get("title", "?"),
        "task_description": task.get("description", "?"),
        "task_area": task.get("area", "general"),
        "git_diff": git_diff,
        "builder_summary": builder_summary or "(no summary provided)",
        "data_dir": data_dir_label,
    })

    result = agent.run_session(
        prompt=prompt,
        working_dir=workspace_dir,
        timeout_minutes=timeout_minutes,
    )

    if not result.success:
        logger.warning("Reviewer session failed, defaulting to APPROVE")
        return ReviewResult(verdict="APPROVE", issues=[], summary="Reviewer session failed")

    return _parse_review_result(data_dir)


def _parse_review_result(data_dir: str) -> ReviewResult:
    """Parse the review result JSON written by the reviewer agent."""
    result_path = os.path.join(data_dir, "review_result.json")
    if not os.path.isfile(result_path):
        logger.warning("Reviewer did not create review_result.json, defaulting to APPROVE")
        return ReviewResult(verdict="APPROVE", issues=[], summary="No review output")

    try:
        with open(result_path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        # Handle markdown code fences
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            content = "\n".join(lines)

        data = json.loads(content)
        os.remove(result_path)

        verdict = data.get("verdict", "APPROVE").upper()
        if verdict not in ("APPROVE", "REQUEST_CHANGES", "REJECT"):
            verdict = "APPROVE"

        return ReviewResult(
            verdict=verdict,
            issues=data.get("issues", []),
            summary=data.get("summary", ""),
        )
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to parse review_result.json: {e}")
        return ReviewResult(verdict="APPROVE", issues=[], summary=f"Parse error: {e}")
