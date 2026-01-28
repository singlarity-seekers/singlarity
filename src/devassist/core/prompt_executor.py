"""Prompt executor for DevAssist.

Orchestrates prompt execution with context aggregation and AI generation.
"""

from datetime import datetime, timedelta
from time import time
from typing import Any

from devassist.ai.prompt_registry import PromptRegistry
from devassist.ai.vertex_client import VertexAIClient
from devassist.core.aggregator import ContextAggregator
from devassist.core.config_manager import ConfigManager
from devassist.core.ranker import RelevanceRanker
from devassist.models.context import ContextItem
from devassist.models.prompt import PromptExecutionResult, PromptTemplate


class PromptExecutor:
    """Executes prompt templates with context aggregation."""

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        aggregator: ContextAggregator | None = None,
        ranker: RelevanceRanker | None = None,
    ) -> None:
        """Initialize PromptExecutor.

        Args:
            config_manager: Configuration manager.
            aggregator: Context aggregator.
            ranker: Relevance ranker.
        """
        self._config_manager = config_manager or ConfigManager()
        self._aggregator = aggregator or ContextAggregator(self._config_manager)

        # Load preferences for ranker
        config = self._config_manager.load_config()
        priority_keywords = config.preferences.priority_keywords
        self._ranker = ranker or RelevanceRanker(priority_keywords=priority_keywords)

        # Base AI client config (used for creating clients per-prompt)
        self._base_ai_config = {
            "api_key": config.ai.api_key,
            "project_id": config.ai.project_id,
            "location": config.ai.location,
            "model": config.ai.model,
            "max_retries": config.ai.max_retries,
            "timeout_seconds": config.ai.timeout_seconds,
        }

    async def execute(
        self,
        prompt_id: str,
        refresh: bool = False,
        context_kwargs: dict[str, Any] | None = None,
    ) -> PromptExecutionResult:
        """Execute a prompt template by ID.

        Args:
            prompt_id: Prompt template ID to execute.
            refresh: Bypass cache and fetch fresh data.
            context_kwargs: Additional kwargs for prompt template formatting
                           (e.g., {"meeting_topic": "Sprint Planning"}).

        Returns:
            PromptExecutionResult with generated text and metadata.

        Raises:
            ValueError: If prompt_id is not registered.
        """
        start_time = time()

        # Get prompt template
        template = PromptRegistry.get(prompt_id)

        # Fetch context items with time filtering
        items = await self._fetch_context(template, refresh)

        # Rank items by relevance
        ranked_items = self._ranker.rank(items)

        # Generate AI response with prompt-specific config
        generated_text = await self._generate_with_template(
            template, ranked_items, context_kwargs
        )

        # Build result
        execution_time = time() - start_time
        return PromptExecutionResult(
            prompt_id=prompt_id,
            generated_text=generated_text,
            format=template.output_format,
            context_items_count=len(ranked_items),
            execution_time_seconds=execution_time,
            generated_at=datetime.now(),
            sources_used=list(set(item.source_type.value for item in ranked_items)),
            sources_failed=self._aggregator.failed_sources,
        )

    async def execute_custom(
        self,
        user_prompt: str,
        include_context: bool = True,
        time_window_hours: int = 24,
        temperature: float = 0.5,
    ) -> PromptExecutionResult:
        """Execute a custom ad-hoc prompt.

        Args:
            user_prompt: Custom prompt text from user.
            include_context: Whether to include aggregated context.
            time_window_hours: Context time window in hours.
            temperature: AI temperature for generation.

        Returns:
            PromptExecutionResult.
        """
        start_time = time()

        items = []
        if include_context:
            # Fetch context with time filter
            since = datetime.now() - timedelta(hours=time_window_hours)
            items = await self._aggregator.fetch_all(since=since)
            items = self._ranker.rank(items)

        # Build full prompt with optional context
        if items:
            context_text = self._format_context(items)
            full_prompt = f"Context:\n{context_text}\n\nQuestion: {user_prompt}"
        else:
            full_prompt = user_prompt

        # Create AI client
        ai_client = VertexAIClient(**self._base_ai_config)

        # Generate response
        try:
            generated_text = await ai_client._generate_content_with_config(
                prompt=full_prompt,
                system_instruction="You are a helpful assistant.",
                temperature=temperature,
                max_output_tokens=2048,
            )
        except Exception as e:
            generated_text = f"Error generating response: {e}"

        execution_time = time() - start_time
        return PromptExecutionResult(
            prompt_id="custom",
            generated_text=generated_text,
            format="text",
            context_items_count=len(items),
            execution_time_seconds=execution_time,
            generated_at=datetime.now(),
            sources_used=list(set(item.source_type.value for item in items)),
            sources_failed=self._aggregator.failed_sources,
        )

    async def _fetch_context(
        self,
        template: PromptTemplate,
        refresh: bool,
    ) -> list[ContextItem]:
        """Fetch context items filtered by template specifications.

        Args:
            template: Prompt template with filter specifications.
            refresh: Whether to bypass cache.

        Returns:
            List of filtered context items.
        """
        # Calculate time cutoff if specified
        since = None
        if template.time_window_hours is not None:
            since = datetime.now() - timedelta(hours=template.time_window_hours)

        # Fetch all items with time filter
        items = await self._aggregator.fetch_all(since=since)

        # Apply source filter if specified
        if template.source_filter:
            items = [
                item
                for item in items
                if item.source_type.value in template.source_filter
            ]

        return items

    async def _generate_with_template(
        self,
        template: PromptTemplate,
        items: list[ContextItem],
        context_kwargs: dict[str, Any] | None = None,
    ) -> str:
        """Generate AI response using template configuration.

        Args:
            template: Prompt template.
            items: Ranked context items.
            context_kwargs: Additional context variables for template.

        Returns:
            Generated text.
        """
        # Build context text from items
        context_text = self._format_context(items)

        # Prepare template kwargs
        template_kwargs = {"context": context_text}
        if context_kwargs:
            template_kwargs.update(context_kwargs)

        # Render user prompt from template
        try:
            user_prompt = template.user_prompt_template.format(**template_kwargs)
        except KeyError as e:
            missing_key = str(e).strip("'")
            return f"Error: Missing required context variable '{missing_key}' for this prompt."

        # Create AI client
        ai_client = VertexAIClient(**self._base_ai_config)

        # Generate with template-specific settings
        try:
            return await ai_client._generate_content_with_config(
                prompt=user_prompt,
                system_instruction=template.system_prompt,
                temperature=template.temperature,
                max_output_tokens=template.max_output_tokens,
            )
        except Exception as e:
            return self._generate_fallback_response(items, str(e))

    def _format_context(self, items: list[ContextItem]) -> str:
        """Format context items as text.

        Args:
            items: Context items to format.

        Returns:
            Formatted context string.
        """
        if not items:
            return "No recent context items available."

        # Sort by relevance (highest first)
        sorted_items = sorted(items, key=lambda x: x.relevance_score, reverse=True)

        parts = []
        for item in sorted_items:
            item_text = f"[{item.source_type.value.upper()}] {item.title}\n"
            if item.author:
                item_text += f"From: {item.author}\n"
            item_text += f"Time: {item.timestamp.strftime('%Y-%m-%d %H:%M')}\n"
            if item.content:
                content = item.content[:500]
                if len(item.content) > 500:
                    content += "..."
                item_text += f"Content: {content}\n"
            if item.url:
                item_text += f"Link: {item.url}\n"
            parts.append(item_text)

        return "\n\n".join(parts)

    def _generate_fallback_response(self, items: list[ContextItem], error_msg: str) -> str:
        """Generate fallback response when AI fails.

        Args:
            items: Context items.
            error_msg: Error message from AI failure.

        Returns:
            Fallback message.
        """
        if not items:
            return "No context items available and AI generation failed."

        # Count by source
        source_counts: dict[str, int] = {}
        for item in items:
            name = item.source_type.value.title()
            source_counts[name] = source_counts.get(name, 0) + 1

        counts_str = ", ".join(f"{count} from {name}" for name, count in source_counts.items())

        return (
            f"AI generation unavailable. Manual review recommended.\n\n"
            f"You have {len(items)} items to review: {counts_str}.\n\n"
            f"(AI error: {error_msg[:100]})"
        )
