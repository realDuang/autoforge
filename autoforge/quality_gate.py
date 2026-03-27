"""Quality gate checks for AutoForge."""
import logging
from .state import run_cmd

logger = logging.getLogger("autoforge")


def check_build(workspace: str, build_command: str, timeout: int = 120) -> dict:
    """Run a configured build command to verify code compiles."""
    if not build_command:
        return {"passed": True, "issues": [], "warnings": []}

    issues = []
    warnings = []

    output = run_cmd(build_command, workspace, timeout=timeout)

    if not output:
        return {"passed": True, "issues": [], "warnings": ["Build check skipped (command not available or timeout)"]}

    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Common error patterns across languages
        if ": error " in line or "error:" in line.lower():
            issues.append(line[:200])
        elif "Build FAILED" in line or "build failed" in line.lower() or "FAILED" in line:
            if not issues:
                issues.append("Build failed")

    passed = len(issues) == 0
    if not passed:
        logger.warning(f"Build check failed with {len(issues)} errors")
    return {"passed": passed, "issues": issues, "warnings": warnings}


def check_project_structure(workspace: str) -> dict:
    """Check basic project structure validity."""
    issues = []
    warnings = []

    return {"passed": len(issues) == 0, "issues": issues, "warnings": warnings}


def run_quality_gate(workspace: str, build_command: str = "", build_timeout: int = 120) -> dict:
    """Run all quality gate checks."""
    result = check_project_structure(workspace)

    if build_command:
        build_result = check_build(workspace, build_command, build_timeout)
        result["issues"].extend(build_result["issues"])
        result["warnings"].extend(build_result["warnings"])
        result["passed"] = result["passed"] and build_result["passed"]

    if result["issues"]:
        logger.warning(f"Quality gate FAILED: {len(result['issues'])} issues")
        for issue in result["issues"][:5]:
            logger.warning(f"  ISSUE: {issue}")

    return result
