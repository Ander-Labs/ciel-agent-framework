"""Tests for ``ciel.enterprise.secrets`` (Fase 7).

OFFLINE-SAFE: no network, no optional deps required.  The Vault backend is
exercised either with a fake client (no hvac needed) or, when hvac is missing,
we assert that ``VAULT_AVAILABLE`` is ``False`` and ``get`` raises
``FeatureUnavailable``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from ciel.enterprise.secrets import (
    EnvSecretBackend,
    FeatureUnavailable,
    KubernetesSecretBackend,
    SecretError,
    SecretStore,
    VaultSecretBackend,
    VAULT_AVAILABLE,
)


# ---------------------------------------------------------------------------
# EnvSecretBackend
# ---------------------------------------------------------------------------
def test_env_backend_get_and_none(monkeypatch) -> None:
    monkeypatch.setenv("CIEL_TEST_TOKEN", "s3cr3t")
    backend = EnvSecretBackend()
    assert backend.get("CIEL_TEST_TOKEN") == "s3cr3t"
    # A never-set variable resolves to None.
    assert backend.get("CIEL_TEST_DOES_NOT_EXIST") is None


# ---------------------------------------------------------------------------
# KubernetesSecretBackend
# ---------------------------------------------------------------------------
def test_k8s_backend_reads_mounted_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mount = Path(tmp)
        # K8s lower-cases and turns underscores into dashes.
        (mount / "my-db-password").write_text("k8s-secret-value", encoding="utf-8")
        backend = KubernetesSecretBackend(mount)
        assert backend.get("MY_DB_PASSWORD") == "k8s-secret-value"
        # Missing secret -> None.
        assert backend.get("MISSING_SECRET") is None


# ---------------------------------------------------------------------------
# SecretStore priority + require
# ---------------------------------------------------------------------------
def test_secretstore_prefers_first_backend(monkeypatch) -> None:
    monkeypatch.setenv("CIEL_PRIORITY", "from-env")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "ciel-priority").write_text("from-k8s", encoding="utf-8")
        env = EnvSecretBackend()
        k8s = KubernetesSecretBackend(tmp)
        # env listed first -> wins over k8s.
        store = SecretStore([env, k8s])
        assert store.get("CIEL_PRIORITY") == "from-env"
        # Swap order -> k8s wins.
        store2 = SecretStore([k8s, env])
        assert store2.get("CIEL_PRIORITY") == "from-k8s"


def test_secretstore_require_raises_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("CIEL_ABSENT", raising=False)
    store = SecretStore([EnvSecretBackend()])
    with pytest.raises(SecretError):
        store.require("CIEL_ABSENT")
    # require returns the value when present.
    monkeypatch.setenv("CIEL_PRESENT", "ok")
    assert store.require("CIEL_PRESENT") == "ok"


# ---------------------------------------------------------------------------
# Vault feature detection
# ---------------------------------------------------------------------------
def test_vault_feature_detection() -> None:
    if not VAULT_AVAILABLE:
        # hvac missing: backend must report unavailable and refuse to read.
        assert VaultSecretBackend.VAULT_AVAILABLE is False
        backend = VaultSecretBackend(url="http://localhost:8200", token="t")
        with pytest.raises(FeatureUnavailable):
            backend.get("anything")
    else:
        # hvac present: exercise with an in-memory fake client (no network).
        class _FakeKV:
            def __init__(self):
                self._store = {"my-token": {"my-token": "vault-value"}}

            def read_secret_version(self, path, raise_on_deleted_version=True):
                key = path.rsplit("/", 1)[-1]
                if key not in self._store:
                    return {"data": {"data": {}}}
                return {"data": {"data": self._store[key]}}

        class _FakeSecrets:
            def __init__(self):
                self.kv = type("_KV", (), {"v2": _FakeKV()})()

        class _FakeClient:
            def __init__(self, *a, **k):
                self.secrets = _FakeSecrets()

        backend = VaultSecretBackend(
            url="http://localhost:8200",
            token="t",
            path_prefix="/secret/data",
            client=_FakeClient(),
        )
        assert backend.get("my-token") == "vault-value"
        assert backend.get("absent") is None
