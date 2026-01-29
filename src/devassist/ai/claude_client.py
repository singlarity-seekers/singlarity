"""Claude Agent SDK client for DevAssist.

Manages Claude sessions and API calls using the Claude Agent SDK.
Supports both stateful session management and simple query execution.
Includes file-based session persistence for daemon use cases.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import AssistantMessage, TextBlock

from devassist.models.config import ClientConfig
from devassist.models.mcp_config import McpServerConfig
from devassist.resources import get_mcp_servers_config

logger = logging.getLogger(__name__)


# Session persistence
SESSIONS_DIR = "sessions"
CURRENT_SESSION_FILE = "current-session-id"


@dataclass
class ClaudeSession:
    """Represents a Claude conversation session."""

    session_id: str
    created_at: datetime
    last_used: datetime
    resources: list[str]
    turns: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize session to dictionary.

        Returns:
            Dictionary representation of session.
        """
        # Don't serialize sdk_client in metadata
        safe_metadata = {k: v for k, v in self.metadata.items() if k != "sdk_client"}
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat(),
            "resources": self.resources,
            "turns": self.turns,
            "metadata": safe_metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClaudeSession":
        """Deserialize session from dictionary.

        Args:
            data: Dictionary containing session data.

        Returns:
            ClaudeSession instance.
        """
        return cls(
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_used=datetime.fromisoformat(data["last_used"]),
            resources=data["resources"],
            turns=data.get("turns", 0),
            metadata=data.get("metadata", {}),
        )


