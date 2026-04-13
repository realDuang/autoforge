"""Prompt generation for AutoForge analyst and builder sessions.

Loads prompt templates from the templates/ directory and fills them with
project-specific variables. Supports language switching (en/zh).
"""
import os
from typing import Optional

# Package directory for built-in templates
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _read_file(path: str, max_chars: int = 8000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        if len(content) >= max_chars:
            content += "\n... (truncated)"
        return content
    except OSError:
        return "(file not found)"


def _load_template(name: str, language: str = "en", templates_dir: str = "") -> str:
    """Load a prompt template by name and language.

    Search order:
    1. Custom templates_dir (if provided)
    2. Built-in templates/{language}/
    3. Built-in templates/en/ (fallback)
    """
    candidates = []
    if templates_dir:
        candidates.append(os.path.join(templates_dir, language, f"{name}.md"))
        if language != "en":
            candidates.append(os.path.join(templates_dir, "en", f"{name}.md"))
    candidates.append(os.path.join(_TEMPLATES_DIR, language, f"{name}.md"))
    if language != "en":
        candidates.append(os.path.join(_TEMPLATES_DIR, "en", f"{name}.md"))

    for path in candidates:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()

    raise FileNotFoundError(f"Template not found: {name}.md (language={language})")


def _format_completed_tasks(tasks: list[dict]) -> str:
    if not tasks:
        return "(none yet)"
    lines = []
    for t in tasks:
        lines.append(f"- [{t.get('area', '?')}] {t.get('title', '?')}")
    return "\n".join(lines)


def _format_areas(areas: list[str]) -> str:
    if not areas:
        return "(no area data yet — this is likely the first run)"
    return "\n".join(f"- {a}" for a in areas)


def _gather_knowledge_summary_text(knowledge_dir: str) -> str:
    """Read knowledge base files and produce a summary."""
    if not os.path.isdir(knowledge_dir):
        return "(knowledge base not yet created — you should create it)"

    lines = []
    for root, dirs, files in os.walk(knowledge_dir):
        dirs.sort()
        for fname in sorted(files):
            if fname.endswith(".md"):
                rel = os.path.relpath(os.path.join(root, fname), knowledge_dir)
                lines.append(f"- {rel}")
    if not lines:
        return "(knowledge base directory exists but is empty — populate it)"
    return "\n".join(lines)


def generate_analyst_prompt(
    seed_content: str,
    project_state: dict,
    knowledge_dir: str,
    knowledge_db_summary: dict,
    perspective: dict,
    recent_completed: list[dict],
    least_touched_areas: list[str],
    loop_count: int,
    data_dir: str = ".autoforge",
    phases: list[str] | None = None,
    language: str = "en",
    templates_dir: str = "",
) -> str:
    """Generate the analyst session prompt using a template."""

    kb_file_list = _gather_knowledge_summary_text(knowledge_dir)
    completed_text = _format_completed_tasks(recent_completed)
    areas_text = _format_areas(least_touched_areas)
    kb_stats = knowledge_db_summary
    kb_level_dist = kb_stats.get('by_level', {})
    data_dir_label = data_dir.replace("\\", "/")

    if phases is None:
        phases = ["BUILD", "TEST", "FIX"]

    if language == "zh":
        phase_labels = {"BUILD": "新功能", "TEST": "编写测试", "FIX": "修复问题"}
        phase_text = "、".join(f"{p}（{phase_labels.get(p, p)}）" for p in phases if p != "EVOLVE")
    else:
        phase_labels = {"BUILD": "new features", "TEST": "write tests", "FIX": "fix issues"}
        phase_text = ", ".join(f"{p} ({phase_labels.get(p, p)})" for p in phases if p != "EVOLVE")

    template = _load_template("analyst", language, templates_dir)

    variables = {
        "loop_count": loop_count,
        "seed_content": seed_content,
        "total_files": project_state.get('total_files', 0),
        "total_lines": project_state.get('total_lines', 0),
        "completed_count": len(recent_completed),
        "file_tree": project_state.get('file_tree', '(empty)'),
        "git_log": project_state.get('git_log', '(no commits yet)'),
        "kb_total": kb_stats.get('total', 0),
        "kb_implemented": kb_stats.get('implemented', 0),
        "kb_not_implemented": kb_stats.get('not_implemented', 0),
        "kb_level_dist": kb_level_dist,
        "kb_file_list": kb_file_list,
        "completed_text": completed_text,
        "perspective_label": perspective.get('label', '?'),
        "perspective_desc": perspective.get('desc', ''),
        "areas_text": areas_text,
        "quality_results": project_state.get('quality_results', '(no test results)'),
        "data_dir": data_dir_label,
        "phase_text": phase_text,
    }

    return template.format_map(variables)


def generate_builder_prompt(
    seed_content: str,
    task: dict,
    project_state: dict,
    knowledge_dir: str,
    related_knowledge_files: list[str],
    data_dir: str = ".autoforge",
    task_result_filename: str = "task_result.md",
    build_command: str = "",
    language: str = "en",
    templates_dir: str = "",
) -> str:
    """Generate the builder session prompt using a template."""

    # Read relevant knowledge entries
    kb_context_parts = []
    for kf in related_knowledge_files[:5]:  # limit to 5 files
        full_path = os.path.join(knowledge_dir, kf)
        if os.path.isfile(full_path):
            content = _read_file(full_path, max_chars=3000)
            kb_context_parts.append(f"### {kf}\n{content}")
    kb_context = "\n\n".join(kb_context_parts) if kb_context_parts else "(no related knowledge entries)"

    # Get seed summary (first 1500 chars — includes tech stack + resource info)
    seed_summary = seed_content[:1500]
    if len(seed_content) > 1500:
        seed_summary += "\n..."

    data_dir_label = data_dir.replace("\\", "/")

    template = _load_template("builder", language, templates_dir)

    variables = {
        "seed_summary": seed_summary,
        "task_title": task.get('title', '?'),
        "task_description": task.get('description', '?'),
        "task_area": task.get("area", "general"),
        "task_priority": task.get('priority', 5),
        "total_files": project_state.get('total_files', 0),
        "total_lines": project_state.get('total_lines', 0),
        "file_tree": project_state.get('file_tree', '(empty)'),
        "kb_context": kb_context,
        "git_log": project_state.get('git_log', '(no commits yet)'),
        "data_dir": data_dir_label,
        "task_result_filename": task_result_filename,
    }

    return template.format_map(variables)


def _parse_acceptance_criteria(task: dict) -> str:
    """Extract and format acceptance criteria from a task dict."""
    import json as _json
    criteria = task.get("acceptance_criteria")
    if isinstance(criteria, str):
        try:
            criteria = _json.loads(criteria)
        except (ValueError, TypeError):
            criteria = None
    if criteria and isinstance(criteria, list):
        return "\n".join(f"- {c}" for c in criteria)
    return "(none specified — infer from task description)"


def generate_contract_prompt(
    seed_content: str,
    task: dict,
    project_state: dict,
    knowledge_dir: str,
    related_knowledge_files: list[str],
    data_dir: str = ".autoforge",
    language: str = "en",
    templates_dir: str = "",
) -> str:
    """Generate the sprint contract proposal prompt."""
    kb_context_parts = []
    for kf in related_knowledge_files[:5]:
        full_path = os.path.join(knowledge_dir, kf)
        if os.path.isfile(full_path):
            content = _read_file(full_path, max_chars=3000)
            kb_context_parts.append(f"### {kf}\n{content}")
    kb_context = "\n\n".join(kb_context_parts) if kb_context_parts else "(no related knowledge entries)"

    seed_summary = seed_content[:1500]
    if len(seed_content) > 1500:
        seed_summary += "\n..."

    data_dir_label = data_dir.replace("\\", "/")
    template = _load_template("contract", language, templates_dir)

    variables = {
        "seed_summary": seed_summary,
        "task_title": task.get("title", "?"),
        "task_description": task.get("description", "?"),
        "task_area": task.get("area", "general"),
        "acceptance_criteria": _parse_acceptance_criteria(task),
        "total_files": project_state.get("total_files", 0),
        "total_lines": project_state.get("total_lines", 0),
        "file_tree": project_state.get("file_tree", "(empty)"),
        "kb_context": kb_context,
        "data_dir": data_dir_label,
    }

    return template.format_map(variables)


def generate_contract_review_prompt(
    task: dict,
    contract: dict,
    project_state: dict,
    data_dir: str = ".autoforge",
    language: str = "en",
    templates_dir: str = "",
) -> str:
    """Generate the contract review prompt for the reviewer agent."""
    # Format contract criteria
    vc = contract.get("verification_criteria", [])
    if vc:
        criteria_lines = []
        for c in vc:
            criteria_lines.append(f"- [{c.get('id', '?')}] ({c.get('type', '?')}) {c.get('description', '?')}")
        contract_criteria = "\n".join(criteria_lines)
    else:
        contract_criteria = "(no criteria specified)"

    files = contract.get("files_to_modify", [])
    contract_files = ", ".join(files) if files else "(not specified)"

    data_dir_label = data_dir.replace("\\", "/")
    template = _load_template("contract_review", language, templates_dir)

    variables = {
        "task_title": task.get("title", "?"),
        "task_description": task.get("description", "?"),
        "task_area": task.get("area", "general"),
        "acceptance_criteria": _parse_acceptance_criteria(task),
        "contract_approach": contract.get("approach", "(not specified)"),
        "contract_files": contract_files,
        "contract_criteria": contract_criteria,
        "file_tree": project_state.get("file_tree", "(empty)"),
        "data_dir": data_dir_label,
    }

    return template.format_map(variables)


def build_review_contract_section(contract: dict | None, language: str = "en") -> tuple[str, str]:
    """Build the contract section and criteria_results hint for the reviewer template.

    Returns (contract_section, criteria_results_hint) strings.
    """
    if not contract:
        return ("", '"(no contract — skip this field)"')

    vc = contract.get("verification_criteria", [])
    if not vc:
        return ("", '"(no contract — skip this field)"')

    criteria_lines = []
    results_example = []
    for c in vc:
        cid = c.get("id", "?")
        criteria_lines.append(f"- **{cid}** ({c.get('type', '?')}): {c.get('description', '?')}")
        results_example.append(f'{{"id": "{cid}", "pass": true, "note": ""}}')

    if language == "zh":
        header = "## Sprint 合同验证标准\n\n以下是实现前协商的验证标准。请逐条对照代码变更进行检查：\n"
    else:
        header = "## Sprint Contract Verification Criteria\n\nThe following criteria were agreed upon before implementation. Check each one against the code changes:\n"

    section = header + "\n".join(criteria_lines)
    hint = "[" + ", ".join(results_example) + "]"

    return (section, hint)


def find_related_knowledge_files(knowledge_dir: str, area: str, area_keywords: dict | None = None) -> list[str]:
    """Find knowledge base files related to a given area."""
    if not os.path.isdir(knowledge_dir):
        return []

    related = []
    area_lower = area.lower()
    keywords = _get_area_keywords(area_lower, area_keywords)

    for root, dirs, files in os.walk(knowledge_dir):
        dirs.sort()
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(root, fname), knowledge_dir)
            fname_lower = fname.lower()
            # Match by area keyword in filename
            if area_lower in fname_lower or any(
                kw in fname_lower for kw in keywords
            ):
                related.append(rel)

    # If nothing matched, return overview files
    if not related:
        for root, dirs, files in os.walk(knowledge_dir):
            for fname in sorted(files):
                if fname.endswith(".md") and ("overview" in fname.lower() or "L1" in fname):
                    related.append(
                        os.path.relpath(os.path.join(root, fname), knowledge_dir)
                    )
    return related[:10]


def _get_area_keywords(area: str, custom_keywords: dict | None = None) -> list[str]:
    """Get search keywords for an area. Uses custom mapping if provided, otherwise empty fallback."""
    if custom_keywords:
        return custom_keywords.get(area, [area])
    return [area]
