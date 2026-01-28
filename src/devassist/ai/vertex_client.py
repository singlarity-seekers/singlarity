"""Vertex AI client for DevAssist.

Handles AI summarization and tool calling using Google Cloud Vertex AI (Gemini).
"""

import asyncio
import json
from typing import Any, Callable

from devassist.ai.prompts import NO_ITEMS_SUMMARY, build_summarization_prompt, get_system_prompt
from devassist.ai.tools import get_all_tools, get_tools_for_sources
from devassist.models.context import ContextItem

# Google Cloud AI imports - optional, checked at runtime
try:
    from google import genai
    from google.genai import types

    VERTEX_AI_AVAILABLE = True
except ImportError:
    VERTEX_AI_AVAILABLE = False
    genai = None  # type: ignore
    types = None  # type: ignore


class VertexAIClient:
    """Client for Vertex AI Gemini model interactions."""

    DEFAULT_MODEL = "gemini-2.5-flash"
    DEFAULT_LOCATION = "us-central1"
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 60
    DEFAULT_MAX_INPUT_TOKENS = 30000  # Conservative limit for context

    def __init__(
        self,
        api_key: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
        model: str | None = None,
        max_retries: int | None = None,
        timeout_seconds: int | None = None,
        max_input_tokens: int | None = None,
    ) -> None:
        """Initialize VertexAIClient.

        Args:
            api_key: Google AI API key (alternative to Vertex AI).
            project_id: GCP project ID (for Vertex AI).
            location: GCP region (for Vertex AI).
            model: Model name to use.
            max_retries: Maximum retry attempts.
            timeout_seconds: Request timeout.
            max_input_tokens: Maximum input tokens for context.
        """
        self.api_key = api_key
        self.project_id = project_id or ""
        self.location = location or self.DEFAULT_LOCATION
        self.model = model or self.DEFAULT_MODEL
        self.max_retries = max_retries if max_retries is not None else self.DEFAULT_MAX_RETRIES
        self.timeout_seconds = timeout_seconds or self.DEFAULT_TIMEOUT
        self.max_input_tokens = max_input_tokens or self.DEFAULT_MAX_INPUT_TOKENS

        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create the AI client.

        Uses Google AI API key if provided, otherwise falls back to Vertex AI.

        Returns:
            Configured genai client.

        Raises:
            RuntimeError: If AI libraries are not available.
        """
        if not VERTEX_AI_AVAILABLE:
            raise RuntimeError(
                "Google AI libraries not installed. Run: pip install google-genai"
            )

        if self._client is None:
            if self.api_key:
                # Use Google AI Studio with API key
                self._client = genai.Client(api_key=self.api_key)
            else:
                # Use Vertex AI with ADC
                self._client = genai.Client(
                    vertexai=True,
                    project=self.project_id,
                    location=self.location,
                )

        return self._client

    async def summarize(self, items: list[ContextItem]) -> str:
        """Generate a summary of context items.

        Args:
            items: List of context items to summarize.

        Returns:
            AI-generated summary string.

        Raises:
            Exception: If summarization fails after retries.
        """
        if not items:
            return NO_ITEMS_SUMMARY

        prompt = self._build_prompt(items)

        # Retry loop
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return await self._generate_content(prompt)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    await asyncio.sleep(2**attempt)

        if last_error:
            raise last_error
        raise RuntimeError("Summarization failed with unknown error")

    async def _generate_content(self, prompt: str) -> str:
        """Generate content using the AI model.

        Args:
            prompt: The prompt to send.

        Returns:
            Generated content string.
        """
        if not VERTEX_AI_AVAILABLE:
            # Fallback for testing without Vertex AI
            return "AI summarization unavailable. Please configure Vertex AI."

        client = self._get_client()

        # Run in thread pool since google-genai may be sync
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=get_system_prompt(),
                    temperature=0.3,  # Lower for more consistent outputs
                    max_output_tokens=1024,
                ),
            ),
        )

        return response.text

    def _build_prompt(self, items: list[ContextItem]) -> str:
        """Build the prompt from context items.

        Args:
            items: Context items to include in prompt.

        Returns:
            Formatted prompt string.
        """
        # Sort by relevance score (highest first)
        sorted_items = sorted(items, key=lambda x: x.relevance_score, reverse=True)

        # Build context text with token budget awareness
        context_parts: list[str] = []
        estimated_tokens = 0

        for item in sorted_items:
            item_text = self._format_item(item)
            # Rough token estimate: ~4 chars per token
            item_tokens = len(item_text) // 4

            if estimated_tokens + item_tokens > self.max_input_tokens:
                break

            context_parts.append(item_text)
            estimated_tokens += item_tokens

        context_text = "\n\n".join(context_parts)
        return build_summarization_prompt(context_text)

    def _format_item(self, item: ContextItem) -> str:
        """Format a single context item for the prompt.

        Args:
            item: Context item to format.

        Returns:
            Formatted string representation.
        """
        parts = [
            f"[{item.source_type.value.upper()}] {item.title}",
        ]

        if item.author:
            parts.append(f"From: {item.author}")

        parts.append(f"Time: {item.timestamp.strftime('%Y-%m-%d %H:%M')}")

        if item.content:
            # Truncate long content
            content = item.content[:500]
            if len(item.content) > 500:
                content += "..."
            parts.append(f"Content: {content}")

        if item.url:
            parts.append(f"Link: {item.url}")

        return "\n".join(parts)

    # ==================== Function Calling ====================

    async def chat_with_tools(
        self,
        message: str,
        tool_executor: Callable[[str, dict[str, Any]], Any],
        sources: list[str] | None = None,
        context_items: list[ContextItem] | None = None,
        max_tool_calls: int = 10,
    ) -> str:
        """Chat with the AI with function calling enabled.
        
        The AI can call tools to interact with context sources (Gmail, Slack, etc.)
        and will automatically execute them via the tool_executor callback.
        
        Args:
            message: User message/request.
            tool_executor: Async callback to execute tools. Takes (tool_name, args) -> result.
            sources: List of sources to enable tools for (gmail, slack, jira, github).
                     If None, all tools are available.
            context_items: Optional context items to include in the conversation.
            max_tool_calls: Maximum number of tool calls allowed in a single conversation.
            
        Returns:
            Final AI response after all tool calls are complete.
        """
        if not VERTEX_AI_AVAILABLE:
            return "AI with tool calling unavailable. Please configure Vertex AI."

        # Get tools for the specified sources
        if sources:
            tools = get_tools_for_sources(sources)
        else:
            tools = get_all_tools()

        if not tools:
            # No tools available, fall back to regular chat
            return await self._generate_content(message)

        # Build initial context
        context_text = ""
        if context_items:
            context_parts = [self._format_item(item) for item in context_items[:20]]
            context_text = "\n\n".join(context_parts)

        # Convert tools to Gemini format
        gemini_tools = self._convert_tools_to_gemini_format(tools)
        
        # Build conversation
        conversation: list[dict[str, Any]] = []
        
        # Add context and user message
        if context_text:
            user_content = f"Current context from your sources:\n\n{context_text}\n\n---\n\nUser request: {message}"
        else:
            user_content = message
            
        conversation.append({"role": "user", "parts": [{"text": user_content}]})

        # Tool calling loop
        tool_calls_made = 0
        
        while tool_calls_made < max_tool_calls:
            # Generate response with tools
            response = await self._generate_with_tools(conversation, gemini_tools)
            
            # Check if model wants to call a function
            function_calls = self._extract_function_calls(response)
            
            if not function_calls:
                # No more function calls, return the text response
                return self._extract_text_response(response)
            
            # Execute each function call
            tool_results = []
            for func_call in function_calls:
                tool_name = func_call["name"]
                tool_args = func_call.get("args", {})
                
                try:
                    result = await self._execute_tool(tool_executor, tool_name, tool_args)
                    tool_results.append({
                        "name": tool_name,
                        "response": {"result": result},
                    })
                except Exception as e:
                    tool_results.append({
                        "name": tool_name,
                        "response": {"error": str(e)},
                    })
                
                tool_calls_made += 1

            # Add model response and tool results to conversation
            conversation.append({
                "role": "model",
                "parts": response.candidates[0].content.parts,
            })
            
            # Add function responses
            function_response_parts = []
            for result in tool_results:
                function_response_parts.append({
                    "function_response": {
                        "name": result["name"],
                        "response": result["response"],
                    }
                })
            
            conversation.append({
                "role": "user",
                "parts": function_response_parts,
            })

        # Max tool calls reached
        return "I've reached the maximum number of tool calls. Here's what I found so far."

    def _convert_tools_to_gemini_format(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tool definitions to Gemini function declaration format.
        
        Args:
            tools: List of tool definitions.
            
        Returns:
            Gemini-formatted function declarations.
        """
        function_declarations = []
        
        for tool in tools:
            func_decl = {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
            }
            function_declarations.append(func_decl)
        
        return [{"function_declarations": function_declarations}]

    async def _generate_with_tools(
        self,
        conversation: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        """Generate response with function calling enabled.
        
        Args:
            conversation: Conversation history.
            tools: Tool definitions in Gemini format.
            
        Returns:
            Gemini response object.
        """
        client = self._get_client()
        
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=self.model,
                contents=conversation,
                config=types.GenerateContentConfig(
                    system_instruction=self._get_tool_system_prompt(),
                    temperature=0.2,
                    tools=tools,
                ),
            ),
        )
        
        return response

    def _get_tool_system_prompt(self) -> str:
        """Get system prompt for tool-enabled conversations."""
        return """You are a helpful developer assistant with access to various tools for managing emails, messages, issues, and more.

When the user asks you to do something, use the available tools to help them. You can:
- Search and read emails from Gmail
- Send emails and create drafts
- Search Slack messages and send messages
- Search and create JIRA issues
- Search GitHub issues and PRs

Be proactive in using tools to gather information before answering questions.
When you perform actions (like sending an email), confirm what you did.
If a tool call fails, explain what went wrong and suggest alternatives.

Always be helpful, concise, and action-oriented."""

    def _extract_function_calls(self, response: Any) -> list[dict[str, Any]]:
        """Extract function calls from Gemini response.
        
        Args:
            response: Gemini response object.
            
        Returns:
            List of function call dicts with name and args.
        """
        function_calls = []
        
        if not response.candidates:
            return function_calls
            
        for part in response.candidates[0].content.parts:
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                function_calls.append({
                    "name": fc.name,
                    "args": dict(fc.args) if fc.args else {},
                })
        
        return function_calls

    def _extract_text_response(self, response: Any) -> str:
        """Extract text response from Gemini response.
        
        Args:
            response: Gemini response object.
            
        Returns:
            Text content from the response.
        """
        if not response.candidates:
            return "No response generated."
            
        text_parts = []
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                text_parts.append(part.text)
        
        return "\n".join(text_parts) if text_parts else "No text response."

    async def _execute_tool(
        self,
        tool_executor: Callable[[str, dict[str, Any]], Any],
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> Any:
        """Execute a tool via the provided executor.
        
        Args:
            tool_executor: Callback to execute tools.
            tool_name: Name of the tool to execute.
            tool_args: Arguments for the tool.
            
        Returns:
            Tool execution result.
        """
        # Check if executor is async
        if asyncio.iscoroutinefunction(tool_executor):
            return await tool_executor(tool_name, tool_args)
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: tool_executor(tool_name, tool_args)
            )
