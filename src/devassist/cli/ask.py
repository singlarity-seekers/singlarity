"""Ask command for DevAssist CLI.

Provides natural language interface to the orchestration agent.
"""

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from devassist.core.config_manager import ConfigManager

console = Console()


def ask(
    prompt: Annotated[
        str,
        typer.Argument(help="Your question or request in natural language"),
    ],
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            "-p",
            help="LLM provider to use (vertex for Gemini, anthropic for Claude)",
        ),
    ] = "anthropic",  # Default to Anthropic (Claude), works with both direct API and Vertex AI
    servers: Annotated[
        str | None,
        typer.Option(
            "--servers",
            "-s",
            help="Comma-separated list of MCP servers to connect (github,slack,filesystem)",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show detailed output including tool calls",
        ),
    ] = False,
) -> None:
    """Ask the assistant a question using natural language.

    The assistant will use available MCP tools to gather information
    and provide a helpful response.

    Examples:
        devassist ask "What are my GitHub notifications?"
        devassist ask "Show me recent Slack messages" -s slack
        devassist ask "Give me a morning brief" -s github,slack
    """
    # Check if setup is needed
    from devassist.cli.setup import check_and_prompt_setup
    if not check_and_prompt_setup():
        raise typer.Exit(1)
    
    asyncio.run(_ask_async(prompt, provider, servers, verbose))


async def _ask_async(
    prompt: str,
    provider: str,
    servers: str | None,
    verbose: bool,
) -> None:
    """Async implementation of the ask command."""
    from devassist.mcp.client import MCPClient
    from devassist.mcp.registry import MCPRegistry
    from devassist.orchestrator.agent import OrchestrationAgent
    from devassist.orchestrator.llm_client import AnthropicLLMClient, VertexAILLMClient

    config_manager = ConfigManager()

    # Create LLM client
    if provider == "anthropic":
        llm_client = AnthropicLLMClient()
    else:
        ai_config = config_manager.get_ai_config()
        llm_client = VertexAILLMClient(
            project_id=ai_config.get("project_id"),
            location=ai_config.get("location", "us-central1"),
        )

    # Create MCP components
    mcp_client = MCPClient()
    registry = MCPRegistry()

    # Load MCP server configs from user config
    mcp_config = config_manager.get_mcp_config()
    if mcp_config:
        for name, server_config in mcp_config.items():
            registry.configure_server(name, server_config.get("env", {}))

    # Determine which servers to connect
    if servers:
        server_names = [s.strip() for s in servers.split(",")]
    else:
        # Use all configured servers
        server_names = [s.name for s in registry.list_configured()]

    if not server_names:
        console.print(
            Panel(
                "[yellow]No MCP servers configured.[/yellow]\n\n"
                "To configure servers, add them to your config:\n"
                "  devassist config mcp add github --token YOUR_TOKEN\n\n"
                "Or specify servers with credentials via environment:\n"
                "  GITHUB_PERSONAL_ACCESS_TOKEN=xxx devassist ask 'your question' -s github",
                title="No Servers Available",
            )
        )
        return

    # Get server configs
    server_configs = []
    for name in server_names:
        config = registry.get(name)
        if config and config.is_configured():
            server_configs.append(config)
        elif verbose:
            console.print(f"[yellow]Skipping {name}: not configured[/yellow]")

    if not server_configs:
        console.print("[red]No configured MCP servers available.[/red]")
        return

    # Create agent
    agent = OrchestrationAgent(
        llm_client=llm_client,
        mcp_client=mcp_client,
        registry=registry,
    )

    # Connect to MCP servers and process
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Connecting to MCP servers...", total=None)

        try:
            async with mcp_client.connect_all(server_configs):
                progress.update(task, description="Processing your request...")

                # Get available tools for verbose output
                if verbose:
                    tools = mcp_client.get_all_tools()
                    console.print(f"\n[dim]Available tools: {len(tools)}[/dim]")
                    for tool in tools:
                        console.print(f"[dim]  - {tool.name}: {tool.description[:50]}...[/dim]")
                    console.print()

                # Process the prompt
                response = await agent.process(prompt)

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            if verbose:
                import traceback
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
            return

    # Display response
    if response.error:
        console.print(f"\n[yellow]Warning: {response.error}[/yellow]\n")

    console.print(Panel(response.content, title="Assistant Response", border_style="green"))

    if verbose:
        console.print(f"\n[dim]Sources used: {', '.join(response.sources_used) or 'none'}[/dim]")
        console.print(f"[dim]Tool calls made: {response.tool_calls_made}[/dim]")
