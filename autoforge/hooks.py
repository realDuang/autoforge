"""Deterministic lifecycle hooks for AutoForge.

Hooks run shell commands at specific stages of the build pipeline,
providing guaranteed quality enforcement independent of agent prompts.

Stages:
    post_build  — after agent session completes, before marking success
    pre_merge   — before merging worktree to main (parallel mode)
    post_merge  — after successful merge to main
"""
import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import Optional

from .state import run_cmd_full

logger = logging.getLogger("autoforge")


@dataclass
class HookSpec:
    """Specification for a single hook."""
    name: str
    command: str
    timeout: int = 120
    required: bool = True  # If required and fails, abort the pipeline step


@dataclass
class HookResult:
    """Result of running hooks at a stage."""
    passed: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class HookRunner:
    """Runs lifecycle hooks at specified stages."""

    def __init__(self, hooks_config: dict[str, list[dict]], clean_dirs: list[str] | None = None):
        """Initialize from hooks configuration.

        Args:
            hooks_config: Dict mapping stage names to lists of hook specs.
                Example: {"post_build": [{"name": "build", "command": "make"}]}
            clean_dirs: Optional list of relative directory paths to remove
                before running hooks (e.g. build caches that conflict in worktrees).
        """
        self.hooks: dict[str, list[HookSpec]] = {}
        self.clean_dirs = clean_dirs or []
        for stage, specs in hooks_config.items():
            self.hooks[stage] = [
                HookSpec(
                    name=s.get("name", "hook"),
                    command=s.get("command", ""),
                    timeout=s.get("timeout", 120),
                    required=s.get("required", True),
                )
                for s in specs
                if s.get("command")
            ]

    def run_hooks(self, stage: str, working_dir: str) -> HookResult:
        """Run all hooks for a given stage.

        Args:
            stage: Hook stage name (e.g. "post_build", "pre_merge").
            working_dir: Directory to run commands in.

        Returns:
            HookResult with pass/fail status and any issues.
        """
        specs = self.hooks.get(stage, [])
        if not specs:
            return HookResult(passed=True)

        # Clean configured cache directories to prevent stale build artifacts
        # from causing false failures (especially in parallel worktrees).
        for rel_dir in self.clean_dirs:
            abs_dir = os.path.join(working_dir, rel_dir)
            if os.path.isdir(abs_dir):
                try:
                    shutil.rmtree(abs_dir)
                    logger.debug(f"Cleaned cache dir: {abs_dir}")
                except OSError:
                    pass  # Best-effort cleanup

        issues = []
        warnings = []

        for hook in specs:
            logger.info(f"Running hook [{stage}] {hook.name}: {hook.command}")
            exit_code, output = run_cmd_full(hook.command, working_dir, timeout=hook.timeout)

            if exit_code == -1:
                msg = f"[{hook.name}] Command timed out or failed to execute"
                if hook.required:
                    issues.append(msg)
                else:
                    warnings.append(msg)
                continue

            if exit_code != 0:
                error_lines = _extract_error_lines(output)
                if error_lines:
                    for line in error_lines[:5]:
                        issues.append(f"[{hook.name}] {line[:200]}")
                else:
                    issues.append(f"[{hook.name}] Command exited with code {exit_code}")

                if not hook.required:
                    # Move issues to warnings for non-required hooks
                    warnings.extend(issues[-len(error_lines or [1]):])
                    issues = issues[:-len(error_lines or [1])]

                logger.warning(f"Hook '{hook.name}' failed (exit={exit_code})")
                continue

            # Exit code 0 but still check output for error patterns
            for line in output.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if ": error " in line or "SCRIPT ERROR" in line:
                    issues.append(f"[{hook.name}] {line[:200]}")
                elif "FAILED" in line:
                    if not any(f"[{hook.name}]" in i for i in issues):
                        issues.append(f"[{hook.name}] {line[:200]}")

        passed = len(issues) == 0

        if issues:
            logger.warning(f"Hooks [{stage}] FAILED: {len(issues)} issues")
            for issue in issues[:5]:
                logger.warning(f"  ISSUE: {issue}")

        return HookResult(passed=passed, issues=issues, warnings=warnings)


def _extract_error_lines(output: str) -> list[str]:
    """Extract error lines from command output."""
    return [
        l.strip() for l in output.split("\n")
        if l.strip() and (
            ": error " in l or "error:" in l.lower()
            or "FAILED" in l or "BUILD FAILED" in l
        )
    ]


def build_hooks_from_config(
    hooks_raw: dict,
    build_command: str = "",
    build_timeout: int = 120,
    quality_commands: list[dict] | None = None,
    clean_dirs: list[str] | None = None,
) -> HookRunner:
    """Build a HookRunner from config, with backward compatibility.

    If explicit hooks config is provided, use it directly.
    Otherwise, auto-generate hooks from legacy build_command and quality_commands.
    """
    if hooks_raw:
        return HookRunner(hooks_raw, clean_dirs=clean_dirs)

    # Backward compat: synthesize hooks from legacy config
    post_build_hooks = []

    if build_command:
        post_build_hooks.append({
            "name": "build",
            "command": build_command,
            "timeout": build_timeout,
            "required": True,
        })

    if quality_commands:
        for cmd_spec in quality_commands:
            post_build_hooks.append({
                "name": cmd_spec.get("name", "quality"),
                "command": cmd_spec.get("command", ""),
                "timeout": cmd_spec.get("timeout", 120),
                "required": True,
            })

    hooks_config = {}
    if post_build_hooks:
        hooks_config["post_build"] = post_build_hooks

    return HookRunner(hooks_config, clean_dirs=clean_dirs)
