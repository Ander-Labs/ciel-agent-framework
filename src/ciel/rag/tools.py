"""Tools RAG para exponer KnowledgeBase/Retriever al agente (Pilar C — Fase 17).

Devuelven objetos ``Tool`` (mismo contrato que skills/tools) para que el
agente pueda hacer RAG vía tool-calls. Offline-safe: usan la KB ya indexada.

El callable de cada tool sigue el contrato oficial del dispatcher de runtime:
``callable_(arguments, *, tool_call_id, tenant_id) -> ToolResult``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ciel.rag.knowledge_base import KnowledgeBase, Retriever
from ciel.runtime.tools import Tool, ToolResult, ToolSpec


def _make_retriever(kb: KnowledgeBase, *, top_k: int, alpha: float) -> Retriever:
    return Retriever(kb, top_k=top_k, alpha=alpha)


def make_retrieve_tool(
    kb: KnowledgeBase,
    *,
    name: str = "retrieve",
    top_k: int = 5,
    alpha: float = 0.5,
) -> Tool:
    """Tool ``retrieve``: busca en la KB y devuelve contexto relevante."""

    spec = ToolSpec(
        name=name,
        description=(
            "Busca en la base de conocimiento del tenant y devuelve los fragmentos "
            "más relevantes para responder la pregunta del usuario (RAG híbrido "
            "BM25 + vector). Usa esto cuando necesites hechos externos al modelo."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Consulta de búsqueda semántica/keyword.",
                }
            },
            "required": ["query"],
        },
    )

    def _call(
        arguments: Dict[str, Any],
        *,
        tool_call_id: str = "",
        tenant_id: Optional[str] = None,
    ) -> ToolResult:
        query = arguments.get("query", "")
        retriever = _make_retriever(kb, top_k=top_k, alpha=alpha)
        ctx = retriever.context(query, tenant_id=tenant_id)
        if not ctx:
            return ToolResult(
                id=tool_call_id,
                name=name,
                output="No se encontró contexto relevante en la base de conocimiento.",
                metadata={"tenant_id": tenant_id},
            )
        return ToolResult(
            id=tool_call_id,
            name=name,
            output=ctx,
            metadata={"tenant_id": tenant_id},
        )

    return Tool(spec, _call)  # type: ignore[arg-type]


def make_kb_add_tool(
    kb: KnowledgeBase,
    *,
    name: str = "kb_add",
) -> Tool:
    """Tool ``kb_add``: indexa texto nuevo en la KB del tenant en runtime."""

    spec = ToolSpec(
        name=name,
        description=(
            "Añade un fragmento de texto a la base de conocimiento del tenant para "
            "consultas futuras (RAG). Útil para memorizar hechos durante la sesión."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Texto a indexar en la base de conocimiento.",
                }
            },
            "required": ["text"],
        },
    )

    def _call(
        arguments: Dict[str, Any],
        *,
        tool_call_id: str = "",
        tenant_id: Optional[str] = None,
    ) -> ToolResult:
        text = arguments.get("text", "")
        if not text:
            return ToolResult(
                id=tool_call_id,
                name=name,
                error="text vacío.",
                metadata={"tenant_id": tenant_id},
            )
        tenant = tenant_id or kb.tenant_id
        kb.add_texts([text], tenant_id=tenant)
        return ToolResult(
            id=tool_call_id,
            name=name,
            output=f"Indexado en la base de conocimiento (tenant={tenant or 'default'}).",
            metadata={"tenant_id": tenant_id},
        )

    return Tool(spec, _call)  # type: ignore[arg-type]


def rag_tools(
    kb: KnowledgeBase,
    *,
    top_k: int = 5,
    alpha: float = 0.5,
    with_kb_add: bool = True,
) -> list:
    """Devuelve la lista de tools RAG para pasar a ``Agent(tools=[...])``."""
    tools: list = [make_retrieve_tool(kb, top_k=top_k, alpha=alpha)]
    if with_kb_add:
        tools.append(make_kb_add_tool(kb))
    return tools


__all__ = ["make_retrieve_tool", "make_kb_add_tool", "rag_tools"]
