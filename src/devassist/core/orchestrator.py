"""Claude SDK orchestrator for DevAssist.

Uses Claude as the orchestration agent with MCP tools to fetch context
from various sources (GitHub, Slack, JIRA) and generate morning briefs.
"""

import asyncio
import os
from contextlib import asynccontextmanager, AsyncExitStack
from pathlib import Path
from typing import Any, AsyncIterator

from devassist.ai.prompts import NO_ITEMS_SUMMARY, get_system_prompt
from devassist.mcp.config import MCPConfigLoader, MCPServerConfig

# Anthropic SDK imports - optional, checked at runtime
try:
    import anthropic
    from anthropic.types import Message, TextBlock, ToolUseBlock, ToolResultBlockParam

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = None  # type: ignore

# Anthropic Vertex AI imports - optional
try:
    from anthropic import AnthropicVertex

    ANTHROPIC_VERTEX_AVAILABLE = True
except ImportError:
    ANTHROPIC_VERTEX_AVAILABLE = False
    AnthropicVertex = None  # type: ignore

# MCP client imports - optional
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    ClientSession = None  # type: ignore
    StdioServerParameters = None  # type: ignore
    stdio_client = None  # type: ignore


# Base MCP-aware system prompt for Claude
MCP_SYSTEM_PROMPT_BASE = """You are DevAssist, an intelligent developer assistant that creates personalized morning briefs.

Your job is to:
1. Use the available MCP tools to fetch context from configured sources (GitHub, Slack, JIRA)
2. Analyze and prioritize items by relevance and urgency
3. Generate a concise, actionable morning brief

Guidelines:
- Focus on items requiring action or attention
- Group related items together
- Highlight blockers and urgent issues
- Be concise but informative
- Include direct links where available

When fetching data:
- For GitHub: Check notifications, PR review requests, and issues assigned to the user
- For Slack: Check direct messages, mentions, and important channel updates
- For JIRA: Check issues assigned to the user and approaching deadlines

Always provide actionable insights and prioritize by urgency.
"""


def build_system_prompt(user_config: Any = None) -> str:
    """Build system prompt with user context.

    Args:
        user_config: User configuration object.

    Returns:
        Complete system prompt with user context.
    """
    prompt = MCP_SYSTEM_PROMPT_BASE

    if user_config:
        user_context = []

        if user_config.github_username:
            user_context.append(f"- GitHub username: {user_config.github_username}")
        if user_config.github_orgs:
            user_context.append(f"- GitHub organizations: {', '.join(user_config.github_orgs)}")
        if user_config.jira_username:
            user_context.append(f"- JIRA username: {user_config.jira_username}")
        if user_config.email:
            user_context.append(f"- Email: {user_config.email}")
        if user_config.name:
            user_context.append(f"- Name: {user_config.name}")

        if user_context:
            prompt += f"""
User Context:
{chr(10).join(user_context)}

Use this information to search for items specifically relevant to this user (assigned issues, review requests, mentions, etc.).
"""

    return prompt


