from importlib.metadata import version as _pkg_version, PackageNotFoundError

try:
    __version__ = _pkg_version("ciel")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.4.0"

from ciel.security import ApprovalPolicy
from ciel.api import Agent, AgentResponse, Context, ToolFunction, skill, teach, tool
from ciel.studio import (
    StudioStore,
    create_studio_router,
    get_studio_store,
    install_studio_support,
)

__all__ = [
    "__version__",
    "ApprovalPolicy",
    # High-level Developer Experience API (Fase 10 / v0.4.0)
    "Agent",
    "AgentResponse",
    "Context",
    "ToolFunction",
    "tool",
    # Fase 12 Item 5 — skill decorator integrated with ciel.Agent
    "skill",
    "teach",
    # Fase 13 / F19 — Ciel Studio (observability dashboard)
    "StudioStore",
    "get_studio_store",
    "install_studio_support",
    "create_studio_router",
]
