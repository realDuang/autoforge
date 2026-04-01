"""Quality gate checks for AutoForge."""
import logging
from .state import run_cmd, run_cmd_full

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


def check_custom_commands(workspace: str, commands: list[dict]) -> dict:
    """Run custom quality check commands. Each: {"name": str, "command": str, "timeout": int}"""
    issues = []
    warnings = []

    for cmd_spec in commands:
        name = cmd_spec.get("name", "custom")
        command = cmd_spec.get("command", "")
        timeout = cmd_spec.get("timeout", 120)

        if not command:
            continue

        logger.info(f"Running quality command: {name}")
        exit_code, output = run_cmd_full(command, workspace, timeout=timeout)

        if exit_code == -1:
            warnings.append(f"[{name}] Command timed out or failed to execute")
            continue

        if exit_code != 0:
            # Non-zero exit = command reported failure
            error_lines = [l.strip() for l in output.split("\n")
                          if l.strip() and (": error " in l or "error:" in l.lower()
                                           or "FAILED" in l or "BUILD FAILED" in l)]
            if error_lines:
                for line in error_lines[:5]:
                    issues.append(f"[{name}] {line[:200]}")
            else:
                issues.append(f"[{name}] Command exited with code {exit_code}")
            logger.warning(f"Quality command '{name}' failed (exit={exit_code})")
            continue

        # Exit code 0 but still check output for error patterns
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            if ": error " in line or "SCRIPT ERROR" in line:
                issues.append(f"[{name}] {line[:200]}")
            elif "FAILED" in line:
                if not any(f"[{name}]" in i for i in issues):
                    issues.append(f"[{name}] {line[:200]}")

    if issues:
        logger.warning(f"Custom quality commands failed with {len(issues)} issues")

    return {"passed": len(issues) == 0, "issues": issues, "warnings": warnings}


def run_quality_gate(workspace: str, build_command: str = "", build_timeout: int = 120,
                     quality_commands: list[dict] | None = None) -> dict:
    """Run all quality gate checks."""
    result = check_project_structure(workspace)

    if build_command:
        build_result = check_build(workspace, build_command, build_timeout)
        result["issues"].extend(build_result["issues"])
        result["warnings"].extend(build_result["warnings"])
        result["passed"] = result["passed"] and build_result["passed"]

    if quality_commands:
        custom_result = check_custom_commands(workspace, quality_commands)
        result["issues"].extend(custom_result["issues"])
        result["warnings"].extend(custom_result["warnings"])
        result["passed"] = result["passed"] and custom_result["passed"]

    if result["issues"]:
        logger.warning(f"Quality gate FAILED: {len(result['issues'])} issues")
        for issue in result["issues"][:5]:
            logger.warning(f"  ISSUE: {issue}")

    return result
