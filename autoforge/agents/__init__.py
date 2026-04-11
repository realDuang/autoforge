"""Agent backend registry for AutoForge."""
from .base import AgentBackend, SessionResult
from .claude_code import ClaudeCodeBackend
from .ghcp import GHCPBackend

# Registry: backend name -> class
_BACKENDS: dict[str, type[AgentBackend]] = {
    "claude_code": ClaudeCodeBackend,
    "ghcp": GHCPBackend,
}


def get_backend(name: str, config: dict) -> AgentBackend:
    """Instantiate an agent backend by name.

    Args:
        name: Backend identifier (e.g. "claude_code").
        config: Backend-specific configuration dict.

    Returns:
        An initialized AgentBackend instance.

    Raises:
        ValueError: If the backend name is not registered.
    """
    cls = _BACKENDS.get(name)
    if cls is None:
        available = ", ".join(sorted(_BACKENDS.keys()))
        raise ValueError(f"Unknown agent backend: {name!r}. Available: {available}")
    return cls(config)


def register_backend(name: str, cls: type[AgentBackend]):
    """Register a custom agent backend."""
    _BACKENDS[name] = cls


__all__ = ["AgentBackend", "SessionResult", "get_backend", "register_backend"]
