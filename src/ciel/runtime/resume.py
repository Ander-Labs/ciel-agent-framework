"""Resume multi-réplica y lease de ejecución (Fase 14 / F16).

Proporciona primitivas para que ``ciel serve`` soporte N>=2 réplicas detrás
de un balanceador:

* :func:`claim_run_lease` — adquiere un lease idempotente por ``run_id``
  (clave ``lease:<run_id>`` en el ``StateBackend``). Si el lease ya está
  tomado por otro holder y no expiró, devuelve ``False`` (evita doble
  ejecución de un mismo ``run_id`` entre réplicas). El upsert por
  ``(tenant_id, session_id, key)`` del backend ya es atómico/race-safe.
* :func:`release_run_lease` — libera el lease.
* :func:`load_shared_checkpoint` — recupera un checkpoint persistido en el
  backend compartido (visible desde cualquier réplica).

El ``StateBackend`` es la fuente de verdad compartida; los leases viven en el
mismo backend, así que no requieren Redis.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

LEASE_KEY_PREFIX = "lease:"
DEFAULT_LEASE_TTL_SECONDS = 300


def _lease_key(run_id: str) -> str:
    return f"{LEASE_KEY_PREFIX}{run_id}"


def claim_run_lease(
    backend: Any,
    *,
    run_id: str,
    tenant_id: Optional[str] = None,
    session_id: str,
    holder: Optional[str] = None,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> bool:
    """Adquiere (o renueva) el lease de ``run_id``.

    Devuelve ``True`` si esta réplica quedó como holder del lease (puede
    ejecutar/resumir). ``False`` si otro holder ya lo tiene y no expiró.
    """
    holder = holder or f"{session_id}:{uuid.uuid4().hex[:12]}"
    now = time.time()
    existing = backend.get(tenant_id=tenant_id, session_id=session_id, key=_lease_key(run_id))
    if isinstance(existing, dict):
        expires_at = float(existing.get("expires_at", 0))
        # Si el lease no expiró y lo tiene otro holder, rechazar.
        if now < expires_at and existing.get("holder") != holder:
            return False
    backend.set(
        tenant_id=tenant_id,
        session_id=session_id,
        key=_lease_key(run_id),
        value={
            "holder": holder,
            "acquired_at": now,
            "expires_at": now + ttl_seconds,
        },
    )
    return True


def release_run_lease(
    backend: Any,
    *,
    run_id: str,
    tenant_id: Optional[str] = None,
    session_id: str,
) -> None:
    """Libera el lease de ``run_id`` (la réplica terminó limpio)."""
    backend.delete(tenant_id=tenant_id, session_id=session_id, key=_lease_key(run_id))


def load_shared_checkpoint(
    backend: Any,
    *,
    run_id: str,
    tenant_id: Optional[str] = None,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Carga un checkpoint compartido (visible desde cualquier réplica)."""
    payload = backend.get(tenant_id=tenant_id, session_id=session_id, key=f"checkpoint:{run_id}")
    return payload if isinstance(payload, dict) else None


__all__ = [
    "claim_run_lease",
    "release_run_lease",
    "load_shared_checkpoint",
    "DEFAULT_LEASE_TTL_SECONDS",
]
