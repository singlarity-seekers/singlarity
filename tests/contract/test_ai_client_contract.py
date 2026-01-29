"""Contract tests for AI client implementations.

All AI clients (Claude, Vertex, etc.) must implement the BaseAIClient interface.
"""

from abc import ABC

import pytest

from devassist.ai.base_client import BaseAIClient
from devassist.models.context import ContextItem, SourceType


class AIClientContractTests(ABC):
    """Base contract test suite that all AI clients must pass.

    Subclass this and implement create_client() to test your AI client.
    """

    @pytest.fixture
    def client(self) -> BaseAIClient:
        """Create an AI client instance for testing.

        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement create_client()")

    @pytest.mark.asyncio
    async def test_implements_base_client(self, client: BaseAIClient) -> None:
        """Should implement BaseAIClient interface."""
        assert isinstance(client, BaseAIClient)

    @pytest.mark.asyncio
    async def test_has_summarize_method(self, client: BaseAIClient) -> None:
        """Should have summarize method."""
        assert hasattr(client, "summarize")
        assert callable(client.summarize)

    @pytest.mark.asyncio
    async def test_has_execute_prompt_method(self, client: BaseAIClient) -> None:
        """Should have execute_prompt method."""
        assert hasattr(client, "execute_prompt")
        assert callable(client.execute_prompt)

    @pytest.mark.asyncio
    async def test_has_test_connection_method(self, client: BaseAIClient) -> None:
        """Should have test_connection method."""
        assert hasattr(client, "test_connection")
        assert callable(client.test_connection)

    @pytest.mark.asyncio
    async def test_summarize_returns_string(self, client: BaseAIClient) -> None:
        """Summarize should return a string."""
        items = [
            ContextItem(
                source_type=SourceType.GMAIL,
                title="Test Email",
                content="Test content",
                timestamp="2026-01-28T10:00:00Z",
                url="https://mail.google.com/test",
                relevance_score=0.8,
            )
        ]

        # Mock the actual API call in subclass tests
        result = await client.summarize(items)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_summarize_handles_empty_list(self, client: BaseAIClient) -> None:
        """Summarize should handle empty item list gracefully."""
        result = await client.summarize([])
        assert isinstance(result, str)
        assert len(result) > 0  # Should return some default message

    @pytest.mark.asyncio
    async def test_execute_prompt_returns_string(self, client: BaseAIClient) -> None:
        """Execute prompt should return a string."""
        # Mock the actual API call in subclass tests
        result = await client.execute_prompt(
            prompt="Summarize this context",
            context={"key": "value"},
        )
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_test_connection_returns_bool(self, client: BaseAIClient) -> None:
        """Test connection should return a boolean."""
        result = await client.test_connection()
        assert isinstance(result, bool)
