"""Configuration manager for DevAssist.

Handles loading, saving, and managing application configuration.
Supports environment variable overrides and .mcp.json format.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from devassist.models.config import AIConfig, AppConfig
from devassist.models.runner_config import MCPConfig, expand_env_vars

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages application configuration with .mcp.json and legacy YAML support."""

    CONFIG_FILENAME = "config.yaml"  # Legacy
    MCP_FILENAME = ".mcp.json"
    ENV_PREFIX = "DEVASSIST_"

    def __init__(self, workspace_dir: Path | str | None = None) -> None:
        """Initialize ConfigManager.

        Args:
            workspace_dir: Path to workspace directory. Defaults to ~/.devassist
        """
        if workspace_dir is None:
            workspace_dir = Path.home() / ".devassist"
        self.workspace_dir = Path(workspace_dir)
        self._ensure_workspace_exists()
        self._config: MCPConfig | AppConfig | None = None

    def _ensure_workspace_exists(self) -> None:
        """Create workspace directory if it doesn't exist."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    @property
    def config_path(self) -> Path:
        """Get path to config file."""
        return self.workspace_dir / self.CONFIG_FILENAME

    def load_config(self) -> MCPConfig | AppConfig:
        """Load configuration with precedence handling.

        Configuration precedence:
        1. ./.mcp.json (current working directory)
        2. ~/.devassist/.mcp.json (workspace directory)
        3. ~/.devassist/config.yaml (legacy, deprecated)
        4. Defaults (MCPConfig)

        Returns:
            MCPConfig or AppConfig (legacy) instance.
        """
        cwd_mcp_path = Path.cwd() / self.MCP_FILENAME
        workspace_mcp_path = self.workspace_dir / self.MCP_FILENAME
        legacy_config_path = self.config_path

        # Priority 1: Current working directory .mcp.json
        if cwd_mcp_path.exists():
            config = self._load_mcp_config(cwd_mcp_path)
            self._config = config
            return config

        # Priority 2: Workspace .mcp.json
        if workspace_mcp_path.exists():
            config = self._load_mcp_config(workspace_mcp_path)
            self._config = config
            return config

        # Priority 3: Legacy config.yaml
        if legacy_config_path.exists():
            logger.warning(
                "config.yaml is deprecated. Run 'devassist config migrate' to upgrade to .mcp.json"
            )
            config = self._load_legacy_config(legacy_config_path)
            self._config = config
            return config

        # Priority 4: Defaults
        config = MCPConfig()
        self._config = config
        return config

    def _load_mcp_config(self, path: Path) -> MCPConfig:
        """Load MCPConfig from .mcp.json file.

        Args:
            path: Path to .mcp.json file.

        Returns:
            MCPConfig instance with environment variables expanded.
        """
        with open(path) as f:
            data = json.load(f)

        # Expand environment variables
        data = expand_env_vars(data)

        # Create and return config
        return MCPConfig(**data)

    def _load_legacy_config(self, path: Path) -> AppConfig:
        """Load legacy AppConfig from config.yaml.

        Args:
            path: Path to config.yaml file.

        Returns:
            AppConfig instance with environment variable overrides.
        """
        config_data: dict[str, Any] = {}

        with open(path) as f:
            file_data = yaml.safe_load(f)
            if file_data:
                config_data = file_data

        config = AppConfig(**config_data)
        config = self._apply_env_overrides(config)
        return config

    def _apply_env_overrides(self, config: AppConfig) -> AppConfig:
        """Apply environment variable overrides to config.

        Supports:
            - DEVASSIST_AI_PROJECT_ID
            - DEVASSIST_AI_LOCATION
            - DEVASSIST_AI_MODEL
            - DEVASSIST_WORKSPACE_DIR

        Args:
            config: Base config to override.

        Returns:
            Config with env var overrides applied.
        """
        config_dict = config.model_dump()

        # AI config overrides
        ai_overrides: dict[str, Any] = {}
        if project_id := os.environ.get(f"{self.ENV_PREFIX}AI_PROJECT_ID"):
            ai_overrides["project_id"] = project_id
        if location := os.environ.get(f"{self.ENV_PREFIX}AI_LOCATION"):
            ai_overrides["location"] = location
        if model := os.environ.get(f"{self.ENV_PREFIX}AI_MODEL"):
            ai_overrides["model"] = model

        if ai_overrides:
            current_ai = config_dict.get("ai", {})
            current_ai.update(ai_overrides)
            config_dict["ai"] = current_ai

        # Workspace dir override
        if workspace := os.environ.get(f"{self.ENV_PREFIX}WORKSPACE_DIR"):
            config_dict["workspace_dir"] = workspace

        return AppConfig(**config_dict)

    def save_config(self, config: MCPConfig | AppConfig) -> None:
        """Save configuration to appropriate file format.

        Args:
            config: MCPConfig or AppConfig instance to save.
        """
        self._ensure_workspace_exists()

        if isinstance(config, MCPConfig):
            # Save as .mcp.json to workspace
            config_dict = config.model_dump()
            mcp_path = self.workspace_dir / self.MCP_FILENAME
            with open(mcp_path, "w") as f:
                json.dump(config_dict, f, indent=2)
        else:
            # Save as legacy config.yaml
            config_dict = config.model_dump()
            with open(self.config_path, "w") as f:
                yaml.safe_dump(config_dict, f, default_flow_style=False)

        self._config = config

    def get_source_config(self, source_name: str) -> dict[str, Any] | None:
        """Get configuration for a specific source.

        Works with both MCPConfig and AppConfig.

        Args:
            source_name: Name of the source (e.g., 'gmail', 'slack').

        Returns:
            Source configuration dict or None if not configured.
        """
        config = self._config or self.load_config()
        return config.sources.get(source_name)

    def set_source_config(
        self, source_name: str, source_config: dict[str, Any]
    ) -> None:
        """Set configuration for a specific source.

        Works with both MCPConfig and AppConfig.

        Args:
            source_name: Name of the source.
            source_config: Configuration dict for the source.
        """
        config = self._config or self.load_config()
        config.sources[source_name] = source_config
        self.save_config(config)

    def remove_source_config(self, source_name: str) -> bool:
        """Remove configuration for a specific source.

        Works with both MCPConfig and AppConfig.

        Args:
            source_name: Name of the source to remove.

        Returns:
            True if source was removed, False if it didn't exist.
        """
        config = self._config or self.load_config()
        if source_name in config.sources:
            del config.sources[source_name]
            self.save_config(config)
            return True
        return False

    def list_sources(self) -> list[str]:
        """List all configured source names.

        Works with both MCPConfig and AppConfig.

        Returns:
            List of configured source names.
        """
        config = self._config or self.load_config()
        return list(config.sources.keys())
