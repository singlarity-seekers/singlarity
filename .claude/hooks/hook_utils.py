#!/usr/bin/env python3
"""
Shared utilities for Claude Code hooks.

Imported by metrics_hook.py and langfuse_hook.py to eliminate duplication.
Do not add heavy dependencies here — this module is loaded on every hook
invocation and must import quickly.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# fcntl is Unix-only; fail gracefully on other platforms.
try:
    import fcntl
    _HAVE_FCNTL = True
except ImportError:
    _HAVE_FCNTL = False

# ── Paths ─────────────────────────────────────────────────────────────

STATE_DIR = Path(__file__).resolve().parent / "state"

# Create once at module load — fast no-op if it already exists.
STATE_DIR.mkdir(parents=True, exist_ok=True)


# ── Logging ───────────────────────────────────────────────────────────

class Logger:
    """Lightweight per-hook file logger.

    Usage:
        log = Logger(STATE_DIR / "my_hook.log", debug_enabled=DEBUG)
        log.info("started")
        log.debug("only shown when debug_enabled=True")
    """

    def __init__(self, log_file: Path, debug_enabled: bool = False) -> None:
        self._log_file = log_file
        self.debug_enabled = debug_enabled

    def _write(self, level: str, message: str) -> None:
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(f"{ts} [{level}] {message}\n")
        except Exception:
            pass  # Never block the hook

    def debug(self, msg: str) -> None:
        if self.debug_enabled:
            self._write("DEBUG", msg)

    def info(self, msg: str) -> None:
        self._write("INFO", msg)

    def warn(self, msg: str) -> None:
        self._write("WARN", msg)

    def error(self, msg: str) -> None:
        self._write("ERROR", msg)


# ── File locking (best-effort) ────────────────────────────────────────

class FileLock:
    """Exclusive advisory lock via fcntl.flock.

    Fails open when fcntl is unavailable (non-Unix) or when the timeout
    expires — the hook always proceeds, just without the lock guarantee.
    """

    def __init__(self, path: Path, timeout_s: float = 2.0) -> None:
        self.path = path
        self.timeout_s = timeout_s
        self._fh = None

    def __enter__(self) -> "FileLock":
        self._fh = open(self.path, "a+", encoding="utf-8")
        if _HAVE_FCNTL:
            deadline = time.time() + self.timeout_s
            while True:
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.time() > deadline:
                        break
                    time.sleep(0.05)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if _HAVE_FCNTL:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        try:
            self._fh.close()
        except Exception:
            pass


# ── Hook payload ──────────────────────────────────────────────────────

def read_hook_payload() -> Dict[str, Any]:
    """Read and parse the JSON payload Claude Code writes to stdin."""
    try:
        data = sys.stdin.read()
        if not data.strip():
            return {}
        return json.loads(data)
    except Exception:
        return {}


# ── Langfuse credentials ──────────────────────────────────────────────

def resolve_langfuse_credentials() -> Tuple[Optional[str], Optional[str], str]:
    """Return (public_key, secret_key, host) from environment variables.

    Checks CC_LANGFUSE_* first, then LANGFUSE_* as fallback.
    Host defaults to http://localhost:3000 when not set.
    """
    public_key = (
        os.environ.get("CC_LANGFUSE_PUBLIC_KEY")
        or os.environ.get("LANGFUSE_PUBLIC_KEY")
    )
    secret_key = (
        os.environ.get("CC_LANGFUSE_SECRET_KEY")
        or os.environ.get("LANGFUSE_SECRET_KEY")
    )
    host = (
        os.environ.get("CC_LANGFUSE_BASE_URL")
        or os.environ.get("LANGFUSE_BASE_URL")
        or "http://localhost:3000"
    )
    return public_key, secret_key, host