class ClaudeClient:
    """Client for interacting with Claude via the Agent SDK.

    Manages sessions, MCP server configuration, and API calls.

    Session Management:
    - Uses file-based persistence for daemon/background use cases
    - Sessions survive process restarts
    - Also maintains in-memory store for current process
    """

    # Static session store shared across all ClaudeClient instances
    _session_store: ClassVar[dict[str, ClaudeSession]] = {}

    def __init__(
        self,
        config: ClientConfig | None = None,
        workspace_dir: Path | str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        """Initialize ClaudeClient.

        Args:
            config: Application configuration.
            workspace_dir: Path to workspace directory for session persistence.
            system_prompt: Optional system prompt override.
        """
        self.config = config or ClientConfig()

        if workspace_dir is None:
            workspace_dir = Path.home() / ".devassist"
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        self._system_prompt_override = system_prompt

        # Ensure sessions directory exists
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        # Load all persisted sessions into memory
        self._load_all_sessions()

        # Load current session if available
        self.session = self._get_current_session()

    @property
    def sessions_dir(self) -> Path:
        """Get the sessions directory path."""
        return self.workspace_dir / SESSIONS_DIR

    @property
    def current_session_file(self) -> Path:
        """Get the current session pointer file path."""
        return self.workspace_dir / CURRENT_SESSION_FILE

    @property
    def effective_system_prompt(self) -> str:
        """Get the effective system prompt."""
        if self._system_prompt_override:
            return self._system_prompt_override
        return self.config.resolved_system_prompt

    def _load_all_sessions(self) -> None:
        """Load all sessions from the sessions directory into memory."""
        if not self.sessions_dir.exists():
            return

        for session_file in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(session_file.read_text())
                session = ClaudeSession.from_dict(data)
                ClaudeClient._session_store[session.session_id] = session
                logger.debug(f"Loaded session: {session.session_id}")
            except Exception as e:
                logger.warning(f"Failed to load session from {session_file}: {e}")

        logger.info(f"Loaded {len(ClaudeClient._session_store)} sessions from disk")

    def _get_current_session(self) -> ClaudeSession | None:
        """Get the current session from the pointer file.

        Returns:
            ClaudeSession or None if no current session.
        """
        if not self.current_session_file.exists():
            return None

        try:
            session_id = self.current_session_file.read_text().strip()
            session = ClaudeClient._session_store.get(session_id)
            if session:
                logger.info(f"Current session: {session_id}")
            return session
        except Exception as e:
            logger.warning(f"Failed to read current session: {e}")
            return None

    def _set_current_session(self, session_id: str) -> None:
        """Set the current session pointer.

        Args:
            session_id: Session ID to set as current.
        """
        try:
            self.current_session_file.write_text(session_id)
            logger.debug(f"Set current session: {session_id}")
        except Exception as e:
            logger.error(f"Failed to set current session: {e}")

    def _save_session_to_file(self, session: ClaudeSession) -> None:
        """Save session to the sessions directory.

        Args:
            session: Session to save.
        """
        try:
            # Use a safe filename (replace special chars)
            safe_id = session.session_id.replace("/", "_").replace("\\", "_")
            session_file = self.sessions_dir / f"{safe_id}.json"
            session_file.write_text(json.dumps(session.to_dict(), indent=2))
            logger.debug(f"Saved session to file: {session.session_id}")
        except Exception as e:
            logger.error(f"Failed to save session to file: {e}")

    def _get_mcp_servers_config(self, resources: list[str] | None = None) -> dict[str, Any]:
        """Get MCP servers configuration for specified resources.

        Args:
            resources: List of resource names (gmail, slack, jira, github).
                      If None, returns all configured sources.

        Returns:
            Dictionary of MCP server configurations with environment variables resolved.
        """
        # Load raw MCP config from JSON
        raw_mcp_config = get_mcp_servers_config()

        if not raw_mcp_config:
            logger.debug("No MCP servers configured")
            return {}

        # Determine which sources to include
        enabled_sources = {source.value for source in self.config.enabled_sources}
        if resources:
            target_sources = enabled_sources.intersection(set(resources))
        else:
            target_sources = enabled_sources

        # Build resolved configuration using McpServerConfig
        resolved_config = {}
        for server_name in target_sources:
            if server_name not in raw_mcp_config:
                logger.debug(f"MCP config not found for server: {server_name}")
                continue

            try:
                # Create McpServerConfig directly from JSON - field validator will resolve env vars
                raw_config = raw_mcp_config[server_name]
                server_config = McpServerConfig(**raw_config)
                # Convert back to dict for Claude SDK
                resolved_config[server_name] = server_config.model_dump()
            except Exception as e:
                logger.warning(f"Failed to configure MCP server {server_name}: {e}")

        logger.debug(f"Resolved MCP config for {len(resolved_config)} servers: {list(resolved_config.keys())}")
        return resolved_config

    def create_session(self, sdk_session_id: str | None = None) -> ClaudeSession:
        """Create a new Claude session.

        Args:
            sdk_session_id: Optional SDK session ID from Claude Agent SDK.
                           If None, a placeholder ID is used until first API call.

        Returns:
            ClaudeSession object with session ID.
        """
        # Use SDK session ID if provided, otherwise create placeholder
        # The placeholder will be replaced after the first successful API call
        if sdk_session_id:
            session_id = sdk_session_id
        else:
            session_id = f"pending-{uuid.uuid4().hex[:12]}"

        # Create session object
        session = ClaudeSession(
            session_id=session_id,
            created_at=datetime.now(),
            last_used=datetime.now(),
            resources=[source.value for source in self.config.enabled_sources],
            metadata={"output_format": self.config.output_format},
        )

        # Store session in memory and file
        ClaudeClient._session_store[session_id] = session
        self._save_session_to_file(session)
        self._set_current_session(session_id)

        logger.info(f"Created Claude session: {session_id}")
        return session

    async def execute_prompt(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """Execute a prompt with optional context.

        Uses the simpler query() function for stateless execution with session resumption.
        This is ideal for daemon/background use cases.

        Args:
            prompt: The user's prompt/instruction.
            context: Optional dictionary of context data.
            system_prompt: Optional system prompt override.

        Returns:
            AI-generated response string.
        """
        # Build full prompt with context if provided
        if context:
            context_json = json.dumps(context, indent=2, default=str)
            full_prompt = f"{prompt}\n\nContext:\n{context_json}"
        else:
            full_prompt = prompt

        # Build options
        effective_system_prompt = system_prompt or self.effective_system_prompt

        # Get MCP servers config (may be empty if not configured)
        mcp_servers = self._get_mcp_servers_config()

        # Only resume if we have a valid SDK session ID (not a pending one)
        resume_id = None
        if self.session and not self.session.session_id.startswith("pending-"):
            resume_id = self.session.session_id

        options = ClaudeAgentOptions(
            system_prompt=effective_system_prompt,
            permission_mode=self.config.permission_mode,
            resume=resume_id,
            mcp_servers=mcp_servers if mcp_servers else None,
        )

        # Execute query
        response_text = ""
        new_session_id = None

        try:
            async for message in query(prompt=full_prompt, options=options):
                # Capture session ID from any message that has it
                if hasattr(message, "session_id") and message.session_id:
                    new_session_id = message.session_id

                # Extract text content from assistant messages
                if isinstance(message, AssistantMessage) and message.content:
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            response_text += block.text

            # Update session with new session ID if provided
            if new_session_id and self.session:
                old_session_id = self.session.session_id
                if new_session_id != old_session_id:
                    # Remove old pending session from store and disk
                    if old_session_id.startswith("pending-"):
                        ClaudeClient._session_store.pop(old_session_id, None)
                        self.delete_session(old_session_id)
                    # Update to real SDK session ID
                    self.session.session_id = new_session_id
                    logger.info(f"Updated session ID: {old_session_id} -> {new_session_id}")
                self.session.last_used = datetime.now()
                self.session.turns += 1
                ClaudeClient._session_store[self.session.session_id] = self.session
                self._save_session_to_file(self.session)
                self._set_current_session(self.session.session_id)

        except Exception as e:
            logger.error(f"Error executing prompt: {e}", exc_info=True)
            raise

        return response_text

    def clear_session(self) -> None:
        """Clear the current session pointer (session data is preserved)."""
        if self.session:
            logger.info(f"Cleared current session: {self.session.session_id}")
            self.session = None

        # Clear the current session pointer file
        if self.current_session_file.exists():
            self.current_session_file.unlink()

    def delete_session(self, session_id: str) -> bool:
        """Delete a session permanently.

        Args:
            session_id: Session ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        # Remove from memory store
        if session_id in ClaudeClient._session_store:
            del ClaudeClient._session_store[session_id]

        # Remove session file
        safe_id = session_id.replace("/", "_").replace("\\", "_")
        session_file = self.sessions_dir / f"{safe_id}.json"
        if session_file.exists():
            session_file.unlink()
            logger.info(f"Deleted session: {session_id}")
            return True

        return False

    def list_sessions(self) -> list[ClaudeSession]:
        """List all active sessions.

        Returns:
            List of ClaudeSession objects.
        """
        return list(ClaudeClient._session_store.values())

    def get_latest_session(self) -> ClaudeSession | None:
        """Get the most recently used session.

        Returns:
            ClaudeSession object or None if no sessions exist.
        """
        if not ClaudeClient._session_store:
            return None

        return max(ClaudeClient._session_store.values(), key=lambda s: s.last_used)

    @classmethod
    def get_session_count(cls) -> int:
        """Get total number of sessions in the store.

        Returns:
            Number of sessions currently stored.
        """
        return len(cls._session_store)

    @classmethod
    def get_session_by_id(cls, session_id: str) -> ClaudeSession | None:
        """Get a session by ID from the static store.

        Args:
            session_id: Session ID to retrieve.

        Returns:
            ClaudeSession object or None if not found.
        """
        return cls._session_store.get(session_id)

    @classmethod
    def clear_all_sessions(cls, workspace_dir: Path | None = None) -> None:
        """Clear all sessions from store and disk.

        WARNING: This removes all sessions for all ClaudeClient instances.

        Args:
            workspace_dir: Workspace directory. Defaults to ~/.devassist.
        """
        count = len(cls._session_store)
        cls._session_store.clear()

        # Also delete session files from disk
        if workspace_dir is None:
            workspace_dir = Path.home() / ".devassist"
        sessions_dir = workspace_dir / SESSIONS_DIR
        if sessions_dir.exists():
            for session_file in sessions_dir.glob("*.json"):
                session_file.unlink()

        # Clear current session pointer
        current_file = workspace_dir / CURRENT_SESSION_FILE
        if current_file.exists():
            current_file.unlink()

        logger.info(f"Cleared all {count} sessions from store and disk")

    @classmethod
    def get_session_ids(cls) -> list[str]:
        """Get all session IDs from the static store.

        Returns:
            List of session IDs.
        """
        return list(cls._session_store.keys())

    async def test_connection(self) -> bool:
        """Test connection to Claude Agent SDK.

        Returns:
            True if connection is successful, False otherwise.
        """
        try:
            response = await self.execute_prompt("Respond with 'OK'")
            return "OK" in response
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
