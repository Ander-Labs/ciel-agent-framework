from __future__ import annotations

import asyncio

import pytest

from ciel.orchestration import AgentStep, AgentSpec
from ciel.orchestration.topology import TopologyError, TopologyEngine


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
    with pytest.raises(TopologyError):
        asyncio.run(engine.run())


def test_pipeline_dependency_check_raises():
    spec = AgentSpec(name="test", steps=[AgentStep(id="a", kind="step"), AgentStep(id="b", kind="step", depends_on=["missing"])], topology="pipeline")
    engine = TopologyEngine(spec, runner=SyncRunner({"a": {"step_id": "a"}, "b": {"step_id": "b"}}))
    with pytest.raises(TopologyError):
        asyncio.run(engine.run())


def test_fan_out_with_deps_returns_map():
    spec = AgentSpec(name="test", steps=[AgentStep(id="r", kind="step"), AgentStep(id="f", kind="step", depends_on=["r"])], topology="fan-out")
    mapping = {"r": {"step_id": "r"}, "f": {"step_id": "f"}}
    engine = TopologyEngine(spec, runner=SyncRunner(mapping))
    result = asyncio.run(engine.run())
    assert set(result.keys()) == {"r", "f"}


def test_debate_order_and_results():
    mapping = {"d1": {"rank": 1, "name": "d1"}, "d2": {"rank": 2, "name": "d2"}, "final": {"winner": "d2", "name": "final"}}
    spec = AgentSpec(name="test", steps=[AgentStep(id="d1", kind="chat"), AgentStep(id="d2", kind="chat"), AgentStep(id="final", kind="chat")], topology="debate")
    engine = TopologyEngine(spec, runner=SyncRunner(mapping))
    out = asyncio.run(engine.run())
    assert [item["name"] for item in out] == ["d1", "d2", "final"]
