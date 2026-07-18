"""Sandbox de ejecución de código del agente (Fase 15, offline-safe).

Dos capas:

* **Guardrails / política** (heredado de Fase anterior): :class:`SandboxPolicy`
  y :class:`SandboxContext` deciden qué capacidades (terminal/file) se permiten.
* **Ejecución aislada** (Fase 15): :class:`SandboxExecutor` corre comandos con
  distintos niveles de aislamiento:

  - ``INPROCESS`` (default, cross-platform): ``subprocess`` con timeout. Es el
    fallback universal y reemplaza los antiguos stubs.
  - ``LIGHT`` (Linux): ``subprocess`` + ``setrlimit`` (CPU/mem) — deshabilitado
    en Windows, degrada a ``INPROCESS``.
  - ``DOCKER`` (opt-in): contenedor efímero con red desactivada y límites de
    cpu/mem; degrada a ``INPROCESS`` si Docker no está disponible.
  - ``GVISOR`` (opt-in, Linux): igual que Docker con runtime ``runsc``; degrada
    a Docker y luego a ``INPROCESS``.

El default SIEMPRE es offline-safe: sin Docker/red/deps externas. Todo backend
no disponible degrada con un log y nunca rompe el runtime.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("ciel.sandbox")


# ===========================================================================
# Guardrails / política (API heredada — no romper)
# ===========================================================================


@dataclass
class SandboxPolicy:
    allow_file_read: bool = True
    allow_file_write: bool = False
    allow_terminal: bool = False
    allowed_commands: set[str] = field(default_factory=set)
    denied_commands: set[str] = field(default_factory=set)


class SandboxBlockedError(Exception):
    def __init__(self, capability: str, reason: str = "denied by policy"):
        self.capability = capability
        self.reason = reason
        super().__init__(f"{capability} {reason}")


# ===========================================================================
# Ejecución aislada (Fase 15)
# ===========================================================================


class SandboxBackend(str, Enum):
    INPROCESS = "inprocess"
    LIGHT = "light"
    DOCKER = "docker"
    GVISOR = "gvisor"


@dataclass
class SandboxLimits:
    """Límites de recursos aplicados al comando (best-effort por backend)."""

    timeout_s: float = 30.0
    cpu_seconds: Optional[int] = None
    memory_mb: Optional[int] = None
    pids: Optional[int] = 128
    network: bool = False  # False => sin red (aislamiento por defecto)


@dataclass
class ExecResult:
    """Resultado de una ejecución en el sandbox."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    backend: str = SandboxBackend.INPROCESS.value
    duration_ms: int = 0
    limits_applied: bool = False


def _docker_available(image: Optional[str] = None) -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        res = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=8,
        )
        return res.returncode == 0
    except Exception:
        return False


def _gvisor_available() -> bool:
    if sys.platform.startswith("win"):
        return False
    if shutil.which("runsc") is None:
        return False
    return _docker_available()


