"""Tests for MCP server registry."""

import tempfile
from unittest.mock import patch

from devassist.mcp.registry import (
    ATLASSIAN_REMOTE_MCP_URL,
    MCPRegistry,
    _resolve_mcp_executable,
)


def test_resolve_mcp_executable_prefers_which() -> None:
    with patch("devassist.mcp.registry.shutil.which", return_value="/custom/bin/some-mcp"):
        assert _resolve_mcp_executable("some-mcp") == "/custom/bin/some-mcp"


def test_atlassian_default_uses_mcp_remote() -> None:
    reg = MCPRegistry()
    cfg = reg.get("atlassian")
    assert cfg is not None
    assert "npx" in cfg.command.lower()
    assert cfg.args == ["-y", "mcp-remote", ATLASSIAN_REMOTE_MCP_URL]
    assert cfg.env == {}
    assert cfg.enabled is False  # opt-in via -s atlassian, not default auto-connect


def test_filesystem_mcp_uses_os_temp_dir() -> None:
    reg = MCPRegistry()
    fs = reg.get("filesystem")
    assert fs is not None
    assert fs.args[-1] == tempfile.gettempdir()
