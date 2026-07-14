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


def test_read_file_allowed_by_default() -> None:
    ctx = SandboxContext()
    result = ctx.read_file("/tmp/out.txt")
    assert "/tmp/out.txt" in result


def test_execute_stub_returns_mocked_output_when_allowed() -> None:
    policy = SandboxPolicy(allow_terminal=True)
    ctx = SandboxContext(policy=policy)
    result = ctx.execute("echo", {"text": "ciel"})
    assert "echo" in result
    assert "ciel" in result


def test_file_write_stub_returns_mocked_output_when_allowed() -> None:
    policy = SandboxPolicy(allow_file_write=True)
    ctx = SandboxContext(policy=policy)
    result = ctx.write_file("/tmp/out.txt", "hello")
    assert "/tmp/out.txt" in result
    assert "hello" in result or "5" in result
