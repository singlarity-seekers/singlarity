"""Claude Agent SDK client for DevAssist.

Uses the Claude Agent SDK for session-based conversations with automatic
history management. Sessions persist across runs, allowing Claude to
remember previous interactions.
"""

import json
import logging
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import AssistantMessage, TextBlock

logger = logging.getLogger(__name__)


class AgentClient:
    """Client using Claude Agent SDK with session management.

    Features:
    - Automatic session persistence (handled by Agent SDK)
    - Conversation history maintained across runs
    - Session can be resumed or cleared
    """

    SESSION_ID_FILE = "runner-session-id"

    def __init__(
        self,
        workspace_dir: Path | str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        """Initialize AgentClient.

        Args:
            workspace_dir: Path to workspace directory for session storage.
            system_prompt: System prompt for the agent.
        """
        if workspace_dir is None:
            workspace_dir = Path.home() / ".devassist"
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        self.system_prompt = system_prompt
        self.session_id: str | None = None

        # Load existing session ID if available
        self._load_session_id()

    def _load_session_id(self) -> None:
        """Load session ID from file if it exists."""
        session_file = self.workspace_dir / self.SESSION_ID_FILE
        if session_file.exists():
            try:
                self.session_id = session_file.read_text().strip()
                logger.info(f"Loaded session ID: {self.session_id}")
            except Exception as e:
                logger.warning(f"Failed to load session ID: {e}")
                self.session_id = None

    def _save_session_id(self, session_id: str) -> None:
        """Save session ID to file.

        Args:
            session_id: The session ID to save.
        """
        session_file = self.workspace_dir / self.SESSION_ID_FILE
        try:
            session_file.write_text(session_id)
            self.session_id = session_id
            logger.info(f"Saved session ID: {session_id}")
        except Exception as e:
            logger.error(f"Failed to save session ID: {e}")

    def clear_session(self) -> None:
        """Clear the current session."""
        session_file = self.workspace_dir / self.SESSION_ID_FILE
        if session_file.exists():
            session_file.unlink()
            logger.info("Cleared session")
        self.session_id = None

    async def execute_prompt(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """Execute a prompt with optional context.

        Automatically resumes the previous session if available, maintaining
        full conversation history.

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
        effective_system_prompt = system_prompt or self.system_prompt
        options = ClaudeAgentOptions(
            system_prompt=effective_system_prompt,
            permission_mode="bypassPermissions",
            resume=self.session_id,  # Resume session if available
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

            # Save session ID for next run
            if new_session_id:
                self._save_session_id(new_session_id)

        except Exception as e:
            logger.error(f"Error executing prompt: {e}", exc_info=True)
            raise

        return response_text

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
