from __future__ import annotations

import gzip
import os
import sqlite3
import zlib
from pathlib import Path

import pytest

from ciel.runtime.compression import (
    CompressionRecord,
    compress_factory,
    gzip_compress,
    gzip_decompress,
    zlib_compress,
    zlib_decompress,
)
from ciel.runtime.memory import MemoryStore
from ciel.runtime.skills import SkillRegistry, load_skill, _parse_frontmatter
from ciel.runtime.tools import Tool, ToolRegistry, ToolsetSchema, ToolSpec


def test_tool_registry_register_and_lookup() -> None:
    registry = ToolRegistry()
    schema = ToolsetSchema(
        name="math",
        description="Math tools",
        tools=(
            ToolSpec(name="add", description="Sum", parameters={"type": "object"}),
            ToolSpec(name="sub", description="Subtract", parameters={"type": "object"}),
        ),
    )
    registry.register_toolset(schema)
    assert registry.get_toolset("math").name == "math"
    assert registry.tool_names("math") == ("add", "sub")
    schema_json = registry.export_schema("math")
    assert schema_json["version"] == "1.0.0"
    assert schema_json["tools"][0]["name"] == "add"
    with pytest.raises(KeyError):
        registry.export_schema("unknown")


def test_tool_registry_register_tool() -> None:
    registry = ToolRegistry()
    registry.register_tool("echo", Tool(spec=ToolSpec(name="echo", description="Echo", parameters={})))
    assert registry.get_tool("echo", "echo").spec.description == "Echo"


def test_toolset_schema_json_omits_empty_metadata() -> None:
    schema = ToolsetSchema(
        name="db",
        description="DB tools",
        tools=(ToolSpec(name="query", description="Query", parameters={}, metadata={}),),
    )
    assert "metadata" not in schema.to_json()["tools"][0]


def test_skills_frontmatter_parsing() -> None:
    assert _parse_frontmatter("---\nname: foo\ndescription: bar\n---\nbody") == {"name": "foo", "description": "bar"}
    assert _parse_frontmatter("no frontmatter") == {}


def test_skill_registry_discovers_markdown(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    sample = root / "Skill.md"
    sample.write_text("---\nname: search\ndescription: Search docs\n---\nBody", encoding="utf-8")
    registry = SkillRegistry(roots=[str(root)])
    skills = registry.discover()
    assert len(skills) == 1
    assert registry.get("search").sha256 is not None


def test_memory_store_set_and_get(tmp_path: Path) -> None:
    db = str(tmp_path / "memory.db")
    store = MemoryStore(db)
    store.set(tenant_id="t1", session_id="s1", key="k1", value={"a": 1})
    assert store.get(tenant_id="t1", session_id="s1", key="k1") == {"a": 1}
    store.close()


def test_memory_store_delete(tmp_path: Path) -> None:
    db = str(tmp_path / "memory.db")
    store = MemoryStore(db)
    store.set(tenant_id="t1", session_id="s1", key="k1", value=1)
    store.delete(tenant_id="t1", session_id="s1", key="k1")
    assert store.get(tenant_id="t1", session_id="s1", key="k1") is None
    store.close()


def test_memory_store_search_falls_back_without_fts5(tmp_path: Path) -> None:
    db = str(tmp_path / "memory.db")
    store = MemoryStore(db)
    assert store.search("k1") == []
    store.close()


def test_memory_store_search_with_fts5(tmp_path: Path) -> None:
    db = str(tmp_path / "memory.db")
    conn = sqlite3.connect(db)
    try:
        available = conn.execute("SELECT * FROM pragma_compile_options WHERE compile_options LIKE '%FTS5%'").fetchone()
    finally:
        conn.close()
    if not available:
        pytest.skip("sqlite fts5 not available")
    store = MemoryStore(db)
    store.set(tenant_id="t1", session_id="s1", key="alpha", value="alpha value")
    store.set(tenant_id="t1", session_id="s1", key="beta", value="beta value")
    results = store.search("alpha")
    assert any(item["key"] == "alpha" for item in results)
    store.close()


def test_memory_tool_execution_log(tmp_path: Path) -> None:
    db = str(tmp_path / "memory.db")
    store = MemoryStore(db)
    store.record_tool_execution(
        tenant_id="t1",
        session_id="s1",
        toolset="default",
        tool_name="echo",
        arguments={"msg": "hi"},
        started_at="2025-01-01T00:00:00Z",
        finished_at="2025-01-01T00:00:01Z",
        duration_ms=1000,
        output="hi",
    )
    assert True
    store.close()


def test_compression_roundtrip_gzip() -> None:
    original = b"hello world"
    record = gzip_compress(original)
    assert record.algorithm == "gzip"
    assert gzip_decompress(record) == original


def test_compression_roundtrip_zlib() -> None:
    original = b"hello world"
    record = zlib_compress(original)
    assert record.algorithm == "zlib"
    assert zlib_decompress(record) == original


def test_compress_factory_invalid_algorithm() -> None:
    with pytest.raises(ValueError):
        compress_factory(b"x", algorithm="unknown")


def test_compress_factory_requires_data() -> None:
    with pytest.raises(TypeError):
        compress_factory("missing")  # type: ignore[arg-type]


def test_checkpoint_store_save_and_load(tmp_path: Path) -> None:
    from ciel.runtime import ChatRequest, ChatMessage, ToolLoopResult
    from ciel.runtime.checkpoints import Checkpoint, CheckpointStore

    db = str(tmp_path / "memory.db")
    store = CheckpointStore(MemoryStore(db))
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        extra={"session_id": "s1"},
    )
    checkpoint = Checkpoint(
        checkpoint_id="cp-1",
        turn_index=1,
        request=request,
        loop_results=(),
        metadata={"agent": "a1"},
    )
    store.save(checkpoint, tenant_id="t1", session_id="s1")
    loaded = store.load(tenant_id="t1", session_id="s1", checkpoint_id="cp-1")
    assert loaded is not None
    assert loaded.checkpoint_id == "cp-1"
    assert loaded.request.extra.get("session_id") == "s1"
    assert loaded.metadata.get("agent") == "a1"


def test_checkpoint_store_load_missing(tmp_path: Path) -> None:
    from ciel.runtime.checkpoints import CheckpointStore

    db = str(tmp_path / "memory.db")
    store = CheckpointStore(MemoryStore(db))
    assert store.load(tenant_id="t1", session_id="s1", checkpoint_id="missing") is None
