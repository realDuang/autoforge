"""Claude Code CLI agent backend."""
import logging
import os
import subprocess
import time
from typing import Optional

from .base import AgentBackend, SessionResult

logger = logging.getLogger("autoforge")


def _permission_profile_to_args(profile) -> list[str]:
    """Translate a PermissionProfile to Claude Code CLI arguments.

    This is Claude Code-specific flag translation — other backends
    would implement their own version.
    """
    args = []
    if profile.mode == "full":
        args.append("--dangerously-skip-permissions")
    elif profile.mode == "edit":
        tools = profile.allowed_tools or ["Read", "Edit", "Write", "Glob", "Grep", "Bash"]
        args.extend(["--allowedTools", ",".join(tools)])
    elif profile.mode == "readonly":
        tools = profile.allowed_tools or ["Read", "Glob", "Grep"]
        args.extend(["--allowedTools", ",".join(tools)])
    return args


class ClaudeCodeBackend(AgentBackend):
    """Agent backend using the Claude Code CLI (claude command)."""

    @property
    def name(self) -> str:
        return "claude_code"

    def _get_path(self) -> str:
        return self.config.get("path", "claude")

    def _get_model(self) -> str:
        return self.config.get("model", "") or "claude-sonnet-4-20250514"

    def _get_effort(self) -> str:
        return self.config.get("effort", "high")

    def _get_extra_args(self) -> list[str]:
        return self.config.get("extra_args", [])

    def check_available(self) -> bool:
        try:
            result = subprocess.run(
                [self._get_path(), "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def run_session(
        self,
        prompt: str,
        working_dir: str,
        timeout_minutes: int = 30,
        prompt_save_path: Optional[str] = None,
        permission_profile: Optional[object] = None,
    ) -> SessionResult:
        from ..runner import is_shutdown_requested

        if prompt_save_path:
            os.makedirs(os.path.dirname(prompt_save_path), exist_ok=True)
            with open(prompt_save_path, "w", encoding="utf-8") as f:
                f.write(prompt)

        model = self._get_model()
        cmd = [
            self._get_path(),
            "-p", prompt,
            "--model", model,
            "--output-format", "text",
        ]

        # Apply permission profile or default to full access
        if permission_profile is not None:
            cmd.extend(_permission_profile_to_args(permission_profile))
        else:
            cmd.append("--dangerously-skip-permissions")

        extra = self._get_extra_args()
        if extra:
            cmd.extend(extra)

        logger.info(f"Running {self.name} session (model={model}, timeout={timeout_minutes}m)")
        logger.debug(f"Working dir: {working_dir}")

        start_time = time.time()
        deadline = start_time + timeout_minutes * 60

        try:
            # Remove CLAUDECODE env var to allow nested sessions
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            proc = subprocess.Popen(
                cmd, cwd=working_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", errors="replace",
                env=env,
            )

            while True:
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    if is_shutdown_requested():
                        logger.info("Shutdown requested, terminating agent session")
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        return SessionResult(
                            success=False, output="", stderr="SHUTDOWN",
                            exit_code=-2, duration_seconds=time.time() - start_time,
                        )
                    if time.time() > deadline:
                        logger.error(f"Agent session timed out after {timeout_minutes} minutes")
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        return SessionResult(
                            success=False, output="", stderr="TIMEOUT",
                            exit_code=-1, duration_seconds=time.time() - start_time,
                        )

            duration = time.time() - start_time
            output = stdout or ""
            stderr = stderr or ""

            if proc.returncode != 0:
                logger.warning(f"Agent exited with code {proc.returncode}")
                if stderr:
                    logger.warning(f"Stderr: {stderr[:500]}")
                if not stderr and duration < 30:
                    logger.warning(f"Agent crashed quickly ({duration:.1f}s) with no stderr")

            logger.info(f"Agent session completed in {duration:.1f}s (exit={proc.returncode})")

            return SessionResult(
                success=proc.returncode == 0,
                output=output, stderr=stderr,
                exit_code=proc.returncode, duration_seconds=duration,
            )

        except FileNotFoundError:
            logger.error(f"Agent CLI not found at: {self._get_path()}")
            return SessionResult(
                success=False, output="",
                stderr=f"FileNotFoundError: {self._get_path()}",
                exit_code=-1, duration_seconds=0,
            )
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Agent session failed: {e}")
            return SessionResult(
                success=False, output="", stderr=str(e),
                exit_code=-1, duration_seconds=duration,
            )
