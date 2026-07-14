from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Budget:
    max_tools: int = 16
    max_tokens: Optional[int] = None
    max_seconds: Optional[float] = None


@dataclass
class AgentCounter:
    agent_id: str
    tenant_id: Optional[str] = None
    used_tools: int = 0
    used_tokens: int = 0
    start_ns: int = 0

    def consume_tool(self, count: int = 1) -> None:
        self.used_tools += count

    def consume_tokens(self, count: int) -> None:
        self.used_tokens += count

    def elapsed_seconds(self) -> float:
        import time
        return (time.perf_counter_ns() - self.start_ns) / 1e9

    def exceed(self, budget: Budget) -> Optional[str]:
        if self.used_tools >= budget.max_tools:
            return "tool budget exceeded"
        if budget.max_tokens is not None and self.used_tokens >= budget.max_tokens:
            return "token budget exceeded"
        if budget.max_seconds is not None and self.elapsed_seconds() >= budget.max_seconds:
            return "wall-clock budget exceeded"
        return None


class RateLimiter:
    def __init__(self) -> None:
        self._calls: Dict[str, int] = {}

    def check(self, key: str, limit: int) -> Optional[str]:
        current = self._calls.get(key, 0) + 1
        self._calls[key] = current
        if current > limit:
            return "rate limit exceeded"
        return None
