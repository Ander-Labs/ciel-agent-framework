from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class WorkerResult:
    worker_id: str
    output: Any = None
    error: Optional[str] = None
    attempts: int = 0
    latency_ms: float = 0.0
    failed: bool = False


@dataclass
class WorkerContext:
    step_id: str
    worker_id: str
    payload: Optional[Dict[str, Any]] = None


Worker = Callable[[WorkerContext], Any]


class Supervisor:
    def __init__(
        self,
        max_attempts: int = 2,
        timeout_s: float = 2.0,
        budget: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        agent_counter: Optional[Any] = None,
        rate_limit: int = 0,
    ) -> None:
        self.max_attempts = max_attempts
        self.timeout_s = timeout_s
        self.budget = budget
        self.rate_limiter = rate_limiter
        self.agent_counter = agent_counter
        self.rate_limit = rate_limit
        self._results: Dict[str, WorkerResult] = {}

    async def run(
        self,
        step_id: str,
        worker: Worker,
        payload: Optional[Dict[str, Any]] = None,
        worker_id: str = "worker-1",
    ) -> WorkerResult:
        key = f"{step_id}:{worker_id}"
        if self.agent_counter is not None and self.budget is not None:
            exceeded = self.agent_counter.exceed(self.budget)
            if exceeded:
                result = WorkerResult(
                    worker_id=worker_id,
                    attempts=0,
                    failed=True,
                    error=f"budget rejection before run: {exceeded}",
                )
                self._results[key] = result
                return result
        if self.rate_limiter is not None and self.rate_limit > 0:
            rate_key = step_id or worker_id
            exceeded = self.rate_limiter.check(rate_key, self.rate_limit)
            if exceeded:
                result = WorkerResult(
                    worker_id=worker_id,
                    attempts=0,
                    failed=True,
                    error=f"rate limit rejection before run: {exceeded}",
                )
                self._results[key] = result
                return result
        attempt = 0
        start = time.perf_counter()
        while attempt < self.max_attempts:
            attempt += 1
            if self.agent_counter is not None:
                self.agent_counter.consume_tool(1)
            ctx = WorkerContext(step_id=step_id, worker_id=worker_id, payload=payload)
            try:
                output = await asyncio.wait_for(worker(ctx), timeout=self.timeout_s)
                result = WorkerResult(
                    worker_id=worker_id,
                    output=output,
                    attempts=attempt,
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                )
                self._results[key] = result
                return result
            except Exception as exc:
                if attempt >= self.max_attempts:
                    result = WorkerResult(
                        worker_id=worker_id,
                        attempts=attempt,
                        latency_ms=(time.perf_counter() - start) * 1000.0,
                        failed=True,
                        error=str(exc),
                    )
                    self._results[key] = result
                    return result
        return self._results[key]

    def results(self) -> Dict[str, WorkerResult]:
        return dict(self._results)
