"""Shutdown coordination for AutoForge.

Provides the global shutdown mechanism used across all agent backends
and the orchestrator main loop.
"""
import threading

# Global shutdown flag — set by signal handler or orchestrator
_shutdown_event = threading.Event()


def request_shutdown():
    """Signal all running agent sessions to stop."""
    _shutdown_event.set()


def is_shutdown_requested() -> bool:
    return _shutdown_event.is_set()
