"""Tests offline para F-Sandbox (Fase 15 — guardrails + sandbox de ejecución).

No requieren Docker/gVisor. Los backends fuertes se prueban solo si están
disponibles (skip en caso contrario); el resto valida degradación graceful,
guardrails y ejecución in-process real.
"""
from __future__ import annotations

import shutil
import sys

import pytest

from ciel.sandbox import (
    ExecResult,
    GuardrailMiddleware,
    SandboxBackend,
    SandboxExecutor,
    SandboxLimits,
)
from ciel.enterprise.ratelimit import RateLimitError, TenantRateLimiter


def _has_docker() -> bool:
    if shutil.which("docker") is None:
        return False
    import subprocess

    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=8).returncode == 0
    except Exception:
        return False


# --------------------------------------------------------------------------
# Ejecución in-process real
# --------------------------------------------------------------------------

def test_inprocess_executes_real_command():
    ex = SandboxExecutor(backend=SandboxBackend.INPROCESS)
    res = ex.run([sys.executable, "-c", "print('hola-sandbox')"])
    assert res.exit_code == 0
    assert "hola-sandbox" in res.stdout
    assert res.backend == "inprocess"


def test_inprocess_timeout_kills_long_running():
    ex = SandboxExecutor(
        backend=SandboxBackend.INPROCESS,
        limits=SandboxLimits(timeout_s=1.0),
    )
    res = ex.run([sys.executable, "-c", "import time; time.sleep(10)"])
    assert res.timed_out is True
    assert res.exit_code == 124


def test_inprocess_nonzero_exit():
    ex = SandboxExecutor()
    res = ex.run([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert res.exit_code == 3


# --------------------------------------------------------------------------
# Degradación graceful de backends
# --------------------------------------------------------------------------

def test_docker_backend_falls_back_to_inprocess_when_unavailable(monkeypatch):
    monkeypatch.setattr("ciel.sandbox._docker_available", lambda image=None: False)
    ex = SandboxExecutor(backend=SandboxBackend.DOCKER)
    assert ex.backend == SandboxBackend.INPROCESS


def test_gvisor_backend_falls_back(monkeypatch):
    monkeypatch.setattr("ciel.sandbox._gvisor_available", lambda: False)
    monkeypatch.setattr("ciel.sandbox._docker_available", lambda image=None: False)
    ex = SandboxExecutor(backend=SandboxBackend.GVISOR)
    assert ex.backend == SandboxBackend.INPROCESS


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="solo Windows")
def test_light_backend_disabled_on_windows():
    ex = SandboxExecutor(backend=SandboxBackend.LIGHT)
    assert ex.backend == SandboxBackend.INPROCESS


# --------------------------------------------------------------------------
# GuardrailMiddleware
# --------------------------------------------------------------------------

def test_guardrail_redacts_output_secrets():
    gm = GuardrailMiddleware(redact_output=True, secrets=["supersecret"])
    out = gm.after_output("token=supersecret and api_key=ABCDEF1234567890")
    assert "supersecret" not in out
    assert "ABCDEF1234567890" not in out


def test_guardrail_truncates_long_output():
    gm = GuardrailMiddleware(max_output_chars=10)
    out = gm.after_output("x" * 100)
    assert out.startswith("xxxxxxxxxx")
    assert "truncated" in out


def test_guardrail_rate_limits_tenant():
    rl = TenantRateLimiter(quotas={("acme", "*"): 2}, window_s=60)
    gm = GuardrailMiddleware(rate_limiter=rl)
    gm.before(tenant_id="acme", user="u1")
    gm.before(tenant_id="acme", user="u1")
    with pytest.raises(RateLimitError):
        gm.before(tenant_id="acme", user="u1")


def test_guardrail_passes_non_string_output():
    gm = GuardrailMiddleware()
    assert gm.after_output({"a": 1}) == {"a": 1}


# --------------------------------------------------------------------------
# Backends fuertes (skip si no disponibles)
# --------------------------------------------------------------------------

@pytest.mark.skipif(not _has_docker(), reason="Docker no disponible")
def test_docker_executor_runs_and_isolates_network():
    ex = SandboxExecutor(
        backend=SandboxBackend.DOCKER,
        limits=SandboxLimits(timeout_s=60, network=False, memory_mb=128),
    )
    res = ex.run(["python", "-c", "print('in-docker')"])
    assert res.exit_code == 0
    assert "in-docker" in res.stdout
    assert res.backend == "docker"


@pytest.mark.skipif(sys.platform.startswith("win") or shutil.which("runsc") is None, reason="runsc no disponible")
def test_gvisor_backend_runs():
    ex = SandboxExecutor(backend=SandboxBackend.GVISOR, limits=SandboxLimits(timeout_s=60))
    res = ex.run(["python", "-c", "print('in-gvisor')"])
    assert res.exit_code == 0
