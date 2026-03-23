"""Helpers for displaying nested asyncio / TaskGroup errors in the CLI."""

from __future__ import annotations


def flatten_exception_messages(exc: BaseException) -> list[str]:
    """Collect leaf messages from ExceptionGroup wrappers (e.g. anyio TaskGroup)."""
    if isinstance(exc, BaseExceptionGroup):
        messages: list[str] = []
        for sub in exc.exceptions:
            messages.extend(flatten_exception_messages(sub))
        return messages
    return [f"{type(exc).__name__}: {exc}"]


def format_user_facing_error(exc: BaseException) -> str:
    """Human-readable message; unwraps ExceptionGroup so the root cause is visible."""
    lines = flatten_exception_messages(exc)
    if len(lines) == 1:
        return lines[0]
    return "\n".join(f"  • {line}" for line in lines)
