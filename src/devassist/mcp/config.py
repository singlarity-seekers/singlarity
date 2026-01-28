"""MCP configuration loader for DevAssist.

Loads and validates MCP server configurations from .mcp.json files.
Supports environment variable expansion in configuration values.
"""

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    type: str = Field("stdio", description="Server type: stdio, http, or sse")
    command: str | None = Field(None, description="Command to run (for stdio type)")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables")
    url: str | None = Field(None, description="Server URL (for http/sse types)")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers")
    enabled: bool = Field(True, description="Whether this server is enabled")


class MCPSettings(BaseModel):
    """Global MCP settings."""

    model: str = Field("claude-sonnet-4-20250514", description="Claude model to use")
    max_tokens: int = Field(4096, description="Maximum tokens for responses")
    system_prompt: str | None = Field(None, description="Custom system prompt")


class MCPConfig(BaseModel):
    """Complete MCP configuration."""

    mcp_servers: dict[str, MCPServerConfig] = Field(
        default_factory=dict, description="MCP server configurations", alias="mcpServers"
    )
    settings: MCPSettings = Field(default_factory=MCPSettings, description="Global settings")

    model_config = {"populate_by_name": True}


class MCPConfigLoader:
    """Loads and manages MCP configuration from .mcp.json files."""

    MCP_CONFIG_FILENAME = ".mcp.json"
    ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

    def __init__(self, config_path: Path | str | None = None) -> None:
        """Initialize the MCP config loader.

        Args:
            config_path: Path to the .mcp.json file. Defaults to ~/.devassist/.mcp.json
        """
        if config_path is None:
            config_path = Path.home() / ".devassist" / self.MCP_CONFIG_FILENAME
        self.config_path = Path(config_path)
        self._config: MCPConfig | None = None

    def load(self) -> MCPConfig:
        """Load MCP configuration from file.

        Returns:
            MCPConfig with expanded environment variables.
        """
        if not self.config_path.exists():
            return MCPConfig()

        with open(self.config_path) as f:
            raw_config = json.load(f)

        # Expand environment variables in the config
        expanded_config = self._expand_env_vars(raw_config)

        self._config = MCPConfig(**expanded_config)
        return self._config

    def save(self, config: MCPConfig) -> None:
        """Save MCP configuration to file.

        Note: This saves the raw values, not expanded env vars.
        Use set_server() to properly preserve env var references.

        Args:
            config: MCPConfig to save.
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        config_dict = config.model_dump(by_alias=True)

        with open(self.config_path, "w") as f:
            json.dump(config_dict, f, indent=2)

        self._config = config

    def _expand_env_vars(self, obj: Any) -> Any:
        """Recursively expand environment variables in config values.

        Supports ${VAR_NAME} syntax.

        Args:
            obj: Config object (dict, list, or string).

        Returns:
            Object with env vars expanded.
        """
        if isinstance(obj, str):
            return self.ENV_VAR_PATTERN.sub(
                lambda m: os.environ.get(m.group(1), ""), obj
            )
        elif isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(v) for v in obj]
        return obj

    def get_server(self, name: str) -> MCPServerConfig | None:
        """Get configuration for a specific MCP server.

        Args:
            name: Server name (e.g., 'github', 'slack').

        Returns:
            MCPServerConfig or None if not configured.
        """
        config = self._config or self.load()
        return config.mcp_servers.get(name)

    def set_server(self, name: str, server_config: MCPServerConfig) -> None:
        """Set configuration for an MCP server.

        Args:
            name: Server name.
            server_config: Server configuration.
        """
        config = self._config or self.load()
        config.mcp_servers[name] = server_config
        self.save(config)

    def remove_server(self, name: str) -> bool:
        """Remove an MCP server configuration.

        Args:
            name: Server name to remove.

        Returns:
            True if server was removed, False if it didn't exist.
        """
        config = self._config or self.load()
        if name in config.mcp_servers:
            del config.mcp_servers[name]
            self.save(config)
            return True
        return False

    def list_servers(self) -> list[str]:
        """List all configured MCP server names.

        Returns:
            List of server names.
        """
        config = self._config or self.load()
        return list(config.mcp_servers.keys())

    def get_enabled_servers(self) -> dict[str, MCPServerConfig]:
        """Get all enabled MCP server configurations.

        Returns:
            Dict of enabled server configs keyed by name.
        """
        config = self._config or self.load()
        return {
            name: server
            for name, server in config.mcp_servers.items()
            if server.enabled
        }
