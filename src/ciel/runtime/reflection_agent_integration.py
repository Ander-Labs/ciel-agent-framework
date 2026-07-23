"""Integración aditiva de self-reflection + learning-from-failure (Fase 19).

IGUAL que ``memory_agent_integration``: NO reescribe ``api.py``. Se invoca
``install_agent_reflection_support(Agent)`` al final de ``ciel/api.py`` y
engancha:

* ``Agent(reflection=...)`` / ``Agent(reflection_config=...)`` — habilita la
  reflexión post-run (opcional, offline-safe).
* Tras cada ``arun``/``run``, si el run tuvo fallos de tool, genera una
  *lección* determinista (sin red) y la persiste como memoria episódica
  ``role="lesson"`` (reutiliza el ``EpisodicStore`` de F17 → multitenant).
* Exponer ``AgentResponse.reflection`` (property aditiva) con el resumen.

Degrada graceful: si no se instala, ``getattr(self, "_reflection", None)`` es
None y el run no cambia.
"""

from __future__ import annotations

import functools
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from ciel.runtime.memory_episodic import EpisodicStore


@dataclass
class ReflectionConfig:
    """Configuración de reflexión del agente (degrada a 'sin reflexión')."""

    enabled: bool = True
    persist_lessons: bool = True
    max_lessons: int = 5

    @classmethod
    def disabled(cls) -> "ReflectionConfig":
        return cls(enabled=False)


class AgentReflection:
    """State holder de reflexión para un ``Agent`` (aditivo, no invasivo).

    Genera lecciones deterministas a partir de fallos de tool (sin red) y las
    persiste vía el ``EpisodicStore`` (memoria episódica F17, aislada por
    tenant). Si no hay store, opera en modo no-persistente (solo resumen).
    """

    def __init__(
        self,
        store: Any,
        config: Optional[ReflectionConfig] = None,
    ) -> None:
        # store: ciel.runtime.memory_episodic.EpisodicStore | None
        self.store = store
        self.config = config or ReflectionConfig()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    # ------------------------------------------------------------------ #
    def reflect(
        self,
        response: Any,
        *,
        tenant_id: Optional[str],
        session_id: str,
    ) -> Optional[dict]:
        """Reflexiona sobre un ``AgentResponse`` y (opcionalmente) persiste lección.

        Devuelve un dict resumen:
        ``{"had_failure", "failed_tools", "lessons_count", "lesson"}``
        o ``None`` si la reflexión está deshabilitada.
        """
        if not self.enabled:
            return None
        tool_results = response.tool_results
        failed = [r for r in tool_results if getattr(r, "error", None)]
        had_failure = bool(failed)
        lesson = None
        if had_failure:
            lesson = self._build_lesson(failed, response=response)
            if self.config.persist_lessons and self.store is not None:
                try:
                    self.store.append(
                        tenant_id=tenant_id,
                        session_id=session_id,
                        role="lesson",
                        content=lesson,
                        metadata={"kind": "reflection", "had_failure": True},
                    )
                except Exception:  # pragma: no cover - reflexión nunca rompe el run
                    pass
        return {
            "had_failure": had_failure,
            "failed_tools": [r.name for r in failed],
            "lessons_count": len(failed) if lesson else 0,
            "lesson": lesson,
        }

    def _build_lesson(self, failed: List[Any], *, response: Any) -> dict:
        """Lección determinista a partir de los fallos (sin red)."""
        details = []
        for r in failed:
            details.append(
                {
                    "tool": r.name,
                    "error": r.error,
                }
            )
        return {
            "type": "learning_from_failure",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": (
                f"El agente falló en {len(failed)} tool(s): "
                + ", ".join(d["tool"] for d in details)
                + ". En próximos runs, considera validar argumentos o usar un tool alternativo."
            ),
            "failures": details,
            "final_text": (response.text or "")[:500],
        }

    def lessons(self, *, tenant_id: Optional[str], session_id: str, limit: int = 5) -> List[dict]:
        """Recupera las lecciones persistidas (memoria episódica role='lesson')."""
        if self.store is None:
            return []
        recent = self.store.get_recent(
            tenant_id=tenant_id, session_id=session_id, limit=max(limit, self.config.max_lessons)
        )
        out: List[dict] = []
        for m in recent:
            if getattr(m, "role", None) == "lesson":
                content = m.content
                out.append(content if isinstance(content, dict) else {"content": content})
        return out


def install_agent_reflection_support(agent_cls: Any) -> Any:
    """Engancha ``reflection=`` / ``reflection_config=`` en ``Agent`` sin reescribir api.py.

    Idempotente: si ya se instaló, no re-envuelve (evita doble wrapper en tests).
    """
    if getattr(agent_cls, "_reflection_installed", False):
        return agent_cls
    original_init = agent_cls.__init__
    original_arun = agent_cls.arun

    @functools.wraps(original_init)
    def _patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        reflection_arg = kwargs.pop("reflection", None)
        reflection_config = kwargs.pop("reflection_config", None)
        original_init(self, *args, **kwargs)

        config = reflection_config or ReflectionConfig()
        # Resolver el store de lecciones: reutiliza el EpisodicStore de memoria
        # si existe; si no, crea uno temporal offline (solo si se habilitó).
        store = None
        mem = getattr(self, "_memory", None)
        if mem is not None and getattr(mem, "store", None) is not None:
            store = mem.store
        elif reflection_arg is True or reflection_config is not None:
            from ciel.runtime.state_backend import SqliteStateBackend

            tmp = tempfile.mkdtemp(prefix="ciel-reflect-")
            be = SqliteStateBackend(str(Path(tmp) / "reflect.sqlite"))
            store = EpisodicStore(be)
        elif isinstance(reflection_arg, EpisodicStore):  # type: ignore[name-defined]
            store = reflection_arg
        if reflection_arg is False or (reflection_arg is None and reflection_config is None):
            config = config.disabled()
        self._reflection = AgentReflection(store=store, config=config)

    @functools.wraps(original_arun)
    async def _patched_arun(self: Any, prompt: Any, *, tenant_id=None, max_turns=10, limit=32) -> Any:
        resp = await original_arun(self, prompt, tenant_id=tenant_id, max_turns=max_turns, limit=limit)
        refl = getattr(self, "_reflection", None)
        if refl is not None and refl.enabled:
            sid = _session_id_of(resp)
            try:
                lesson = refl.reflect(resp, tenant_id=tenant_id, session_id=sid)
            except Exception:  # pragma: no cover - reflexión nunca rompe el run
                lesson = None
            try:
                resp.raw.metadata["reflection"] = lesson
            except Exception:  # pragma: no cover - defensivo
                pass
        return resp

    agent_cls.__init__ = _patched_init  # type: ignore[assignment]
    agent_cls.arun = _patched_arun  # type: ignore[assignment]
    agent_cls._reflection_installed = True  # type: ignore[attr-defined]
    return agent_cls


def _session_id_of(resp: AgentResponse) -> str:
    raw = getattr(resp, "raw", None)
    meta = getattr(raw, "metadata", None) or {}
    sid = meta.get("session_id")
    return sid if isinstance(sid, str) else "default"


__all__ = ["AgentReflection", "ReflectionConfig", "install_agent_reflection_support"]
