from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


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


@dataclass
class SandboxContext:
    policy: Optional[SandboxPolicy] = None

    def __post_init__(self) -> None:
        if self.policy is None:
            self.policy = SandboxPolicy()

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
        return _execution_stub(command, arguments)

    def write_file(self, path: str, content: str) -> str:
        if not self.evaluate("file_write"):
            raise SandboxBlockedError("file_write", f"write to '{path}' denied")
        return _file_write_stub(path, content)

    def read_file(self, path: str) -> str:
        if not self.evaluate("file_read"):
            raise SandboxBlockedError("file_read", f"read from '{path}' denied")
        return _file_read_stub(path)


def _execution_stub(command: str, arguments: Dict[str, Any]) -> str:
    return f"[stub] executed {command} with {arguments}"


def _file_write_stub(path: str, content: str) -> str:
    return f"[stub] wrote {len(content)} bytes to {path}"


def _file_read_stub(path: str) -> str:
    return f"[stub] read from {path}"
