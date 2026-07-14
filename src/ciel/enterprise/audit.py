"""Hash-chained, append-only audit sink (Fase 7 — Enterprise duro).

Extiende ``JsonlAuditSink`` (de ``ciel.observability``) heredando su
partición por ``tenant/session`` (``_jsonl_path``) y su lock interno, y
añade una cadena de hashes inmutable:

    hash = sha256(prev_hash || canonical_json(event))

Cada registro JSONL se escribe con ``prev_hash`` (hash del registro
anterior, o ``""`` si es el primero) y su propio ``hash``. ``verify``
reproduce la cadena y devuelve ``False`` si cualquier registro fue
alterado. El evento sigue exigiendo ``tenant_id`` (``assert_tenant_event``).

OFFLINE-SAFE: sin red, sin dependencias externas.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ciel.observability import AuditEvent, JsonlAuditSink, assert_tenant_event


def _canonical(event_data: Dict[str, Any]) -> str:
    """JSON determinista (claves ordenadas, sin espacios) para el hash."""
    return json.dumps(event_data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


class HashChainAuditSink(JsonlAuditSink):
    """JSONL audit sink con hash-chain SHA-256 append-only.

    Respeta la ruta de partición de ``JsonlAuditSink._jsonl_path``
    (``base_path / tenant / session / {tenant}-{session}.jsonl``) y reusa
    su lock para escrituras seguras en concurrencia asíncrona.
    """

    def __init__(
        self, base_path: Path | str = "audit", *, tenant_id: Optional[str] = None
    ) -> None:
        super().__init__(base_path)
        self._default_tenant_id = tenant_id

    # ------------------------------------------------------------------
    # helpers interno
    # ------------------------------------------------------------------
    @staticmethod
    def _event_data(event: AuditEvent) -> Dict[str, Any]:
        return {
            "event": event.event,
            "session_id": event.session_id,
            "agent": event.agent,
            "tool_call_id": event.tool_call_id,
            "tenant_id": event.tenant_id,
            "data": event.data or {},
        }

    @staticmethod
    def _record_data(rec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "event": rec.get("event"),
            "session_id": rec.get("session_id"),
            "agent": rec.get("agent"),
            "tool_call_id": rec.get("tool_call_id"),
            "tenant_id": rec.get("tenant_id"),
            "data": rec.get("data") or {},
        }

    @staticmethod
    def _hash(prev_hash: str, event_data: Dict[str, Any]) -> str:
        canonical = _canonical(event_data)
        digest = hashlib.sha256()
        digest.update(prev_hash.encode("utf-8"))
        digest.update(canonical.encode("utf-8"))
        return digest.hexdigest()

    def _last_record_hash(self, path: Path) -> str:
        """Hash del último registro válido del archivo, o '' si está vacío."""
        if not path.exists():
            return ""
        prev = ""
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    # línea corrupta: nos quedamos con el último hash bueno
                    return prev
                prev = rec.get("hash", "")
        return prev

    def _chain_path(self, *, tenant_id: Optional[str], session_id: Optional[str]) -> Path:
        # Reusa la partición del padre construyendo un evento mínimo.
        return self._jsonl_path(
            AuditEvent(event="", session_id=session_id, tenant_id=tenant_id)
        )

    # ------------------------------------------------------------------
    # write (sobreescrito): añade prev_hash/hash al payload
    # ------------------------------------------------------------------
    async def write(self, event: AuditEvent) -> None:
        assert_tenant_event(event)
        path = self._jsonl_path(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            prev_hash = self._last_record_hash(path)
            record_hash = self._hash(prev_hash, self._event_data(event))
            payload = {
                "ts": time.time(),
                "event": event.event,
                "tenant_id": event.tenant_id,
                "session_id": event.session_id,
                "agent": event.agent,
                "tool_call_id": event.tool_call_id,
                "data": event.data or {},
                "prev_hash": prev_hash,
                "hash": record_hash,
            }
            f = await asyncio.to_thread(path.open, mode="a", encoding="utf-8")
            try:
                await asyncio.to_thread(f.write, json.dumps(payload, ensure_ascii=True) + "\n")
            finally:
                await asyncio.to_thread(f.close)

    # ------------------------------------------------------------------
    # verify: reproduce la cadena y detecta alteraciones
    # ------------------------------------------------------------------
    async def verify(
        self, *, tenant_id: Optional[str] = None, session_id: Optional[str] = None
    ) -> bool:
        path = self._chain_path(tenant_id=tenant_id, session_id=session_id)
        async with self._lock:
            if not path.exists():
                # Cadena vacía: no hay evidencia de alteración.
                return True
            with path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
        prev_hash = ""
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                return False
            if rec.get("prev_hash") != prev_hash:
                return False
            expected = self._hash(prev_hash, self._record_data(rec))
            if rec.get("hash") != expected:
                return False
            prev_hash = rec.get("hash", "")
        return True

    # ------------------------------------------------------------------
    # last_hash: hash del último registro de la cadena (o None si vacía)
    # ------------------------------------------------------------------
    def last_hash(self, *, tenant_id: str, session_id: str) -> Optional[str]:
        path = self._chain_path(tenant_id=tenant_id, session_id=session_id)
        if not path.exists():
            return None
        last = self._last_record_hash(path)
        return last or None


__all__ = ["HashChainAuditSink"]
