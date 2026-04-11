"""Permission profiles for agent sessions.

Maps high-level permission modes to agent-backend-specific flags,
enabling least-privilege enforcement per role (analyst, builder, reviewer).
"""
from dataclasses import dataclass, field


@dataclass
class PermissionProfile:
    """Permission profile for an agent session.

    Modes:
        full     — agent can read, write, execute anything (default for builder)
        edit     — agent can read and edit files, limited shell access
        readonly — agent can only read files and search (default for analyst/reviewer)
    """
    mode: str = "full"
    allowed_tools: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=list)


# Default profiles per role
ROLE_DEFAULTS = {
    "analyst": PermissionProfile(mode="readonly"),
    "builder": PermissionProfile(mode="full"),
    "reviewer": PermissionProfile(mode="readonly"),
}


def get_profile_for_role(role: str, overrides: dict | None = None) -> PermissionProfile:
    """Get the permission profile for a role, with optional overrides.

    Args:
        role: Role name ("analyst", "builder", "reviewer").
        overrides: Optional dict with mode/allowed_tools/denied_paths overrides.

    Returns:
        PermissionProfile for the role.
    """
    default = ROLE_DEFAULTS.get(role, PermissionProfile())

    if not overrides:
        return default

    return PermissionProfile(
        mode=overrides.get("mode", default.mode),
        allowed_tools=overrides.get("allowed_tools", default.allowed_tools),
        denied_paths=overrides.get("denied_paths", default.denied_paths),
    )
