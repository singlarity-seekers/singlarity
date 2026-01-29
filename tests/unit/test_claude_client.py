"""Unit tests for ClaudeClient."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from devassist.ai.claude_client import ClaudeClient
from devassist.models.context import ContextItem, SourceType


class MockMessage:
    """Mock Anthropic message response."""

    def __init__(self, text: str):
        self.content = [MagicMock(text=text)]


class TestClaudeClient:
    """Tests for ClaudeClient with API key mode."""

    @pytest.fixture(autouse=True)
    def disable_vertex_ai(self, monkeypatch):
        """Ensure Vertex AI mode is disabled for API key tests."""
        monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)

    @pytest.fixture
    def mock_anthropic(self):
        """Mock Anthropic client."""
        with patch("devassist.ai.claude_client.Anthropic") as mock:
            yield mock

    @pytest.fixture
    def client(self) -> ClaudeClient:
        """Create ClaudeClient for testing."""
        return ClaudeClient(
            api_key="sk-ant-test123",
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
        )

    def test_init_with_defaults(self) -> None:
        """Should initialize with default values."""
        client = ClaudeClient(api_key="sk-ant-test")
        assert client.api_key == "sk-ant-test"
        assert client.model == "claude-sonnet-4-5-20250929"
        assert client.max_tokens == 4096
        assert client.temperature == 0.7
        assert client.max_retries == 3

    def test_init_with_custom_values(self) -> None:
        """Should accept custom values."""
        client = ClaudeClient(
            api_key="sk-ant-custom",
            model="claude-opus-4",
            max_tokens=8192,
            temperature=0.5,
            max_retries=5,
        )
        assert client.api_key == "sk-ant-custom"
        assert client.model == "claude-opus-4"
        assert client.max_tokens == 8192
        assert client.temperature == 0.5
        assert client.max_retries == 5

    @pytest.mark.asyncio
    async def test_summarize_with_items(self, client: ClaudeClient, mock_anthropic) -> None:
        """Should generate summary from context items."""
        items = [
            ContextItem(
                id="item1",
                source_id="gmail_123",
                source_type=SourceType.GMAIL,
                title="Meeting Reminder",
                content="Team standup at 10am",
                timestamp=datetime(2026, 1, 28, 9, 0, 0),
                author="alice@example.com",
                url="https://mail.google.com/123",
                relevance_score=0.9,
            ),
            ContextItem(
                id="item2",
                source_id="slack_456",
                source_type=SourceType.SLACK,
                title="Deploy notification",
                content="Production deploy successful",
                timestamp=datetime(2026, 1, 28, 8, 30, 0),
                author="deploy-bot",
                url="https://slack.com/456",
                relevance_score=0.7,
            ),
        ]

        # Mock the API response (sync, not async)
        mock_client = mock_anthropic.return_value
        mock_client.messages.create = Mock(
            return_value=MockMessage("Summary: Meeting at 10am, deploy successful.")
        )

        result = await client.summarize(items)

        assert isinstance(result, str)
        assert "Summary" in result
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_with_empty_list(self, client: ClaudeClient) -> None:
        """Should return default message for empty list."""
        result = await client.summarize([])
        assert isinstance(result, str)
        assert len(result) > 0
        assert "no" in result.lower() or "nothing" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_prompt(self, client: ClaudeClient, mock_anthropic) -> None:
        """Should execute custom prompt with context."""
        prompt = "Summarize urgent items"
        context = {"items": ["item1", "item2"], "count": 2}

        mock_client = mock_anthropic.return_value
        mock_client.messages.create = Mock(
            return_value=MockMessage("You have 2 urgent items requiring attention.")
        )

        result = await client.execute_prompt(prompt, context)

        assert isinstance(result, str)
        assert "urgent" in result.lower()
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_test_connection_success(self, client: ClaudeClient, mock_anthropic) -> None:
        """Should return True when connection is successful."""
        mock_client = mock_anthropic.return_value
        mock_client.messages.create = Mock(
            return_value=MockMessage("Connection test successful")
        )

        result = await client.test_connection()

        assert result is True
        mock_client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_test_connection_failure(self, client: ClaudeClient, mock_anthropic) -> None:
        """Should return False when connection fails."""
        mock_client = mock_anthropic.return_value
        mock_client.messages.create = Mock(side_effect=Exception("API Error"))

        result = await client.test_connection()

        assert result is False

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, client: ClaudeClient, mock_anthropic) -> None:
        """Should retry on failure with exponential backoff."""
        mock_client = mock_anthropic.return_value

        # Fail twice, succeed on third attempt
        mock_client.messages.create = Mock(
            side_effect=[
                Exception("Rate limit"),
                Exception("Timeout"),
                MockMessage("Success on third try"),
            ]
        )

        result = await client.execute_prompt("test", {})

        assert result == "Success on third try"
        assert mock_client.messages.create.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self, client: ClaudeClient, mock_anthropic) -> None:
        """Should raise exception after max retries exceeded."""
        mock_client = mock_anthropic.return_value
        mock_client.messages.create = Mock(side_effect=Exception("Persistent error"))

        with pytest.raises(Exception, match="Persistent error"):
            await client.execute_prompt("test", {})

        # Should retry 3 times (initial + 2 retries)
        assert mock_client.messages.create.call_count == 3

    @pytest.mark.asyncio
    async def test_formats_items_correctly(self, client: ClaudeClient, mock_anthropic) -> None:
        """Should format context items correctly in prompts."""
        items = [
            ContextItem(
                id="item1",
                source_id="jira_bug123",
                source_type=SourceType.JIRA,
                title="BUG-123: Fix login issue",
                content="Users cannot log in with SSO",
                timestamp=datetime(2026, 1, 28, 10, 0, 0),
                author="john.doe@example.com",
                url="https://jira.example.com/BUG-123",
                relevance_score=0.95,
            )
        ]

        mock_client = mock_anthropic.return_value
        mock_client.messages.create = Mock(return_value=MockMessage("Formatted"))

        await client.summarize(items)

        # Verify the call includes formatted item data
        call_args = mock_client.messages.create.call_args
        messages = call_args.kwargs.get("messages", [])
        assert len(messages) > 0
        prompt_text = messages[0]["content"]
        assert "JIRA" in prompt_text
        assert "BUG-123" in prompt_text
        assert "john.doe@example.com" in prompt_text

    def test_raises_without_api_key(self) -> None:
        """Should raise error if API key is not provided and not using Vertex AI."""
        with pytest.raises(ValueError, match="api_key"):
            ClaudeClient(api_key=None)  # type: ignore


class TestClaudeClientVertexAI:
    """Tests for ClaudeClient with Vertex AI."""

    def test_init_with_vertex_ai_env_vars(self, monkeypatch) -> None:
        """Should initialize with Vertex AI when env vars are set."""
        monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
        monkeypatch.setenv("ANTHROPIC_VERTEX_PROJECT_ID", "my-gcp-project")
        monkeypatch.setenv("CLOUD_ML_REGION", "us-east5")

        client = ClaudeClient()

        assert client.use_vertex is True
        assert client.project_id == "my-gcp-project"
        assert client.region == "us-east5"
        assert client.api_key is None

    def test_init_with_vertex_ai_params(self, monkeypatch) -> None:
        """Should accept project_id and region as parameters."""
        monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")

        client = ClaudeClient(
            project_id="param-project",
            region="us-central1",
        )

        assert client.use_vertex is True
        assert client.project_id == "param-project"
        assert client.region == "us-central1"

    def test_vertex_ai_requires_project_id(self, monkeypatch) -> None:
        """Should raise error if Vertex AI mode but no project_id."""
        monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
        monkeypatch.delenv("ANTHROPIC_VERTEX_PROJECT_ID", raising=False)

        with pytest.raises(ValueError, match="project_id"):
            ClaudeClient()

    def test_vertex_ai_default_region(self, monkeypatch) -> None:
        """Should use default region if not specified."""
        monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
        monkeypatch.setenv("ANTHROPIC_VERTEX_PROJECT_ID", "my-project")
        monkeypatch.delenv("CLOUD_ML_REGION", raising=False)

        client = ClaudeClient()

        assert client.region == "us-east5"

    @pytest.mark.asyncio
    async def test_vertex_ai_creates_correct_client(self, monkeypatch) -> None:
        """Should create AnthropicVertex client in Vertex AI mode."""
        monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
        monkeypatch.setenv("ANTHROPIC_VERTEX_PROJECT_ID", "my-project")

        with patch("devassist.ai.claude_client.AnthropicVertex") as mock_vertex:
            client = ClaudeClient()
            _ = client._get_client()

            mock_vertex.assert_called_once_with(
                project_id="my-project",
                region="us-east5",
            )

    def test_api_key_mode_when_vertex_not_set(self, monkeypatch) -> None:
        """Should use API key mode when CLAUDE_CODE_USE_VERTEX is not set."""
        monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)

        client = ClaudeClient(api_key="sk-ant-test")

        assert client.use_vertex is False
        assert client.api_key == "sk-ant-test"
        assert client.project_id is None
