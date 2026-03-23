"""Tests for exception formatting helpers."""

from devassist.core.exceptions import flatten_exception_messages, format_user_facing_error


def test_simple_exception() -> None:
    e = ValueError("bad")
    assert flatten_exception_messages(e) == ["ValueError: bad"]
    assert format_user_facing_error(e) == "ValueError: bad"


def test_exception_group_unwraps() -> None:
    inner = FileNotFoundError("/opt/homebrew/bin/npx")
    group = ExceptionGroup("unhandled errors in a TaskGroup", [inner])
    lines = flatten_exception_messages(group)
    assert len(lines) == 1
    assert "FileNotFoundError" in lines[0]
    assert "npx" in lines[0]