class MCPServerManager:
    """Manages connections to MCP servers."""

    def __init__(self, mcp_config_loader: MCPConfigLoader):
        """Initialize the MCP server manager.

        Args:
            mcp_config_loader: Loader for MCP configuration.
        """
        self.mcp_loader = mcp_config_loader
        self._sessions: dict[str, ClientSession] = {}
        self._tools: list[dict[str, Any]] = []

    @asynccontextmanager
    async def connect_all(self) -> AsyncIterator["MCPServerManager"]:
        """Connect to all configured MCP servers.

        Yields:
            Self with active connections.
        """
        if not MCP_AVAILABLE:
            raise RuntimeError(
                "MCP client not installed. Run: pip install mcp"
            )

        mcp_config = self.mcp_loader.load()

        async with AsyncExitStack() as stack:
            for name, server_config in mcp_config.mcp_servers.items():
                if not server_config.enabled:
                    continue

                if server_config.type == "stdio":
                    try:
                        # Build environment with expanded variables
                        env = dict(os.environ)
                        if server_config.env:
                            env.update(server_config.env)

                        params = StdioServerParameters(
                            command=server_config.command,
                            args=server_config.args or [],
                            env=env,
                        )

                        # Enter the stdio client context properly
                        read_stream, write_stream = await stack.enter_async_context(
                            stdio_client(params)
                        )

                        # Create and initialize session
                        session = await stack.enter_async_context(
                            ClientSession(read_stream, write_stream)
                        )

                        # Initialize the session
                        await session.initialize()

                        self._sessions[name] = session

                        # Get tools from this server
                        tools_result = await session.list_tools()
                        for tool in tools_result.tools:
                            self._tools.append({
                                "name": f"{name}__{tool.name}",
                                "description": tool.description or f"Tool from {name}",
                                "input_schema": tool.inputSchema,
                                "_server": name,
                                "_original_name": tool.name,
                            })

                        print(f"Connected to MCP server: {name} ({len(tools_result.tools)} tools)")

                    except Exception as e:
                        print(f"Warning: Failed to connect to MCP server '{name}': {e}")
                        continue

            try:
                yield self
            finally:
                self._sessions.clear()
                self._tools.clear()

    def get_tools_for_claude(self) -> list[dict[str, Any]]:
        """Get tool definitions formatted for Claude API.

        Returns:
            List of tool definitions.
        """
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["input_schema"],
            }
            for tool in self._tools
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the appropriate MCP server.

        Args:
            tool_name: Full tool name (server__toolname format).
            arguments: Tool arguments.

        Returns:
            Tool result.
        """
        # Parse server name from tool name
        if "__" in tool_name:
            server_name, original_name = tool_name.split("__", 1)
        else:
            # Try to find the tool
            for tool in self._tools:
                if tool["name"] == tool_name or tool["_original_name"] == tool_name:
                    server_name = tool["_server"]
                    original_name = tool["_original_name"]
                    break
            else:
                raise ValueError(f"Unknown tool: {tool_name}")

        if server_name not in self._sessions:
            raise ValueError(f"MCP server '{server_name}' not connected")

        session = self._sessions[server_name]
        result = await session.call_tool(original_name, arguments)

        # Extract content from result
        if hasattr(result, "content"):
            contents = []
            for content in result.content:
                if hasattr(content, "text"):
                    contents.append(content.text)
                elif hasattr(content, "data"):
                    contents.append(str(content.data))
            return "\n".join(contents) if contents else str(result)

        return str(result)

BRIEF_PROMPT = """Generate my morning brief by checking all available sources.

For each source you have access to:
- GitHub: Check my notifications, PR review requests, and assigned issues
- Slack: Check direct messages and recent mentions
- JIRA: Check issues assigned to me and approaching deadlines

Then create a summary with:
1. Executive summary (2-3 sentences about what needs attention)
2. Key highlights as bullet points
3. Action items requiring immediate attention
4. Any blockers or urgent issues

Format the output in clean markdown.
"""


def _get_gcloud_project() -> str | None:
    """Get the default GCP project from gcloud config.

    Returns:
        Project ID or None if not configured.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            project = result.stdout.strip()
            if project and project != "(unset)":
                return project
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