class SandboxExecutor:
    """Ejecutor de comandos con aislamiento seleccionable.

    Se construye con un ``backend`` deseado; si no está disponible, degrada
    (con log) al siguiente backend más seguro disponible hasta ``INPROCESS``,
    que siempre existe.
    """

    def __init__(
        self,
        *,
        backend: SandboxBackend = SandboxBackend.INPROCESS,
        limits: Optional[SandboxLimits] = None,
        docker_image: str = "python:3.11-slim",
        workdir: Optional[str] = None,
    ) -> None:
        self.requested_backend = SandboxBackend(backend)
        self.limits = limits or SandboxLimits()
        self.docker_image = docker_image
        self.workdir = workdir
        self.backend = self._resolve_backend(self.requested_backend)

    def _resolve_backend(self, backend: SandboxBackend) -> SandboxBackend:
        if backend == SandboxBackend.GVISOR:
            if _gvisor_available():
                return SandboxBackend.GVISOR
            logger.warning("gVisor no disponible; degradando a docker/inprocess")
            backend = SandboxBackend.DOCKER
        if backend == SandboxBackend.DOCKER:
            if _docker_available(self.docker_image):
                return SandboxBackend.DOCKER
            logger.warning("Docker no disponible; degradando a inprocess")
            return SandboxBackend.INPROCESS
        if backend == SandboxBackend.LIGHT:
            if sys.platform.startswith("win"):
                logger.warning("backend 'light' no soportado en Windows; degradando a inprocess")
                return SandboxBackend.INPROCESS
            return SandboxBackend.LIGHT
        return SandboxBackend.INPROCESS

    # -- ejecución ----------------------------------------------------------
    def run(self, command, *, stdin: Optional[str] = None) -> ExecResult:
        """Ejecuta ``command`` (lista o str) y devuelve un :class:`ExecResult`."""
        start = time.monotonic()
        if self.backend == SandboxBackend.DOCKER:
            result = self._run_docker(command, stdin, runtime=None)
        elif self.backend == SandboxBackend.GVISOR:
            result = self._run_docker(command, stdin, runtime="runsc")
        elif self.backend == SandboxBackend.LIGHT:
            result = self._run_light(command, stdin)
        else:
            result = self._run_inprocess(command, stdin)
        result.duration_ms = int((time.monotonic() - start) * 1000)
        result.backend = self.backend.value
        return result

    def _as_list(self, command):
        if isinstance(command, (list, tuple)):
            return list(command)
        # str: en Windows sin shell, usar split simple; el caller controla input.
        import shlex

        return shlex.split(command, posix=not sys.platform.startswith("win"))

    def _run_inprocess(self, command, stdin) -> ExecResult:
        args = self._as_list(command)
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.limits.timeout_s,
                input=stdin,
                cwd=self.workdir,
            )
            return ExecResult(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=proc.returncode,
                limits_applied=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ExecResult(
                stdout=(exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                stderr="timeout",
                exit_code=124,
                timed_out=True,
                limits_applied=False,
            )
        except FileNotFoundError as exc:
            return ExecResult(stderr=str(exc), exit_code=127)

    def _run_light(self, command, stdin) -> ExecResult:
        import resource  # Linux-only

        args = self._as_list(command)
        limits = self.limits

        def _preexec():
            if limits.cpu_seconds:
                resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
            if limits.memory_mb:
                nbytes = limits.memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))

        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=limits.timeout_s,
                input=stdin,
                cwd=self.workdir,
                preexec_fn=_preexec,
            )
            return ExecResult(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=proc.returncode,
                limits_applied=True,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(stderr="timeout", exit_code=124, timed_out=True, limits_applied=True)
        except FileNotFoundError as exc:
            return ExecResult(stderr=str(exc), exit_code=127, limits_applied=True)

    def _run_docker(self, command, stdin, *, runtime: Optional[str]) -> ExecResult:
        args = self._as_list(command)
        limits = self.limits
        docker_cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "none" if not limits.network else "bridge",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
        ]
        if limits.memory_mb:
            docker_cmd += ["--memory", f"{limits.memory_mb}m"]
        if limits.pids:
            docker_cmd += ["--pids-limit", str(limits.pids)]
        if runtime:
            docker_cmd += ["--runtime", runtime]
        docker_cmd += [self.docker_image, *args]
        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=limits.timeout_s,
                input=stdin,
            )
            return ExecResult(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=proc.returncode,
                limits_applied=True,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(stderr="timeout", exit_code=124, timed_out=True, limits_applied=True)
        except FileNotFoundError as exc:
            return ExecResult(stderr=str(exc), exit_code=127, limits_applied=True)


# ===========================================================================
# GuardrailMiddleware (Fase 15): rate-limit + redacción sobre tool dispatch
# ===========================================================================


class GuardrailMiddleware:
    """Envoltura de guardrails para la ejecución de herramientas.

    Reutiliza :class:`TenantRateLimiter` (rate-limit por tenant) y
    :func:`redact_string` (redacción de secretos en la salida). También trunca
    salidas excesivamente largas. Todos los componentes son opcionales.
    """

    def __init__(
        self,
        *,
        rate_limiter=None,
        redact_output: bool = True,
        max_output_chars: int = 100_000,
        secrets=None,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.redact_output = redact_output
        self.max_output_chars = max_output_chars
        self.secrets = list(secrets or [])

    def before(self, *, tenant_id: Optional[str] = None, user: Optional[str] = None) -> None:
        """Aplica rate-limit antes de ejecutar (lanza ``RateLimitError``)."""
        if self.rate_limiter is not None:
            self.rate_limiter.consume(tenant_id=tenant_id, user=user)

    def after_output(self, output: Any) -> Any:
        """Redacta y trunca la salida de una herramienta."""
        if not isinstance(output, str):
            return output
        text = output
        if self.redact_output:
            from ciel.security.redaction import redact_string

            text = redact_string(text, self.secrets)
        if self.max_output_chars and len(text) > self.max_output_chars:
            text = text[: self.max_output_chars] + "\n[...truncated...]"
        return text


# ===========================================================================
# SandboxContext (API heredada) — ahora respaldada por SandboxExecutor real
# ===========================================================================


@dataclass
class SandboxContext:
    policy: Optional[SandboxPolicy] = None
    executor: Optional[SandboxExecutor] = None

    def __post_init__(self) -> None:
        if self.policy is None:
            self.policy = SandboxPolicy()
        if self.executor is None:
            self.executor = SandboxExecutor()

    def evaluate(self, capability: str, command: Optional[str] = None) -> bool:
        if capability == "terminal":
            if not self.policy.allow_terminal:
                return False
            if command:
                if self.policy.denied_commands and command in self.policy.denied_commands:
                    return False
                if self.policy.allowed_commands and command not in self.policy.allowed_commands:
                    return False
            return True
        if capability == "file_write":
            return self.policy.allow_file_write
        if capability == "file_read":
            return self.policy.allow_file_read
        return False

    def execute(self, command: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        arguments = arguments or {}
        if not self.evaluate("terminal", command=command):
            raise SandboxBlockedError("terminal", f"command '{command}' denied")
        # Ejecución REAL vía el executor (reemplaza el antiguo stub).
        full = command
        args = arguments.get("args")
        if args:
            full = command + " " + (args if isinstance(args, str) else " ".join(map(str, args)))
        result = self.executor.run(full)
        if result.exit_code != 0 and result.stderr:
            return result.stderr
        return result.stdout

    def write_file(self, path: str, content: str) -> str:
        if not self.evaluate("file_write"):
            raise SandboxBlockedError("file_write", f"write to '{path}' denied")
        from pathlib import Path

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} bytes to {path}"

    def read_file(self, path: str) -> str:
        if not self.evaluate("file_read"):
            raise SandboxBlockedError("file_read", f"read from '{path}' denied")
        from pathlib import Path

        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(path)
        return p.read_text(encoding="utf-8")


__all__ = [
    "SandboxPolicy",
    "SandboxBlockedError",
    "SandboxContext",
    "SandboxBackend",
    "SandboxLimits",
    "ExecResult",
    "SandboxExecutor",
    "GuardrailMiddleware",
]
