from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ciel.orchestration import AgentSpec, AgentStep
from ciel.orchestration.budget import AgentCounter, Budget, RateLimiter
from ciel.orchestration.supervisor import Supervisor
from ciel.orchestration.topology import TopologyEngine


class SyncRunner:
    def __init__(self, mapping):
        self.mapping = mapping

    def run(self, step):
        return self.mapping.get(step.id, {"step_id": step.id})


class AsyncRunner:
    def __init__(self, mapping):
        self.mapping = mapping

    async def run(self, step):
        return self.mapping.get(step.id, {"step_id": step.id})


def test_pipeline_order_sync():
    spec = AgentSpec(name="test", steps=[AgentStep(id="a", kind="step"), AgentStep(id="b", kind="step"), AgentStep(id="c", kind="step")], topology="pipeline")
    mapping = {"a": {"step_id": "a"}, "b": {"step_id": "b"}, "c": {"step_id": "c"}}
    engine = TopologyEngine(spec, runner=SyncRunner(mapping))
    result = asyncio.run(engine.run())
    assert [item["step_id"] for item in result] == ["a", "b", "c"]


def test_fan_out_returns_map():
    spec = AgentSpec(name="test", steps=[AgentStep(id="x", kind="step"), AgentStep(id="y", kind="step")], topology="fan-out")
    mapping = {"x": {"step_id": "x"}, "y": {"step_id": "y"}}
    engine = TopologyEngine(spec, runner=SyncRunner(mapping))
    result = asyncio.run(engine.run())
    assert set(result.keys()) == {"x", "y"}


def test_invalid_topology_raises():
    spec = AgentSpec(name="test", steps=[AgentStep(id="a", kind="step")], topology="unknown")
    engine = TopologyEngine(spec, runner=SyncRunner({"a": {"step_id": "a"}}))
    with pytest.raises(Exception):
        asyncio.run(engine.run())


def test_debate_order_and_results():
    mapping = {"d1": {"rank": 1, "name": "d1"}, "d2": {"rank": 2, "name": "d2"}, "final": {"winner": "d2", "name": "final"}}
    spec = AgentSpec(name="test", steps=[AgentStep(id="d1", kind="chat"), AgentStep(id="d2", kind="chat"), AgentStep(id="final", kind="chat")], topology="debate")
    engine = TopologyEngine(spec, runner=SyncRunner(mapping))
    out = asyncio.run(engine.run())
    assert [item["name"] for item in out] == ["d1", "d2", "final"]


def test_pipeline_dependency_cross_field_raises():
    spec = AgentSpec(name="test", steps=[AgentStep(id="a", kind="step"), AgentStep(id="b", kind="step", depends_on=["missing"])], topology="pipeline")
    engine = TopologyEngine(spec, runner=SyncRunner({"a": {"step_id": "a"}, "b": {"step_id": "b"}}))
    with pytest.raises(Exception):
        asyncio.run(engine.run())


def test_agent_spec_from_yaml_roundtrip():
    yaml_doc = """name: sample
topology: pipeline
budget:
  max_tools: 4
steps:
  - id: step-1
    kind: step
"""
    spec = AgentSpec.from_yaml(yaml_doc)
    assert spec.name == "sample"
    assert spec.topology == "pipeline"
    assert spec.budget == {"max_tools": 4}
    assert spec.steps[0].id == "step-1"


def test_budget_supervisor_rejects_before_run():
    counter = AgentCounter(agent_id="a1")
    budget = Budget(max_tools=1)
    counter.consume_tool(1)
    supervisor = Supervisor(max_attempts=2, timeout_s=1.0, budget=budget, agent_counter=counter)

    async def never(_):
        return {}

    result = asyncio.run(supervisor.run("step-1", never, {}))
    assert result.failed is True
    assert "budget rejection" in result.error


def test_rate_limit_supervisor_rejects_before_run():
    limiter = RateLimiter()
    limiter.check("step-1", 2)
    limiter.check("step-1", 2)
    counter = AgentCounter(agent_id="a1")
    supervisor = Supervisor(max_attempts=2, timeout_s=1.0, rate_limiter=limiter, rate_limit=2, agent_counter=counter)

    async def never(_):
        return {}

    result = asyncio.run(supervisor.run("step-1", never, {}))
    assert result.failed is True
    assert "rate limit rejection" in result.error


def test_topology_rejects_budget_mid_run():
    spec = AgentSpec(name="test", steps=[AgentStep(id="a", kind="step")], topology="pipeline", budget={"max_tools": 0})
    budget = Budget(max_tools=0)
    counter = AgentCounter(agent_id="a1")
    engine = TopologyEngine(spec, runner=SyncRunner({}), budget=budget, counter_for_step=lambda step: counter)
    with pytest.raises(Exception):
        asyncio.run(engine.run())


def test_swarm_command_prints_header(tmp_path):
    from ciel.cli.swarm import swarm_app
    from typer.testing import CliRunner

    spec = tmp_path / "spec.yaml"
    spec.write_text("name: sample\ntopology: pipeline\nsteps:\n  - id: step-1\n    kind: step\n")
    runner = CliRunner()
    result = runner.invoke(swarm_app, ["--spec", str(spec), "--max-tools", "8", "--seconds", "5", "--rate-limit", "0"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "Swarm: sample" in result.output


def test_board_list_prints_tasks(tmp_path):
    from ciel.orchestration.board import BoardTask, KanbanBoard

    board = KanbanBoard()
    board.add_task(BoardTask(id="t1", title="task-1"))
    board.add_task(BoardTask(id="t2", title="task-2"))

    out = board.list_tasks()
    assert {task.title for task in out} == {"task-1", "task-2"}
