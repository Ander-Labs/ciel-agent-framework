from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class CielError(Exception):
    """Base Ciel error."""


class ProviderError(CielError):
    """Model/provider error."""


class ToolError(CielError):
    """Tool execution error."""


class ApprovalDenied(CielError):
    """Execution denied by approval policy."""


class TenantRequired(CielError):
    """Tenant context is required for the requested operation."""


class SandboxError(CielError):
    """Sandbox execution error."""


class EventPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass
class Event:
    evt: str
    priority: EventPriority = EventPriority.NORMAL
    data: Dict[str, Any] = field(default_factory=dict)