class ClaudeOrchestrator:
    """Orchestrates Claude SDK interactions with MCP servers."""

    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    DEFAULT_MODEL_VERTEX = "claude-sonnet-4@20250514"  # Vertex AI model format
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_VERTEX_REGION = "us-east5"

    def __init__(
        self,
        mcp_config_path: Path | str | None = None,
        api_key: str | None = None,
        project_id: str | None = None,
        region: str | None = None,
        model: str | None = None,
        use_vertex: bool | None = None,
    ) -> None:
        """Initialize the Claude orchestrator.

        Supports two authentication modes:
        1. Direct Anthropic API: Set ANTHROPIC_API_KEY or pass api_key
        2. Vertex AI: Set GOOGLE_CLOUD_PROJECT or pass project_id (or use gcloud config)

        Args:
            mcp_config_path: Path to .mcp.json file.
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var).
            project_id: GCP project ID for Vertex AI (auto-detected from env or gcloud).
            region: GCP region for Vertex AI (defaults to us-east5).
            model: Claude model to use.
            use_vertex: Force Vertex AI mode. Auto-detected if None.
        """
        self.mcp_loader = MCPConfigLoader(mcp_config_path)

        # Load user config for personalized prompts
        from devassist.core.config_manager import ConfigManager
        config_manager = ConfigManager()
        app_config = config_manager.load_config()
        self.user_config = app_config.user

        # Check for credentials
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

        # Try to get project ID from multiple sources
        self.project_id = (
            project_id
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("CLOUDSDK_CORE_PROJECT")
            or _get_gcloud_project()
        )
        self.region = region or os.environ.get("GOOGLE_CLOUD_REGION") or self.DEFAULT_VERTEX_REGION

        # Determine which mode to use
        if use_vertex is not None:
            self.use_vertex = use_vertex
        else:
            # Auto-detect: prefer Vertex AI if project_id is set and no API key
            self.use_vertex = bool(self.project_id) and not self.api_key

        # Set model based on mode
        if model:
            self.model = model
        elif self.use_vertex:
            self.model = self.DEFAULT_MODEL_VERTEX
        else:
            self.model = self.DEFAULT_MODEL

        self._client: Any = None

    def _get_system_prompt(self) -> str:
        """Get the system prompt with user context."""
        return build_system_prompt(self.user_config)

    def _get_client(self) -> Any:
        """Get or create the Anthropic client.

        Returns:
            Configured Anthropic or AnthropicVertex client.

        Raises:
            RuntimeError: If SDK is not available or credentials missing.
        """
        if self._client is not None:
            return self._client

        if self.use_vertex:
            # Use Vertex AI
            if not ANTHROPIC_VERTEX_AVAILABLE:
                raise RuntimeError(
                    "Anthropic Vertex SDK not installed. Run: pip install 'anthropic[vertex]'"
                )

            if not self.project_id:
                raise RuntimeError(
                    "GCP project ID not found. Set GOOGLE_CLOUD_PROJECT environment variable "
                    "or pass project_id to ClaudeOrchestrator."
                )

            self._client = AnthropicVertex(
                project_id=self.project_id,
                region=self.region,
            )
        else:
            # Use direct Anthropic API
            if not ANTHROPIC_AVAILABLE:
                raise RuntimeError(
                    "Anthropic SDK not installed. Run: pip install anthropic"
                )

            if not self.api_key:
                raise RuntimeError(
                    "No credentials found. Either:\n"
                    "  1. Set ANTHROPIC_API_KEY for direct API access, or\n"
                    "  2. Set GOOGLE_CLOUD_PROJECT for Vertex AI access"
                )

            self._client = anthropic.Anthropic(api_key=self.api_key)

        return self._client

    def _build_mcp_servers_config(self) -> list[dict[str, Any]]:
        """Build MCP server configuration for Claude API.

        Returns:
            List of MCP server configurations for the API.
        """
        mcp_config = self.mcp_loader.load()
        servers = []

        for name, server_config in mcp_config.mcp_servers.items():
            if not server_config.enabled:
                continue

            if server_config.type == "stdio":
                # For stdio servers, we need to describe the tools available
                # This is a placeholder - actual MCP integration requires
                # running the server and getting its tool definitions
                servers.append({
                    "name": name,
                    "type": "stdio",
                    "command": server_config.command,
                    "args": server_config.args,
                    "env": server_config.env,
                })
            elif server_config.type in ("http", "sse"):
                servers.append({
                    "name": name,
                    "type": "url",
                    "url": server_config.url,
                    "headers": server_config.headers,
                })

        return servers

    def _build_tools_from_mcp(self) -> list[dict[str, Any]]:
        """Build tool definitions based on configured MCP servers.

        Returns:
            List of tool definitions for Claude.
        """
        mcp_config = self.mcp_loader.load()
        tools = []

        # Define standard tools for each MCP server type
        tool_templates = {
            "github": [
                {
                    "name": "github_list_notifications",
                    "description": "List GitHub notifications for the authenticated user",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "all": {
                                "type": "boolean",
                                "description": "Include read notifications",
                            },
                            "participating": {
                                "type": "boolean",
                                "description": "Only notifications where user is participating",
                            },
                        },
                    },
                },
                {
                    "name": "github_list_pull_requests",
                    "description": "List pull requests awaiting review",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "state": {
                                "type": "string",
                                "enum": ["open", "closed", "all"],
                                "description": "PR state filter",
                            },
                        },
                    },
                },
            ],
            "slack": [
                {
                    "name": "slack_list_messages",
                    "description": "List recent Slack messages and mentions",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "channel": {
                                "type": "string",
                                "description": "Channel ID to fetch messages from",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum messages to return",
                            },
                        },
                    },
                },
                {
                    "name": "slack_list_mentions",
                    "description": "List messages mentioning the user",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Maximum mentions to return",
                            },
                        },
                    },
                },
            ],
            "jira": [
                {
                    "name": "jira_search_issues",
                    "description": "Search JIRA issues assigned to the user",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "jql": {
                                "type": "string",
                                "description": "JQL query string",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum results to return",
                            },
                        },
                    },
                },
            ],
        }

        for name, server_config in mcp_config.mcp_servers.items():
            if not server_config.enabled:
                continue

            if name in tool_templates:
                tools.extend(tool_templates[name])

        return tools

    async def generate_brief(self, refresh: bool = False) -> str:
        """Generate a morning brief using Claude with MCP tools.

        Args:
            refresh: If True, bypass any cached data.

        Returns:
            Markdown-formatted morning brief.
        """
        mcp_config = self.mcp_loader.load()

        if not mcp_config.mcp_servers:
            return NO_ITEMS_SUMMARY

        # Check if we have any enabled servers
        enabled_servers = [
            name for name, s in mcp_config.mcp_servers.items() if s.enabled
        ]

        if not enabled_servers:
            return NO_ITEMS_SUMMARY

        try:
            return await self._generate_with_claude(refresh)
        except Exception as e:
            # Return error message but don't crash
            auth_help = (
                "GOOGLE_CLOUD_PROJECT is set for Vertex AI"
                if self.use_vertex
                else "ANTHROPIC_API_KEY is set for direct API access"
            )
            return f"""## Morning Brief Generation Failed

An error occurred while generating your morning brief:

**Error**: {e!s}

Please check:
1. Your {auth_help}
2. MCP servers are configured in ~/.devassist/.mcp.json
3. Required environment variables for each MCP server are set

You can run `devassist config mcp list` to see configured servers.
"""

    async def _generate_with_claude(self, refresh: bool = False) -> str:
        """Generate brief using Claude API with tool use.

        Args:
            refresh: Whether to refresh cached data.

        Returns:
            Generated brief text.
        """
        client = self._get_client()

        prompt = BRIEF_PROMPT
        if refresh:
            prompt += "\n\nPlease fetch fresh data, ignoring any cached information."

        # Connect to MCP servers and use their tools
        mcp_manager = MCPServerManager(self.mcp_loader)

        if not MCP_AVAILABLE:
            # Fall back to no-tools mode
            return await self._generate_without_tools(client, prompt)

        try:
            async with mcp_manager.connect_all() as manager:
                tools = manager.get_tools_for_claude()

                if not tools:
                    # No tools available, fall back
                    return await self._generate_without_tools(client, prompt)

                # Agentic loop with tool use
                messages = [{"role": "user", "content": prompt}]
                max_iterations = 10

                for _ in range(max_iterations):
                    # Run in thread pool since anthropic SDK may block
                    loop = asyncio.get_event_loop()
                    response: Message = await loop.run_in_executor(
                        None,
                        lambda: client.messages.create(
                            model=self.model,
                            max_tokens=self.DEFAULT_MAX_TOKENS,
                            system=self._get_system_prompt(),
                            messages=messages,
                            tools=tools,
                        ),
                    )

                    # Check if we're done (no tool use)
                    if response.stop_reason == "end_turn":
                        # Extract final text
                        result_text = []
                        for block in response.content:
                            if isinstance(block, TextBlock):
                                result_text.append(block.text)
                        return "".join(result_text) if result_text else NO_ITEMS_SUMMARY

                    # Process tool calls
                    tool_results = []
                    has_tool_use = False

                    for block in response.content:
                        if isinstance(block, ToolUseBlock):
                            has_tool_use = True
                            tool_name = block.name
                            tool_input = block.input

                            print(f"  Calling tool: {tool_name}")

                            try:
                                result = await manager.call_tool(tool_name, tool_input)
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": str(result),
                                })
                            except Exception as e:
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": f"Error: {e}",
                                    "is_error": True,
                                })

                    if not has_tool_use:
                        # No more tool calls, extract text
                        result_text = []
                        for block in response.content:
                            if isinstance(block, TextBlock):
                                result_text.append(block.text)
                        return "".join(result_text) if result_text else NO_ITEMS_SUMMARY

                    # Add assistant message and tool results
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": tool_results})

                # Max iterations reached
                return "## Brief Generation Incomplete\n\nReached maximum iterations. Partial results may be available."

        except Exception as e:
            print(f"MCP integration error: {e}, falling back to no-tools mode")
            return await self._generate_without_tools(client, prompt)

    async def _generate_without_tools(self, client: Any, prompt: str) -> str:
        """Generate brief without MCP tools.

        Args:
            client: Anthropic client.
            prompt: The prompt to send.

        Returns:
            Generated brief text.
        """
        loop = asyncio.get_event_loop()
        response: Message = await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                model=self.model,
                max_tokens=self.DEFAULT_MAX_TOKENS,
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            ),
        )

        result_text = []
        for block in response.content:
            if isinstance(block, TextBlock):
                result_text.append(block.text)

        return "".join(result_text) if result_text else NO_ITEMS_SUMMARY

    async def query(self, prompt: str, use_tools: bool = True) -> str:
        """Send a custom query to Claude.

        Args:
            prompt: The query prompt.
            use_tools: Whether to use MCP tools.

        Returns:
            Claude's response text.
        """
        client = self._get_client()

        if not use_tools or not MCP_AVAILABLE:
            return await self._query_without_tools(client, prompt)

        # Connect to MCP servers and use their tools
        mcp_manager = MCPServerManager(self.mcp_loader)

        try:
            async with mcp_manager.connect_all() as manager:
                tools = manager.get_tools_for_claude()

                if not tools:
                    return await self._query_without_tools(client, prompt)

                # Agentic loop with tool use
                messages = [{"role": "user", "content": prompt}]
                max_iterations = 10

                for _ in range(max_iterations):
                    loop = asyncio.get_event_loop()
                    response: Message = await loop.run_in_executor(
                        None,
                        lambda: client.messages.create(
                            model=self.model,
                            max_tokens=self.DEFAULT_MAX_TOKENS,
                            system=get_system_prompt(),
                            messages=messages,
                            tools=tools,
                        ),
                    )

                    # Check if we're done
                    if response.stop_reason == "end_turn":
                        result_text = []
                        for block in response.content:
                            if isinstance(block, TextBlock):
                                result_text.append(block.text)
                        return "".join(result_text)

                    # Process tool calls
                    tool_results = []
                    has_tool_use = False

                    for block in response.content:
                        if isinstance(block, ToolUseBlock):
                            has_tool_use = True
                            try:
                                result = await manager.call_tool(block.name, block.input)
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": str(result),
                                })
                            except Exception as e:
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": f"Error: {e}",
                                    "is_error": True,
                                })

                    if not has_tool_use:
                        result_text = []
                        for block in response.content:
                            if isinstance(block, TextBlock):
                                result_text.append(block.text)
                        return "".join(result_text)

                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": tool_results})

                return "Query reached maximum iterations."

        except Exception as e:
            print(f"MCP query error: {e}, falling back to no-tools mode")
            return await self._query_without_tools(client, prompt)

    async def _query_without_tools(self, client: Any, prompt: str) -> str:
        """Send a query without MCP tools.

        Args:
            client: Anthropic client.
            prompt: The query prompt.

        Returns:
            Claude's response text.
        """
        loop = asyncio.get_event_loop()
        response: Message = await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                model=self.model,
                max_tokens=self.DEFAULT_MAX_TOKENS,
                system=get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            ),
        )

        result_text = []
        for block in response.content:
            if isinstance(block, TextBlock):
                result_text.append(block.text)

        return "".join(result_text)


