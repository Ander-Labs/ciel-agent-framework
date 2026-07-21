"""MockProvider determinista para tests y evaluación offline (Fase 18).

Devuelve respuestas configurables sin red ni API keys, con tres modos:

- ``echo``: repite la última palabra del prompt del usuario (paridad con
  ``_EchoProvider`` de la CLI, que devuelve ``echo:<prompt>`` completo). Aquí
  repetimos la última palabra para que sea útil en eval de métricas cerradas.
- ``map``: dict ``prompt -> response`` (coincidencia exacta o substring).
- ``fixed``: respuesta constante.

Soporta ``complete`` / ``stream`` (parity: devuelve ``(response,)``) / ``models``
y respeta el contrato ``ChatProvider`` (``ciel.providers.ChatProvider``).
Offline-safe por construcción: no importa nada de red.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from ciel.providers import ChatProvider, ModelInfo
from ciel.runtime import ChatResponse, ChatChoice, ChatMessage


class MockProvider(ChatProvider):
    """Proveedor determinista configurable para eval/tests sin red.

    Args:
        mode: ``"echo"`` | ``"map"`` | ``"fixed"``.
        response: respuesta constante (modo ``fixed``).
        mapping: dict ``prompt -> response`` (modo ``map``). La coincidencia es
            exacta; si no hay exacta, se usa la primera clave que sea substring
            del prompt (case-insensitive).
        model: id de modelo devuelto por ``models()`` (default ``"mock"``).
        tenant: tenant_id propagado en metadata.
    """

    provider_name = "mock"

    def __init__(
        self,
        *,
        mode: str = "fixed",
        response: str = "",
        mapping: Optional[Dict[str, str]] = None,
        model: str = "mock",
        tenant: Optional[str] = None,
    ) -> None:
        if mode not in ("echo", "map", "fixed"):
            raise ValueError(f"MockProvider mode inválido: {mode!r}; usar echo|map|fixed")
        self.mode = mode
        self.response = response
        self.mapping = dict(mapping or {})
        self.model = model
        self.tenant = tenant

    def _respond(self, request: Any) -> str:
        if self.mode == "fixed":
            return self.response
        if self.mode == "echo":
            last = request.messages[-1].content if request.messages else ""
            if isinstance(last, list):
                last = "".join(p.get("text", "") for p in last if isinstance(p, dict))
            last = last or ""
            words = last.split()
            return words[-1] if words else ""
        # map
        prompt = request.messages[-1].content if request.messages else ""
        if isinstance(prompt, list):
            prompt = "".join(p.get("text", "") for p in prompt if isinstance(p, dict))
        prompt = prompt or ""
        if prompt in self.mapping:
            return self.mapping[prompt]
        lowered = prompt.lower()
        for key, val in self.mapping.items():
            if key and key.lower() in lowered:
                return val
        return self.mapping.get("", self.response)

    async def complete(self, request: Any) -> ChatResponse:
        text = self._respond(request)
        message = ChatMessage(role="assistant", content=text, metadata={"tenant": self.tenant})
        return ChatResponse(
            choice=ChatChoice(message=message, finish_reason="stop"),
            metadata={"provider": self.provider_name, "mode": self.mode, "tenant": self.tenant},
        )

    async def stream(self, request: Any) -> Sequence[ChatResponse]:
        return (await self.complete(request),)

    async def models(self) -> Sequence[ModelInfo]:
        return [
            ModelInfo(
                id=self.model,
                provider=self.provider_name,
                metadata={"tenant": self.tenant, "mode": self.mode},
            )
        ]
