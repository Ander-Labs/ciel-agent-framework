"""CLI `ciel skills` — dynamic skill library management (offline-safe).

Comandos:
  ciel skills list
  ciel skills create --name N --description D --code-file F
  ciel skills verify --name N --test-cases FILE
  ciel skills remove --name N

Todo opera sobre un :class:`SkillLibrary` en memoria/offline (sin red ni API
keys), usando las primitivas de :mod:`ciel.runtime.skills_lib`
(``SkillLibrary``, ``SkillVerifier``). Se exponen funciones de lógica pura
(``list_registered``, ``create_skill``, ``verify_skill``, ``remove_skill``)
que reciben la librería explícitamente, de modo que los tests pueden inyectar
su propia instancia y compartir estado entre llamadas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

import typer
from rich.console import Console
from rich.table import Table

from ciel.runtime.skills import Skill
from ciel.runtime.skills_lib import SkillLibrary, SkillVerificationResult, SkillVerifier

skills_app = typer.Typer(name="skills", help="Dynamic skill library management (offline)")
console = Console()


# --------------------------------------------------------------------------- #
# Lógica pura (testeable directamente).
# --------------------------------------------------------------------------- #
def list_registered(lib: SkillLibrary) -> List[Skill]:
    """Devuelve los skills registrados (última versión de cada nombre)."""
    return lib.list_skills()


def create_skill(
    lib: SkillLibrary,
    *,
    name: str,
    description: str,
    code_file: str,
    category: str | None = None,
) -> Skill:
    """Lee ``code_file`` y registra un skill vía ``SkillLibrary.create_from_code``."""
    path = Path(code_file)
    code = path.read_text(encoding="utf-8")
    return lib.create_from_code(
        name=name,
        description=description,
        code=code,
        category=category,
    )


def verify_skill(
    lib: SkillLibrary,
    *,
    name: str,
    test_cases: Sequence[Dict[str, Any]],
) -> SkillVerificationResult:
    """Verifica ``name`` contra ``test_cases`` usando :class:`SkillVerifier`."""
    verifier = SkillVerifier(library=lib)
    return verifier.verify_by_name(name, test_cases=test_cases)


def remove_skill(lib: SkillLibrary, *, name: str) -> bool:
    """Elimina ``name`` de la librería en memoria. Devuelve True si existía."""
    return lib.remove(name)


def _load_test_cases(path: str) -> List[Dict[str, Any]]:
    """Carga casos de prueba desde un archivo JSON (lista de dicts)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise typer.BadParameter("test-cases file must contain a JSON list")
    return data


def _library() -> SkillLibrary:
    """Librería en memoria por defecto para la CLI (offline, fresh por proceso)."""
    return SkillLibrary()


# --------------------------------------------------------------------------- #
# Comandos typer (capa fina sobre la lógica pura).
# --------------------------------------------------------------------------- #
@skills_app.command("list")
def list_cmd() -> None:
    """Lista los skills registrados en la librería en memoria."""
    lib = _library()
    skills = list_registered(lib)
    table = Table(title="Registered skills")
    table.add_column("name")
    table.add_column("category")
    table.add_column("description")
    if not skills:
        console.print("[dim](no skills registered)[/]")
        return
    for skill in skills:
        table.add_row(
            skill.name,
            skill.category or "(none)",
            (skill.description or "").strip(),
        )
    console.print(table)


@skills_app.command("create")
def create_cmd(
    name: str = typer.Option(..., "--name", help="Skill name"),
    description: str = typer.Option(..., "--description", help="Skill description"),
    code_file: Path = typer.Option(
        ..., "--code-file", exists=True, dir_okay=False, help="Path to a .py file with the skill code"
    ),
    category: str | None = typer.Option(None, "--category", help="Optional category"),
) -> None:
    """Crea un skill desde un archivo de código y lo registra en memoria."""
    lib = _library()
    try:
        skill = create_skill(
            lib,
            name=name,
            description=description,
            code_file=str(code_file),
            category=category,
        )
    except Exception as exc:  # SyntaxError de compile() se propaga como SkillError
        console.print(f"[red]create failed[/] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]created[/] name={skill.name} sha={skill.sha256[:12] if skill.sha256 else '(none)'} "
        f"category={skill.category or '(none)'}"
    )


@skills_app.command("verify")
def verify_cmd(
    name: str = typer.Option(..., "--name", help="Skill name to verify"),
    test_cases_file: Path = typer.Option(
        ..., "--test-cases", exists=True, dir_okay=False, help="JSON file: list of {\"call\": {}, \"expect\": value}"
    ),
) -> None:
    """Verifica un skill contra casos de prueba (offline, sin ejecución de red)."""
    lib = _library()
    try:
        cases = _load_test_cases(str(test_cases_file))
    except Exception as exc:
        console.print(f"[red]invalid test-cases file[/] {exc}")
        raise typer.Exit(code=1) from exc

    result = verify_skill(lib, name=name, test_cases=cases)
    if result.passed:
        console.print(f"[green]PASS[/] skill={result.skill} cases={result.attempts}")
    else:
        console.print(
            f"[red]FAIL[/] skill={result.skill} "
            f"(attempt {result.attempts}): {result.error}"
        )
        raise typer.Exit(code=1)


@skills_app.command("remove")
def remove_cmd(
    name: str = typer.Option(..., "--name", help="Skill name to remove"),
) -> None:
    """Elimina un skill de la librería en memoria."""
    lib = _library()
    removed = remove_skill(lib, name=name)
    if removed:
        console.print(f"[green]removed[/] name={name}")
    else:
        console.print(f"[yellow]not found[/] name={name}")
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    skills_app()
