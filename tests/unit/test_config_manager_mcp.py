"""Unit tests for ConfigManager with .mcp.json support."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from devassist.core.config_manager import ConfigManager
from devassist.models.config import AppConfig
from devassist.models.mcp_config import MCPConfig


class TestMCPConfigLoading:
    """Tests for loading .mcp.json configuration."""

    def test_loads_mcp_json_from_workspace(self, tmp_path: Path) -> None:
        """Should load .mcp.json from workspace directory."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()

        mcp_config = {
            "version": "1.0",
            "ai": {"provider": "claude"},
            "runner": {"enabled": True},
            "sources": {"gmail": {"enabled": True}},
        }
        (workspace / ".mcp.json").write_text(json.dumps(mcp_config))

        manager = ConfigManager(workspace_dir=workspace)
        config = manager.load_config()

        assert isinstance(config, MCPConfig)
        assert config.version == "1.0"
        assert config.ai.provider == "claude"
        assert config.runner.enabled is True
        assert "gmail" in config.sources

    def test_loads_mcp_json_from_current_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should prioritize .mcp.json from current working directory."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()
        cwd = tmp_path / "project"
        cwd.mkdir()

        # Create .mcp.json in both locations with different content
        workspace_mcp = {
            "version": "1.0",
            "runner": {"enabled": False},
        }
        (workspace / ".mcp.json").write_text(json.dumps(workspace_mcp))

        cwd_mcp = {
            "version": "1.0",
            "runner": {"enabled": True},
        }
        (cwd / ".mcp.json").write_text(json.dumps(cwd_mcp))

        # Change to the project directory
        monkeypatch.chdir(cwd)

        manager = ConfigManager(workspace_dir=workspace)
        config = manager.load_config()

        # Should load from current directory (cwd)
        assert isinstance(config, MCPConfig)
        assert config.runner.enabled is True  # From cwd, not workspace

    def test_falls_back_to_legacy_config_yaml(self, tmp_path: Path) -> None:
        """Should fall back to config.yaml if no .mcp.json exists."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()

        legacy_config = {
            "workspace_dir": str(workspace),
            "sources": {"slack": {"enabled": True}},
            "ai": {"project_id": "legacy-project"},
        }
        (workspace / "config.yaml").write_text(yaml.dump(legacy_config))

        manager = ConfigManager(workspace_dir=workspace)
        config = manager.load_config()

        # Should load legacy config
        assert isinstance(config, AppConfig)
        assert "slack" in config.sources

    def test_returns_defaults_when_no_config_exists(self, tmp_path: Path) -> None:
        """Should return default MCPConfig when no configuration exists."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()

        manager = ConfigManager(workspace_dir=workspace)
        config = manager.load_config()

        assert isinstance(config, MCPConfig)
        assert config.version == "1.0"
        assert config.sources == {}

    def test_expands_environment_variables(self, tmp_path: Path) -> None:
        """Should expand ${VAR} references in .mcp.json."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()

        os.environ["TEST_API_KEY"] = "sk-test-123"
        os.environ["TEST_PROJECT_ID"] = "my-project"

        mcp_config = {
            "version": "1.0",
            "ai": {
                "provider": "claude",
                "claude": {"api_key": "${TEST_API_KEY}"},
            },
            "sources": {
                "gmail": {
                    "credentials_file": "${TEST_PROJECT_ID}/creds.json"
                }
            },
        }
        (workspace / ".mcp.json").write_text(json.dumps(mcp_config))

        manager = ConfigManager(workspace_dir=workspace)
        config = manager.load_config()

        assert config.ai.claude.api_key == "sk-test-123"
        assert config.sources["gmail"]["credentials_file"] == "my-project/creds.json"

        # Cleanup
        del os.environ["TEST_API_KEY"]
        del os.environ["TEST_PROJECT_ID"]


class TestMCPConfigSaving:
    """Tests for saving .mcp.json configuration."""

    def test_saves_mcp_config_to_workspace(self, tmp_path: Path) -> None:
        """Should save MCPConfig to workspace directory."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()

        manager = ConfigManager(workspace_dir=workspace)
        config = MCPConfig(
            ai={"provider": "vertex"},
            runner={"enabled": True, "interval_minutes": 10},
            sources={"slack": {"enabled": True}},
        )

        manager.save_config(config)

        # Verify file exists and content is correct
        mcp_path = workspace / ".mcp.json"
        assert mcp_path.exists()

        saved_data = json.loads(mcp_path.read_text())
        assert saved_data["ai"]["provider"] == "vertex"
        assert saved_data["runner"]["enabled"] is True
        assert saved_data["runner"]["interval_minutes"] == 10

    def test_save_preserves_structure(self, tmp_path: Path) -> None:
        """Should preserve nested structure when saving."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()

        manager = ConfigManager(workspace_dir=workspace)
        config = MCPConfig(
            mcp_servers={
                "devassist": {
                    "command": "devassist",
                    "args": ["--config", "test.json"],
                    "env": {"VAR": "value"},
                }
            }
        )

        manager.save_config(config)

        mcp_path = workspace / ".mcp.json"
        saved_data = json.loads(mcp_path.read_text())

        assert "devassist" in saved_data["mcp_servers"]
        assert saved_data["mcp_servers"]["devassist"]["command"] == "devassist"
        assert saved_data["mcp_servers"]["devassist"]["args"] == ["--config", "test.json"]
        assert saved_data["mcp_servers"]["devassist"]["env"] == {"VAR": "value"}


class TestConfigManagerBackwardCompatibility:
    """Tests for backward compatibility with existing code."""

    def test_get_source_config_works_with_mcp(self, tmp_path: Path) -> None:
        """Should retrieve source config from MCPConfig."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()

        mcp_config = {
            "version": "1.0",
            "sources": {
                "gmail": {"enabled": True, "credentials_file": "/path/to/creds"}
            },
        }
        (workspace / ".mcp.json").write_text(json.dumps(mcp_config))

        manager = ConfigManager(workspace_dir=workspace)
        source_config = manager.get_source_config("gmail")

        assert source_config is not None
        assert source_config["enabled"] is True
        assert source_config["credentials_file"] == "/path/to/creds"

    def test_set_source_config_works_with_mcp(self, tmp_path: Path) -> None:
        """Should set source config in MCPConfig."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()

        (workspace / ".mcp.json").write_text(json.dumps({"version": "1.0"}))

        manager = ConfigManager(workspace_dir=workspace)
        manager.set_source_config("slack", {"enabled": True, "bot_token": "xoxb-test"})

        # Reload and verify
        config = manager.load_config()
        assert "slack" in config.sources
        assert config.sources["slack"]["bot_token"] == "xoxb-test"

    def test_remove_source_config_works_with_mcp(self, tmp_path: Path) -> None:
        """Should remove source config from MCPConfig."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()

        mcp_config = {
            "version": "1.0",
            "sources": {
                "gmail": {"enabled": True},
                "slack": {"enabled": True},
            },
        }
        (workspace / ".mcp.json").write_text(json.dumps(mcp_config))

        manager = ConfigManager(workspace_dir=workspace)
        result = manager.remove_source_config("gmail")

        assert result is True

        # Reload and verify
        config = manager.load_config()
        assert "gmail" not in config.sources
        assert "slack" in config.sources  # Other source still exists

    def test_list_sources_works_with_mcp(self, tmp_path: Path) -> None:
        """Should list sources from MCPConfig."""
        workspace = tmp_path / ".devassist"
        workspace.mkdir()

        mcp_config = {
            "version": "1.0",
            "sources": {
                "gmail": {"enabled": True},
                "slack": {"enabled": True},
                "jira": {"enabled": False},
            },
        }
        (workspace / ".mcp.json").write_text(json.dumps(mcp_config))

        manager = ConfigManager(workspace_dir=workspace)
        sources = manager.list_sources()

        assert set(sources) == {"gmail", "slack", "jira"}
