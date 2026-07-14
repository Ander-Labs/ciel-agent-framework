"""Tests para HashChainAuditSink (Fase 7 — audit inmutable hash-chained).

Patrón del proyecto: funciones ``def test_*`` síncronas que envuelven la
corutina con ``asyncio.run`` (sin pytest-asyncio). OFFLINE-SAFE: usa
``tempfile.mkdtemp()`` para ``base_path`` y libera/borra antes de salir.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from typing import List

from ciel.enterprise.audit import HashChainAuditSink
from ciel.observability import AuditEvent


def _make_sink(tmp: str) -> HashChainAuditSink:
    return HashChainAuditSink(base_path=tmp)


def _read_lines(path) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def test_write_preserves_events():
    """write+read preserva los eventos (payload original intacto)."""
    tmp = tempfile.mkdtemp()
    try:
        sink = _make_sink(tmp)
        events = [
            AuditEvent(event="tool.call.start", session_id="s1", tenant_id="t1",
                       agent="a", tool_call_id="c1", data={"x": 1}),
            AuditEvent(event="tool.call.end", session_id="s1", tenant_id="t1",
                       agent="a", tool_call_id="c1", data={"y": 2}),
        ]
        for ev in events:
            asyncio.run(sink.write(ev))

        path = sink._jsonl_path(events[0])
        lines = _read_lines(path)
        assert len(lines) == 2

        rec0 = json.loads(lines[0])
        rec1 = json.loads(lines[1])
        assert rec0["event"] == "tool.call.start"
        assert rec0["data"] == {"x": 1}
        assert rec1["event"] == "tool.call.end"
        assert rec1["data"] == {"y": 2}
        # Campos de la cadena presentes en ambos.
        for rec in (rec0, rec1):
            assert "prev_hash" in rec and "hash" in rec
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_verify_true_on_intact_chain():
    """verify() == True para una cadena íntegra."""
    tmp = tempfile.mkdtemp()
    try:
        sink = _make_sink(tmp)
        for i in range(3):
            ev = AuditEvent(event=f"e{i}", session_id="s1", tenant_id="t1",
                            data={"i": i})
            asyncio.run(sink.write(ev))
        ok = asyncio.run(sink.verify(tenant_id="t1", session_id="s1"))
        assert ok is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_verify_false_after_tamper():
    """verify() == False tras alterar una línea del jsonl (delete/modify)."""
    tmp = tempfile.mkdtemp()
    try:
        sink = _make_sink(tmp)
        for i in range(3):
            ev = AuditEvent(event=f"e{i}", session_id="s1", tenant_id="t1",
                            data={"i": i})
            asyncio.run(sink.write(ev))

        path = sink._jsonl_path(AuditEvent(event="", session_id="s1", tenant_id="t1"))

        # Alteramos el contenido de la segunda línea (modificamos un campo).
        lines = _read_lines(path)
        rec = json.loads(lines[1])
        rec["data"]["i"] = 999  # mutación maliciosa
        lines[1] = json.dumps(rec, ensure_ascii=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        ok = asyncio.run(sink.verify(tenant_id="t1", session_id="s1"))
        assert ok is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_hash_chains_across_events():
    """El last_hash del evento N == hash del payload N."""
    tmp = tempfile.mkdtemp()
    try:
        sink = _make_sink(tmp)
        evs = []
        for i in range(4):
            ev = AuditEvent(event=f"e{i}", session_id="s1", tenant_id="t1",
                            data={"i": i})
            evs.append(ev)
            asyncio.run(sink.write(ev))

        path = sink._jsonl_path(evs[0])
        lines = _read_lines(path)
        recs = [json.loads(ln) for ln in lines]

        # last_hash coincide con el hash del último payload.
        last = sink.last_hash(tenant_id="t1", session_id="s1")
        assert last == recs[-1]["hash"]

        # Toda la cadena es reproducible de forma incremental.
        prev = ""
        for rec in recs:
            assert rec["prev_hash"] == prev
            prev = rec["hash"]
        assert prev == last
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_prev_hash_links_events():
    """prev_hash del evento 2 == hash del evento 1."""
    tmp = tempfile.mkdtemp()
    try:
        sink = _make_sink(tmp)
        ev1 = AuditEvent(event="e1", session_id="s1", tenant_id="t1", data={"n": 1})
        ev2 = AuditEvent(event="e2", session_id="s1", tenant_id="t1", data={"n": 2})
        asyncio.run(sink.write(ev1))
        asyncio.run(sink.write(ev2))

        path = sink._jsonl_path(ev1)
        lines = _read_lines(path)
        rec1 = json.loads(lines[0])
        rec2 = json.loads(lines[1])

        assert rec1["prev_hash"] == ""          # primer evento
        assert rec2["prev_hash"] == rec1["hash"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
