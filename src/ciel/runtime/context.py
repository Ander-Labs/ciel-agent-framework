from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


DEFAULT_FILES = (
    ".hermes.md",
    "HERMES.md",
    "AGENTS.md",
    "agents.md",
    "CLAUDE.md",
    "claude.md",
    ".cursorrules",
)


class ContextInjectionError(Exception):
    """Raised when a project context file cannot be loaded."""


@dataclass(frozen=True)
class ContextFile:
    path: str
    name: str
    source: str
    content: str
    size: int
    truncated: bool = False
    max_chars: int = 20_000


@dataclass
class ProjectContext:
    files: Sequence[ContextFile] = ()
    raw: str = ""

    def render(self, max_chars: int = 20_000) -> str:
        if not self.files:
            return ""
        parts: List[str] = []
        total = 0
        for item in self.files:
            header = f"<context file={item.name} path={item.path} source={item.source}>"
            footer = "</context>"
            block = f"{header}\n{item.content}\n{footer}\n"
            if total + len(block) > max_chars:
                remaining = max(0, max_chars - total)
                if remaining <= 0:
                    break
                block = block[:remaining] + "\n[...truncated...]\n"
                parts.append(block)
                break
            total += len(block)
            parts.append(block)
        return "\n".join(parts)


def _read_file(path: Path, max_chars: int = 20_000) -> Tuple[str, bool]:
    text = path.read_text(encoding="utf-8")
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n[...truncated...]\n"
    return text, truncated


def _walk_parents(current: Path, stop_at_git_root_first_match: bool = True) -> List[Path]:
    paths: List[Path] = []
    for directory in [current, *current.parents]:
        paths.append(directory)
        if stop_at_git_root_first_match and (directory / ".git").exists():
            return paths[: paths.index(directory) + 1]
    return paths


def _find_default_context(current: Path) -> Optional[Tuple[Path, str]]:
    for directory in _walk_parents(current):
        for name in DEFAULT_FILES:
            candidate = directory / name
            if candidate.exists() and candidate.is_file():
                source = "hierarchical: .hermes/HERMES.md"
                if name.upper() in {"AGENTS.md", "CLAUDE.md", ".CURSORRULES"}:
                    source = f"cwd-only: {name}"
                return candidate, source
    return None


def load_project_context(
    path: Optional[str] = None,
    max_chars: int = 20_000,
) -> "ProjectContext":
    target = Path(path or os.getcwd()).resolve()
    found = _find_default_context(target)
    if found is None:
        return ProjectContext()
    candidate, source = found
    text, truncated = _read_file(candidate, max_chars=max_chars)
    return ProjectContext(
        files=(
            ContextFile(
                path=str(candidate),
                name=candidate.name,
                source=source,
                content=text,
                size=len(text),
                truncated=truncated,
                max_chars=max_chars,
            ),
        ),
        raw=text,
    )
