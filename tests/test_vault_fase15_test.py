"""Tests offline para F-Vault (Fase 15 — secretos dinámicos y rotación).

No requieren Vault ni red: usan un backend dinámico falso con reloj controlado.
Los tests que requieren la dependencia ``hvac`` real se marcan ``skip``.
"""
from __future__ import annotations

import pytest

from ciel.enterprise.secrets import (
    EnvSecretBackend,
    LeasedSecret,
    RotatingSecretStore,
    SecretError,
    VaultSecretBackend,
)
from ciel.enterprise.secrets import VAULT_AVAILABLE


class FakeDynamicBackend:
    """Backend dinámico controlable para tests (sin red)."""

    def __init__(self, *, ttl=100.0, clock=None):
        self.ttl = ttl
        self._clock = clock
        self.calls = 0
        self.revoked: list[str] = []
        self.fail = False
        self._counter = 0

    def get_lease(self, name):
        self.calls += 1
        if self.fail:
            raise RuntimeError("network down")
        self._counter += 1
        now = self._clock() if self._clock else 0.0
        return LeasedSecret(
            name=name,
            value=f"secret-v{self._counter}",
            lease_id=f"lease-{self._counter}",
            ttl=self.ttl,
            expires_at=now + self.ttl,
            renewable=True,
        )

    def revoke_lease(self, lease_id):
        self.revoked.append(lease_id)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_lease_expiry_triggers_refresh():
    clock = Clock()
    backend = FakeDynamicBackend(ttl=100.0, clock=clock)
    store = RotatingSecretStore(backend, refresh_ratio=0.75, clock=clock)

    assert store.resolve("db") == "secret-v1"
    assert backend.calls == 1
    # dentro de la ventana de refresh (antes de 75 s) no re-fetch
    clock.advance(50)
    assert store.resolve("db") == "secret-v1"
    assert backend.calls == 1
    # pasado el 75% del TTL, refresca
    clock.advance(30)  # t=80 > 75
    assert store.resolve("db") == "secret-v2"
    assert backend.calls == 2


def test_rotation_invalidation():
    clock = Clock()
    backend = FakeDynamicBackend(ttl=100.0, clock=clock)
    store = RotatingSecretStore(backend, clock=clock)
    assert store.resolve("db") == "secret-v1"
    store.invalidate("db")
    assert store.resolve("db") == "secret-v2"
    assert backend.calls == 2


def test_network_failure_keeps_last_known_good():
    clock = Clock()
    backend = FakeDynamicBackend(ttl=100.0, clock=clock)
    store = RotatingSecretStore(backend, clock=clock)
    assert store.resolve("db") == "secret-v1"
    # forzar expiración y fallo de red
    clock.advance(200)
    backend.fail = True
    assert store.resolve("db") == "secret-v1"  # last-known-good


def test_fallback_to_static_backend(monkeypatch):
    backend = FakeDynamicBackend()
    backend.fail = True
    fallback = EnvSecretBackend()
    monkeypatch.setenv("MY_SECRET", "from-env")
    store = RotatingSecretStore(backend, fallback_backend=fallback)
    # dynamic falla y no hay cache → static fallback
    assert store.resolve("MY_SECRET") == "from-env"


def test_kv_static_has_no_lease():
    ls = LeasedSecret(name="x", value="v")
    assert ls.lease_id is None
    assert ls.is_expired() is False


def test_static_secret_not_auto_refreshed():
    clock = Clock()

    class StaticBackend:
        def __init__(self):
            self.calls = 0

        def get_lease(self, name):
            self.calls += 1
            return LeasedSecret(name=name, value="static", lease_id=None)

    backend = StaticBackend()
    store = RotatingSecretStore(backend, clock=clock)
    assert store.resolve("x") == "static"
    clock.advance(10_000)
    assert store.resolve("x") == "static"
    assert backend.calls == 1  # nunca re-fetch para secretos estáticos


def test_revoke_called_on_rotate():
    clock = Clock()
    backend = FakeDynamicBackend(ttl=100.0, clock=clock)
    store = RotatingSecretStore(backend, clock=clock)
    store.resolve("db")  # lease-1
    clock.advance(200)
    store.resolve("db")  # rota → revoca lease-1
    assert "lease-1" in backend.revoked


def test_revoke_explicit():
    backend = FakeDynamicBackend()
    store = RotatingSecretStore(backend)
    store.resolve("db")
    store.revoke("db")
    assert backend.revoked == ["lease-1"]


def test_require_raises_when_missing():
    backend = FakeDynamicBackend()
    backend.fail = True
    store = RotatingSecretStore(backend)
    with pytest.raises(SecretError):
        store.require("nope")


@pytest.mark.skipif(VAULT_AVAILABLE, reason="hvac instalado; este test cubre el caso sin hvac")
def test_vault_dynamic_requires_hvac():
    from ciel.enterprise.secrets import FeatureUnavailable

    backend = VaultSecretBackend(url="http://vault:8200", token="x")
    with pytest.raises(FeatureUnavailable):
        backend.get_lease("db/creds/role")


def test_vault_get_lease_with_fake_client():
    class FakeClient:
        def read(self, path):
            return {
                "data": {"db/creds/role": "dynamic-pass"},
                "lease_id": "database/creds/role/abc",
                "lease_duration": 3600,
                "renewable": True,
            }

    backend = VaultSecretBackend(url="http://vault:8200", token="x", client=FakeClient())
    leased = backend.get_lease("db/creds/role")
    assert leased is not None
    assert leased.value == "dynamic-pass"
    assert leased.lease_id == "database/creds/role/abc"
    assert leased.ttl == 3600.0
    assert leased.renewable is True
