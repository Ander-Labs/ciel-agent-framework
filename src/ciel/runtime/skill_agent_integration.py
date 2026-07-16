"""Fase 12 Item 5 — Integración con ciel.Agent.

Este módulo conecta la :class:`~ciel.runtime.skills_lib.SkillLibrary` (Item 1
de Fase 12) con la fachada de alto nivel ``ciel.api`` (Fases 10/11) de forma
100% offline y sin romper la API existente del ``Agent``.

Piezas que aporta:

* ``@ciel.skill`` — decorador que registra una función como ``Skill`` en una
  :class:`SkillLibrary` global (singleton), validando su sintaxis en tiempo de
  definición (``compile`` del source).
* ``global_skill_library`` — la instancia singleton compartida por todo el
  proceso (mismo patrón que el registro de herramientas).
* ``teach(agent, skill, ...)`` — helper que registra un *skill verificado* en
  un ``Agent`` ya construido, convirtiéndolo en un ``ToolFunction`` ejecutable
  a través del ``ToolRegistry`` existente.
* ``install_agent_skill_support(Agent)`` — engancha ``Agent(skills=[...])`` y
  ``Agent.teach(...)`` al ``Agent`` público *sin reescribir* ``api.py``: se
  invoca al final de ``ciel/api.py`` (ver regla 2 del ítem).

No se cambia la firma pública de ``Agent`` existente: el soporte de skills se
inyecta envuelto en ``__init__`` y como método ``teach``.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Dict, List, Optional, Sequence

from ciel.runtime.skills import Skill
from ciel.runtime.skills_lib import (
    SkillError,
    SkillLibrary,
    SkillVerificationError,
    SkillVerifier,
)
from ciel.runtime.tools import Tool


# ---------------------------------------------------------------------------
# Singleton — la librería de skills compartida por todo el proceso.
# ---------------------------------------------------------------------------
global_skill_library: SkillLibrary = SkillLibrary()


# ---------------------------------------------------------------------------
# @ciel.skill — registra una función como Skill validando su sintaxis.
# ---------------------------------------------------------------------------
def skill(
    fn: Optional[Any] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
) -> Any:
    """Decorador que registra ``fn`` como un ``Skill`` en la librería global.

    Valida la sintaxis de la función (``compile`` de su source) en tiempo de
    definición y guarda una referencia a la función original en
    ``metadata["_callable"]`` para poder exponerla luego como ``ToolFunction``
    sin tener que re-ejecutar el código fuente.

    Uso::

        import ciel

        @ciel.skill
        def add(a: int, b: int) -> int:
            \"Suma dos enteros.\"
            return a + b

        # Disponible de inmediato en la librería singleton:
        ciel.runtime.skill_agent_integration.global_skill_library.get("add")
    """

    def _decorate(func: Any) -> Any:
        sname = name or getattr(func, "__name__", "skill")
        sdesc = description or (inspect.getdoc(func) or "").strip() or sname
        source = _function_source(func)
        # Validación de sintaxis (offline, sin ejecutar).
        try:
            compile(source, f"<skill:{sname}>", "exec")
        except SyntaxError as exc:  # noqa: BLE001
            raise SkillError(f"skill '{sname}' has invalid syntax: {exc}") from exc

        skill_obj = Skill(
            name=sname,
            description=sdesc,
            content=source,
            category=category,
            metadata={"_callable": func, "source": source},
        )
        global_skill_library.register(skill_obj)
        # Marca la función para inspección/debug.
        try:
            func._ciel_skill = sname  # type: ignore[attr-defined]
        except AttributeError:  # pragma: no cover - builtins/non-settable
            pass
        return func

    if fn is not None:
        return _decorate(fn)
    return _decorate


def _function_source(func: Any) -> str:
    """Devuelve el source de ``func`` para validación de sintaxis.

    Se elimina cualquier línea de decorador ``@skill`` / ``@ciel.skill`` para
    que el contenido sea ejecutable de forma aislada (p.ej. por el
    :class:`SkillVerifier`) sin depender del decorador en runtime.
    """
    import re
    import textwrap

    try:
        raw = inspect.getsource(func)
    except (OSError, TypeError):  # pragma: no cover - REPL/def sin archivo
        # Fallback: no tenemos source legible; delegamos la validación al
        # momento de convertir a ToolFunction (que compila el contenido).
        return f"def {getattr(func, '__name__', 'skill')}(*args, **kwargs):\n    pass\n"
    lines = textwrap.dedent(raw).splitlines()
    # Quita decoradores @skill / @ciel.skill que preceden a la definición.
    decor_re = re.compile(r"^\s*@(ciel\.)?skill(\(.*\))?\s*$")
    while lines and decor_re.match(lines[0]):
        lines.pop(0)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Conversión Skill -> ToolFunction (reusa el registry / @ciel.tool existente).
# ---------------------------------------------------------------------------
def _skill_to_tool_function(skill_obj: Skill) -> Any:
    """Construye un ``ToolFunction`` ejecutable a partir de un ``Skill``.

    Prefiere la función original guardada en ``metadata["_callable"]``; si no
    existe (skill creado solo desde código fuente) lo reconstruye ejecutando el
    contenido en un namespace aislado. Reusa ``ciel.api.tool`` para inferir el
    esquema JSON a partir de las type hints.
    """
    fn = skill_obj.metadata.get("_callable")
    if fn is None:
        namespace: Dict[str, Any] = {}
        try:
            exec(compile(skill_obj.content, f"<skill:{skill_obj.name}>", "exec"), namespace)  # noqa: S102
        except Exception as exc:  # noqa: BLE001
            raise SkillError(f"skill '{skill_obj.name}' could not be loaded: {exc}") from exc
        fn = namespace.get(skill_obj.name)
        if fn is None or not callable(fn):
            callables = [
                v for v in namespace.values() if callable(v) and not inspect.isbuiltin(v)
            ]
            if not callables:
                raise SkillError(f"skill '{skill_obj.name}' defines no callable to expose as a tool")
            fn = callables[0]

    # Reusa la fachada pública de herramientas (inferencia de esquema + runtime
    # callable compatible). Import perezoso para evitar ciclos en tiempo de carga.
    from ciel.api import tool

    return tool(fn)


def _register_tool_function(agent: Any, tool_function: Any) -> None:
    """Registra un ``ToolFunction`` en el registry del agente en runtime."""
    from ciel.api import ToolFunction

    ciel_tool = tool_function.as_tool if isinstance(tool_function, ToolFunction) else tool_function
    if not isinstance(ciel_tool, Tool):
        raise TypeError(
            f"skill tool must be a ToolFunction or Tool, got {type(tool_function).__name__}"
        )
    agent.registry.register_tool(agent.toolset, ciel_tool)
    # Refresca la lista de specs que el Agent entrega al modelo en cada run.
    agent._tool_specs.append(ciel_tool.spec)


# ---------------------------------------------------------------------------
# teach(agent, skill) — registra un skill *verificado* en runtime.
# ---------------------------------------------------------------------------
def teach(
    agent: Any,
    skill_obj: Skill,
    *,
    test_cases: Optional[Sequence[Dict[str, Any]]] = None,
    verify: bool = True,
) -> Any:
    """Registra ``skill_obj`` como herramienta ejecutable en ``agent``.

    Si ``test_cases`` se provee y ``verify=True``, el skill pasa primero por el
    :class:`SkillVerifier` offline; se lanza :class:`SkillVerificationError` si
    no pasa. Devuelve el ``ToolFunction`` registrado.
    """
    if verify and test_cases:
        verifier = SkillVerifier(library=global_skill_library)
        result = verifier.verify(skill_obj, test_cases=list(test_cases))
        if not result.passed:
            raise SkillVerificationError(
                f"skill '{skill_obj.name}' failed verification: {result.error}"
            )
    tool_function = _skill_to_tool_function(skill_obj)
    _register_tool_function(agent, tool_function)
    return tool_function


def load_agent_skills(agent: Any, skill_names: Sequence[str]) -> List[Any]:
    """Carga una lista de nombres de skills (desde la librería global) en el agente."""
    registered: List[Any] = []
    for skill_name in skill_names:
        skill_obj = global_skill_library.get(skill_name)
        if skill_obj is None:
            raise SkillError(
                f"unknown skill '{skill_name}'; declare it first with @ciel.skill"
            )
        tool_function = _skill_to_tool_function(skill_obj)
        _register_tool_function(agent, tool_function)
        registered.append(tool_function)
    return registered


# ---------------------------------------------------------------------------
# Enganche al Agent público (invocado al final de ciel/api.py).
# ---------------------------------------------------------------------------
def install_agent_skill_support(agent_cls: Any) -> Any:
    """Inyecta ``skills=[...]`` en ``__init__`` y ``teach`` como método.

    No reescribe nada de ``api.py``: envuelve ``__init__`` para consumir el
    kwarg ``skills`` (y cargarlos como tools) y adjunta ``teach`` / ``load_skills``
    como métodos de instancia.
    """
    original_init = agent_cls.__init__

    @functools.wraps(original_init)
    def _patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        skills = kwargs.pop("skills", None)
        original_init(self, *args, **kwargs)
        if skills:
            load_agent_skills(self, list(skills))

    agent_cls.__init__ = _patched_init
    # teach(agent, skill) se enlaza como método de instancia:
    #   agent.teach(skill) -> teach(agent, skill)
    agent_cls.teach = teach  # type: ignore[attr-defined]
    agent_cls.load_skills = load_agent_skills  # type: ignore[attr-defined]
    return agent_cls


__all__ = [
    "global_skill_library",
    "skill",
    "teach",
    "load_agent_skills",
    "install_agent_skill_support",
]
