"""MCP configuration models for DevAssist.

Defines the structure for .mcp.json configuration file with support for:
- MCP server definitions
- AI provider configuration (Claude, Vertex AI)
- Background runner settings
- Context source configurations
"""

import os
import re
from typing import Any, Literal

from pydantic import BaseModel, Field


class ClaudeConfig(BaseModel):
    """Configuration for Anthropic Claude API."""

    api_key: str | None = None
    model: str = "claude-sonnet-4-5@20250929"
    max_tokens: int = 4096
    temperature: float = 0.7


class VertexConfig(BaseModel):
    """Configuration for Google Vertex AI."""

    api_key: str | None = None
    project_id: str = ""
    location: str = "us-central1"
    model: str = "gemini-2.5-flash"


class AIProviderConfig(BaseModel):
    """AI provider configuration supporting multiple providers."""

    provider: Literal["claude", "vertex"] = "claude"
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)
    vertex: VertexConfig = Field(default_factory=VertexConfig)


class RunnerConfig(BaseModel):
    """Background runner configuration."""

    enabled: bool = False
    interval_minutes: int = 5
    prompt: str = "Review my context and summarize urgent items."
    last_run: str | None = None
    status: Literal["stopped", "running", "error"] = "stopped"
    last_error: str | None = None
    output_destination: str = "~/.devassist/runner-output.md"
    notify_on_completion: bool = False
    sources: list[str] = Field(default_factory=list)


class MCPServerConfig(BaseModel):
    """MCP server configuration."""

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class PreferencesConfig(BaseModel):
    """User preference configuration (for backward compatibility)."""

    priority_keywords: list[str] = Field(
        default_factory=list, description="Keywords to prioritize"
    )


class MCPConfig(BaseModel):
    """Main MCP configuration model.

    Represents the complete .mcp.json configuration file structure.
    """

    version: str = "1.0"
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
    ai: AIProviderConfig = Field(default_factory=AIProviderConfig)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)
    preferences: PreferencesConfig = Field(default_factory=PreferencesConfig)


def expand_env_vars(data: Any) -> Any:
    """Recursively expand ${VAR} environment variable references.

    Supports expansion in:
    - String values: "prefix_${VAR}_suffix" → "prefix_value_suffix"
    - Nested dictionaries
    - Lists

    Undefined variables are replaced with empty string.

    Args:
        data: Configuration data (dict, list, str, or primitive type).

    Returns:
        Data with environment variables expanded.

    Examples:
        >>> os.environ["API_KEY"] = "secret"
        >>> expand_env_vars({"key": "${API_KEY}"})
        {'key': 'secret'}
        >>> expand_env_vars({"nested": {"key": "${API_KEY}"}})
        {'nested': {'key': 'secret'}}
    """
    if isinstance(data, dict):
        return {key: expand_env_vars(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [expand_env_vars(item) for item in data]
    elif isinstance(data, str):
        # Replace ${VAR} with os.environ.get('VAR', '')
        return re.sub(
            r"\$\{(\w+)\}",
            lambda match: os.environ.get(match.group(1), ""),
            data,
        )
    else:
        return data
