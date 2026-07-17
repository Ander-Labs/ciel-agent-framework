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
from ciel.studio_trace import (
    GraphTraceStore,
    attach_trace,
    create_trace_router,
    get_trace_store,
)
from ciel.studio_cost import (
    CostDashboardStore,
    attach_cost_tracking,
    create_cost_router,
    get_cost_store,
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
    # Fase 13 / F20 — Ciel Studio: graph trace + replay
    "GraphTraceStore",
    "attach_trace",
    "get_trace_store",
    "create_trace_router",
    # Fase 13 / F21 — Ciel Studio: cost dashboard
    "CostDashboardStore",
    "attach_cost_tracking",
    "get_cost_store",
    "create_cost_router",
]
