from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class Skill:
    name: str
    description: str
    content: str
    category: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    sha256: Optional[str] = None


_FRONTMATTER_RE = re.compile(r"^---\s*(.*?)\s*---", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*(.+)\s*$", re.MULTILINE)
_DESCRIPTION_RE = re.compile(r"^description:\s*(.+)\s*$", re.MULTILINE)


def _parse_frontmatter(text: str) -> Dict[str, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    block = match.group(1)
    result: Dict[str, str] = {}
    for regex in (_NAME_RE, _DESCRIPTION_RE):
        m = regex.search(block)
        if m:
            result[m.group().split(":", 1)[0].strip()] = m.group(1).strip()
    return result


def load_skill(path: str) -> Skill:
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()
    frontmatter = _parse_frontmatter(content)
    if "name" not in frontmatter:
        raise ValueError(f"missing skill name in frontmatter: {path}")
    hasher = hashlib.sha256()
    hasher.update(content.encode("utf-8"))
    return Skill(
        name=frontmatter.get("name", os.path.splitext(os.path.basename(path))[0]),
        description=frontmatter.get("description", ""),
        category=frontmatter.get("category"),
        content=content,
        metadata={"path": path},
        sha256=hasher.hexdigest(),
    )


class SkillRegistry:
    def __init__(self, roots: Optional[Sequence[str]] = None) -> None:
        self.roots: List[str] = list(roots or [])
        self.by_name: Dict[str, Skill] = {}
        self.by_category: Dict[str, List[Skill]] = {}
        self._path_seen: set[str] = set()

    def register_root(self, root: str) -> None:
        if root not in self.roots:
            self.roots.append(root)

    def discover(self) -> List[Skill]:
        self.by_name.clear()
        self.by_category.clear()
        self._path_seen.clear()
        found: List[Skill] = []
        for root in self.roots:
            if not os.path.isdir(root):
                continue
            for dirpath, _, filenames in os.walk(root):
                for filename in filenames:
                    if filename.lower() != "skill.md":
                        continue
                    path = os.path.join(dirpath, filename)
                    if path in self._path_seen:
                        continue
                    self._path_seen.add(path)
                    try:
                        skill = load_skill(path)
                    except ValueError:
                        continue
                    self.by_name[skill.name] = skill
                    if skill.category:
                        self.by_category.setdefault(skill.category, []).append(skill)
                    found.append(skill)
        return found

    def get(self, name: str) -> Optional[Skill]:
        return self.by_name.get(name)

    def list_skills(self, *, category: Optional[str] = None) -> List[Skill]:
        if category is None:
            return list(self.by_name.values())
        return list(self.by_category.get(category, []))
