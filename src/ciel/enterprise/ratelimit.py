"""Rate-limit + cuotas transversales por tenant/usuario.

Ventana deslizante en memoria (timestamps). OFFLINE-SAFE. La clave de cuota
efectiva se resuelve por especificidad:

    (tenant, user) > (tenant, "*") > ("*", "*")

Si ninguna coincide, la entidad es ilimitada.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Optional, Tuple

# Centinela para "sin cuota" (ilimitado).
_UNLIMITED = 1 << 62

# Clave interna cuando no hay cuota que aplique.
_NO_QUOTA: Tuple[str, ...] = ("__no_quota__",)


class RateLimitError(Exception):
    """Se lanza cuando una petición excede la cuota del tenant/usuario."""


Key = Tuple[Optional[str], Optional[str]]


class TenantRateLimiter:
    """Rate-limiter transversal por tenant/usuario con ventana deslizante.

    Las cuotas se definen como ``dict[(tenant_id o "*", user o "*")]: max_requests``.
    La cuota efectiva para una petición se resuelve por especificidad
    (``(tenant, user)`` > ``(tenant, "*")`` > ``("*", "*")``). Si ninguna
    coincide, la entidad es ilimitada.
    """

    def __init__(
        self,
        *,
        quotas: Optional[dict] = None,
        window_s: int = 60,
    ) -> None:
        # ``quotas``: dict[(tenant_id o "*", user o "*")] -> max_requests en la ventana
        self.quotas: dict = dict(quotas or {})
        self.window_s = window_s
        # bucket por clave de cuota efectiva -> timestamps (ventana deslizante)
        self._buckets: dict[Key, Deque[float]] = {}

    # -- resolución de cuota ------------------------------------------------
    def _effective_key(self, tenant_id: Optional[str], user: Optional[str]) -> Key:
        if (tenant_id, user) in self.quotas:
            return (tenant_id, user)
        if (tenant_id, "*") in self.quotas:
            return (tenant_id, "*")
        if ("*", "*") in self.quotas:
            return ("*", "*")
        return _NO_QUOTA

    def _quota_of(self, key: Key) -> Optional[int]:
        if key == _NO_QUOTA:
            return None
        return self.quotas.get(key)

    def _prune(self, key: Key, now: float) -> Deque[float]:
        dq = self._buckets.get(key)
        if dq is None:
            dq = deque()
            self._buckets[key] = dq
            return dq
        # descarta timestamps fuera de la ventana deslizante
        while dq and (now - dq[0]) > self.window_s:
            dq.popleft()
        return dq

    # -- API ----------------------------------------------------------------
    def check(self, *, tenant_id: Optional[str] = None, user: Optional[str] = None) -> bool:
        """False si la petición excedería la cuota (ventana deslizante)."""
        key = self._effective_key(tenant_id, user)
        quota = self._quota_of(key)
        if quota is None:
            return True
        now = time.monotonic()
        dq = self._prune(key, now)
        return len(dq) < quota

    def consume(
        self, *, tenant_id: Optional[str] = None, user: Optional[str] = None
    ) -> None:
        """Registra una petición; lanza ``RateLimitError`` si excede la cuota."""
        key = self._effective_key(tenant_id, user)
        quota = self._quota_of(key)
        if quota is None:
            return
        now = time.monotonic()
        dq = self._prune(key, now)
        if len(dq) >= quota:
            raise RateLimitError(
                f"cuota excedida para tenant={tenant_id!r} user={user!r} "
                f"(máx {quota} en {self.window_s}s)"
            )
        dq.append(now)

    def reset(
        self, *, tenant_id: Optional[str] = None, user: Optional[str] = None
    ) -> None:
        """Vacía el contador de la clave efectiva de (tenant_id, user)."""
        key = self._effective_key(tenant_id, user)
        if key in self._buckets:
            del self._buckets[key]

    def remaining(
        self, *, tenant_id: Optional[str] = None, user: Optional[str] = None
    ) -> int:
        """Peticiones restantes en la ventana para (tenant_id, user)."""
        key = self._effective_key(tenant_id, user)
        quota = self._quota_of(key)
        if quota is None:
            return _UNLIMITED
        now = time.monotonic()
        dq = self._prune(key, now)
        return max(0, quota - len(dq))