class HybridOrchestrator:
    """Orchestrator that can use either Claude or Vertex AI based on config."""

    def __init__(
        self,
        provider: str = "claude",
        mcp_config_path: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the hybrid orchestrator.

        Args:
            provider: AI provider to use ('claude' or 'vertex').
            mcp_config_path: Path to MCP config (for Claude).
            **kwargs: Additional arguments passed to the provider.
        """
        self.provider = provider

        if provider == "claude":
            self._orchestrator: Any = ClaudeOrchestrator(
                mcp_config_path=mcp_config_path, **kwargs
            )
        else:
            # Import Vertex AI client for fallback
            from devassist.ai.vertex_client import VertexAIClient

            self._vertex_client = VertexAIClient(**kwargs)
            self._orchestrator = None

    async def generate_brief(
        self, refresh: bool = False, items: list[Any] | None = None
    ) -> str:
        """Generate a morning brief.

        Args:
            refresh: Bypass cached data.
            items: Context items (only used for Vertex AI fallback).

        Returns:
            Generated brief text.
        """
        if self.provider == "claude":
            return await self._orchestrator.generate_brief(refresh=refresh)
        else:
            # Vertex AI fallback - requires pre-fetched items
            if items is None:
                return NO_ITEMS_SUMMARY
            return await self._vertex_client.summarize(items)

    async def query(self, prompt: str) -> str:
        """Send a query to the AI provider.

        Args:
            prompt: Query prompt.

        Returns:
            Response text.
        """
        if self.provider == "claude":
            return await self._orchestrator.query(prompt)
        else:
            raise NotImplementedError("Custom queries not supported with Vertex AI")
