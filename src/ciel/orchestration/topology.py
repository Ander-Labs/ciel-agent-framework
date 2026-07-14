from __future__ import annotations

from typing import Any, Dict, List, Optional


class CeldaOrchestrationBudgetError(Exception):
    ...


class TopologyError(Exception):
    ...


class TopologyEngine:
    def __init__(
        self,
        agent_spec: Any,
        runner: Any,
        budget: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        rate_limits: Optional[Dict[str, int]] = None,
        counter_for_step: Optional[Any] = None,
    ) -> None:
        self.spec = agent_spec
        self.runner = runner
        self.budget = budget
        self.rate_limiter = rate_limiter
        self.rate_limits = rate_limits or {}
        self.counter_for_step = counter_for_step
        self._executed: Dict[str, Any] = {}

    async def _execute(self, step) -> Any:
        run_fn = getattr(self.runner, "run", self.runner)
        if not callable(run_fn):
            raise TypeError("runner must be callable or async-callable")
        candidate = run_fn(step)
        if hasattr(candidate, "__await__"):
            return await candidate
        return candidate

    async def run(self) -> Any:
        topology = getattr(self.spec, "topology", "pipeline")
        if topology == "pipeline":
            return await self._pipeline()
        if topology == "fan-out":
            return await self._fan_out()
        if topology == "debate":
            return await self._debate()
        raise TopologyError(f"topology '{topology}' unsupported")

    async def _reject_if_budget_or_rate_exceeded(self, step) -> None:
        if self.budget is None:
            return
        counter = self.counter_for_step(step) if callable(self.counter_for_step) else None
        if counter is None:
            return
        exceeded = counter.exceed(self.budget)
        if exceeded:
            raise TopologyError(f"budget rejection on step '{step.id}': {exceeded}")
        if self.rate_limiter is not None:
            limit = self.rate_limits.get(step.id, 0)
            if limit > 0:
                exceeded = self.rate_limiter.check(step.id, limit)
                if exceeded:
                    raise TopologyError(f"rate limit rejection on step '{step.id}': {exceeded}")

    async def _pipeline(self) -> List[Any]:
        results: List[Any] = []
        for step in self.spec.steps:
            missing = [name for name in getattr(step, "depends_on", []) if name not in self._executed]
            if missing:
                raise TopologyError(f"missing dependencies: {sorted(missing)}")
            await self._reject_if_budget_or_rate_exceeded(step)
            results.append(await self._execute(step))
            self._executed[step.id] = True
        return results

    async def _fan_out(self) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        for step in self.spec.steps:
            await self._reject_if_budget_or_rate_exceeded(step)
            results[step.id] = await self._execute(step)
            self._executed[step.id] = True
        return results

    async def _debate(self) -> List[Any]:
        if not self.spec.steps:
            return []
        primary, *rest = self.spec.steps
        await self._reject_if_budget_or_rate_exceeded(primary)
        output = await self._execute(primary)
        transcript: List[Any] = [output]
        for step in rest:
            await self._reject_if_budget_or_rate_exceeded(step)
            output = await self._execute(step)
            transcript.append(output)
        return transcript
