"""Copilot CLI runner for AutoForge."""
import subprocess
import os
import time
import logging
import signal
import threading
from typing import Optional

logger = logging.getLogger("autoforge")

# Global shutdown flag — set by signal handler or orchestrator
_shutdown_event = threading.Event()


def request_shutdown():
    """Signal all running copilot sessions to stop."""
    _shutdown_event.set()


def is_shutdown_requested() -> bool:
    return _shutdown_event.is_set()


def run_copilot_session(
    prompt: str,
    working_dir: str,
    copilot_path: str = "copilot",
    model: str = "claude-sonnet-4-20250514",
    effort: str = "high",
    timeout_minutes: int = 30,
    extra_args: Optional[list[str]] = None,
    prompt_save_path: Optional[str] = None,
) -> dict:
    """Run a copilot CLI session with the given prompt.

    Supports graceful shutdown via request_shutdown().
    """
    if prompt_save_path:
        os.makedirs(os.path.dirname(prompt_save_path), exist_ok=True)
        with open(prompt_save_path, "w", encoding="utf-8") as f:
            f.write(prompt)

    cmd = [
        copilot_path,
        "-p", prompt,
        "--yolo",
        "--autopilot",
        "--no-ask-user",
        "--model", model,
        "--effort", effort,
        "--no-auto-update",
    ]

    if extra_args:
        cmd.extend(extra_args)

    logger.info(f"Running copilot session (model={model}, timeout={timeout_minutes}m)")
    logger.debug(f"Working dir: {working_dir}")

    start_time = time.time()
    deadline = start_time + timeout_minutes * 60

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )

        # Poll until done, timeout, or shutdown requested
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=5)
                break  # Process finished
            except subprocess.TimeoutExpired:
                if _shutdown_event.is_set():
                    logger.info("Shutdown requested, terminating copilot session")
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return {
                        "success": False,
                        "output": "",
                        "stderr": "SHUTDOWN",
                        "exit_code": -2,
                        "duration_seconds": time.time() - start_time,
                    }
                if time.time() > deadline:
                    logger.error(f"Copilot session timed out after {timeout_minutes} minutes")
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return {
                        "success": False,
                        "output": "",
                        "stderr": "TIMEOUT",
                        "exit_code": -1,
                        "duration_seconds": time.time() - start_time,
                    }

        duration = time.time() - start_time
        output = stdout or ""
        stderr = stderr or ""

        if proc.returncode != 0:
            logger.warning(f"Copilot exited with code {proc.returncode}")
            if stderr:
                logger.warning(f"Stderr: {stderr[:500]}")
            if not stderr and duration < 30:
                logger.warning(f"Copilot crashed quickly ({duration:.1f}s) with no stderr")

        logger.info(f"Copilot session completed in {duration:.1f}s (exit={proc.returncode})")

        return {
            "success": proc.returncode == 0,
            "output": output,
            "stderr": stderr,
            "exit_code": proc.returncode,
            "duration_seconds": duration,
        }

    except FileNotFoundError:
        logger.error(f"Copilot CLI not found at: {copilot_path}")
        return {
            "success": False,
            "output": "",
            "stderr": f"FileNotFoundError: {copilot_path}",
            "exit_code": -1,
            "duration_seconds": 0,
        }
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Copilot session failed: {e}")
        return {
            "success": False,
            "output": "",
            "stderr": str(e),
            "exit_code": -1,
            "duration_seconds": duration,
        }


def check_copilot_available(copilot_path: str = "copilot") -> bool:
    """Check if copilot CLI is available."""
    try:
        result = subprocess.run(
            [copilot_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
