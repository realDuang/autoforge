"""Abstract base class for AI agent backends."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class SessionResult:
    """Result of an agent session."""
    success: bool
    output: str
    stderr: str
    exit_code: int
    duration_seconds: float


class AgentBackend(ABC):
    """Abstract interface for AI coding agent backends.

    Each backend translates a prompt + working directory into a subprocess
    (or SDK call) that drives an AI agent to completion.
    """

    def __init__(self, config: dict):
        """Initialize with backend-specific configuration.

        Args:
            config: Dict of backend config (model, timeout, path, etc.)
        """
        self.config = config

    @abstractmethod
    def run_session(
        self,
        prompt: str,
        working_dir: str,
        timeout_minutes: int = 30,
        prompt_save_path: Optional[str] = None,
        permission_profile: Optional[object] = None,
    ) -> SessionResult:
        """Run an agent session with the given prompt.

        Args:
            prompt: The full prompt text.
            working_dir: Working directory for the agent.
            timeout_minutes: Hard timeout for the session.
            prompt_save_path: Optional path to save the prompt for debugging.
            permission_profile: Optional PermissionProfile for sandboxing.

        Returns:
            SessionResult with success status, output, and timing.
        """

    @abstractmethod
    def check_available(self) -> bool:
        """Check if this agent backend is available on the system."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this backend."""
