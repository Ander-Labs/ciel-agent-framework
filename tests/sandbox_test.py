from __future__ import annotations

import pytest

from ciel.sandbox import SandboxBlockedError, SandboxContext, SandboxPolicy


def test_default_policy_denies_terminal() -> None:
    ctx = SandboxContext()
    assert ctx.evaluate("terminal") is False


def test_default_policy_denies_file_write() -> None:
    ctx = SandboxContext()
    assert ctx.evaluate("file_write") is False


def test_default_policy_allows_file_read() -> None:
    ctx = SandboxContext()
    assert ctx.evaluate("file_read") is True


def test_evaluate_allows_allowed_command_when_terminal_enabled() -> None:
    policy = SandboxPolicy(allow_terminal=True, allowed_commands={"ls", "echo"})
    ctx = SandboxContext(policy=policy)
    assert ctx.evaluate("terminal", command="ls") is True


def test_evaluate_denies_unknown_command_when_allowed_list_set() -> None:
    policy = SandboxPolicy(allow_terminal=True, allowed_commands={"ls"})
    ctx = SandboxContext(policy=policy)
    assert ctx.evaluate("terminal", command="cat") is False


def test_evaluate_denies_denied_command_even_when_terminal_enabled() -> None:
    policy = SandboxPolicy(allow_terminal=True, denied_commands={"rm"})
    ctx = SandboxContext(policy=policy)
    assert ctx.evaluate("terminal", command="rm") is False


def test_execute_raises_when_terminal_blocked() -> None:
    ctx = SandboxContext()
    with pytest.raises(SandboxBlockedError):
        ctx.execute("ls", {"path": "/"})


def test_write_file_raises_when_blocked() -> None:
    ctx = SandboxContext()
    with pytest.raises(SandboxBlockedError):
        ctx.write_file("/tmp/out.txt", "hello")


def test_read_file_allowed_by_default(tmp_path) -> None:
    ctx = SandboxContext()
    target = tmp_path / "out.txt"
    target.write_text("hello-real", encoding="utf-8")
    result = ctx.read_file(str(target))
    assert result == "hello-real"


def test_execute_runs_real_command_when_allowed() -> None:
    policy = SandboxPolicy(allow_terminal=True)
    ctx = SandboxContext(policy=policy)
    result = ctx.execute("echo", {"args": ["ciel"]})
    assert "ciel" in result


def test_file_write_writes_real_file_when_allowed(tmp_path) -> None:
    policy = SandboxPolicy(allow_file_write=True)
    ctx = SandboxContext(policy=policy)
    target = tmp_path / "out.txt"
    result = ctx.write_file(str(target), "hello")
    assert str(target) in result
    assert target.read_text(encoding="utf-8") == "hello"
