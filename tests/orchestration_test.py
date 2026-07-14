from __future__ import annotations

import asyncio

import pytest

from ciel.orchestration.budget import AgentCounter, Budget, RateLimiter
from ciel.orchestration.supervisor import Supervisor, Worker, WorkerContext


async def _run_async(coro):
    return coro


def test_supervisor_happy_path():
    async def worker(ctx):
        return {"ctx": ctx.step_id}

    supervisor = Supervisor(max_attempts=2, timeout_s=1.0)
    result = asyncio.run(supervisor.run("step-1", worker, {"x": 1}))
    assert result.output == {"ctx": "step-1"}
    assert result.attempts == 1
    assert result.failed is False


def test_supervisor_retry_then_success():
    attempts = []

    async def worker(ctx):
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("transient")
        return {"ok": True}

    supervisor = Supervisor(max_attempts=3, timeout_s=1.0)
    result = asyncio.run(supervisor.run("step-1", worker, {}))
    assert result.output == {"ok": True}
    assert result.attempts == 2


def test_supervisor_timeout_exhaust_retries():
    async def worker(ctx):
        await asyncio.sleep(2)
        return {}

    supervisor = Supervisor(max_attempts=2, timeout_s=0.1)
    result = asyncio.run(supervisor.run("step-1", worker, {}))
    assert result.failed is True
    assert result.attempts == 2


def test_budget_tool_exceeded():
    counter = AgentCounter(agent_id="a1")
    budget = Budget(max_tools=1)
    counter.consume_tool(1)
    assert counter.exceed(budget) == "tool budget exceeded"


def test_rate_limiter_rejects_after_limit():
    limiter = RateLimiter()
    assert limiter.check("tenant:1", limit=2) is None
    assert limiter.check("tenant:1", limit=2) is None
    assert limiter.check("tenant:1", limit=2) == "rate limit exceeded"
