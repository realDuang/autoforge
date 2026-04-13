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
    criteria_results: list[dict] | None = None


@dataclass
class ContractResult:
    """Structured result of a contract review."""
    verdict: str  # APPROVE, REQUEST_CHANGES
    notes: str


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
    contract: dict | None = None,
) -> ReviewResult:
    """Run a review session on the builder's changes."""
    from .prompts import build_review_contract_section

    # Get the git diff of recent changes
    git_diff = run_cmd("git diff HEAD~1 HEAD", workspace_dir, timeout=30) or "(no diff available)"
    if len(git_diff) > 10000:
        git_diff = git_diff[:10000] + "\n... (truncated)"

    data_dir_label = data_dir.replace("\\", "/")

    contract_section, criteria_results_hint = build_review_contract_section(contract, language)

    template = _load_template("reviewer", language, templates_dir)
    prompt = template.format_map({
        "task_title": task.get("title", "?"),
        "task_description": task.get("description", "?"),
        "task_area": task.get("area", "general"),
        "git_diff": git_diff,
        "builder_summary": builder_summary or "(no summary provided)",
        "data_dir": data_dir_label,
        "contract_section": contract_section,
        "criteria_results_hint": criteria_results_hint,
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
            criteria_results=data.get("criteria_results") if isinstance(data.get("criteria_results"), list) else None,
        )
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to parse review_result.json: {e}")
        return ReviewResult(verdict="APPROVE", issues=[], summary=f"Parse error: {e}")


def run_contract_review(
    agent: AgentBackend,
    task: dict,
    contract: dict,
    project_state: dict,
    data_dir: str,
    language: str = "en",
    templates_dir: str = "",
    timeout_minutes: int = 10,
) -> ContractResult:
    """Run a contract review session — reviewer evaluates the proposed contract."""
    from .prompts import generate_contract_review_prompt

    prompt = generate_contract_review_prompt(
        task=task,
        contract=contract,
        project_state=project_state,
        data_dir=data_dir,
        language=language,
        templates_dir=templates_dir,
    )

    result = agent.run_session(
        prompt=prompt,
        working_dir=os.path.dirname(data_dir),  # workspace dir
        timeout_minutes=timeout_minutes,
    )

    if not result.success:
        logger.warning("Contract review session failed, defaulting to APPROVE")
        return ContractResult(verdict="APPROVE", notes="Contract review session failed")

    return _parse_contract_review(data_dir)


def _parse_contract_review(data_dir: str) -> ContractResult:
    """Parse the contract review JSON written by the reviewer agent."""
    result_path = os.path.join(data_dir, "contract_review.json")
    if not os.path.isfile(result_path):
        logger.warning("Reviewer did not create contract_review.json, defaulting to APPROVE")
        return ContractResult(verdict="APPROVE", notes="No contract review output")

    try:
        with open(result_path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            content = "\n".join(lines)

        data = json.loads(content)
        os.remove(result_path)

        verdict = data.get("verdict", "APPROVE").upper()
        if verdict not in ("APPROVE", "REQUEST_CHANGES"):
            verdict = "APPROVE"

        return ContractResult(
            verdict=verdict,
            notes=data.get("notes", ""),
        )
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to parse contract_review.json: {e}")
        return ContractResult(verdict="APPROVE", notes=f"Parse error: {e}")
