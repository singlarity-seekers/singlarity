"""Chat command for DevAssist CLI.

Interactive AI chat with tool calling capabilities.
"""

import asyncio
from typing import Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from devassist.adapters import get_adapter
from devassist.ai import VertexAIClient, get_tool_executor
from devassist.core.config_manager import ConfigManager
from devassist.models.context import SourceType

console = Console()
chat_app = typer.Typer(help="Interactive AI chat with tool calling")


async def setup_adapters(config_manager: ConfigManager) -> list[str]:
    """Set up and authenticate adapters for configured sources.
    
    Returns:
        List of successfully configured source names.
    """
    executor = get_tool_executor()
    configured_sources: list[str] = []
    
    # Get configured source names
    source_names = config_manager.list_sources()
    
    for source_name in source_names:
        try:
            # Get source type from name
            try:
                source_type = SourceType(source_name)
            except ValueError:
                console.print(f"[yellow]Warning:[/yellow] Unknown source type: {source_name}")
                continue
            
            # Get adapter for this source type
            adapter = get_adapter(source_type)
            
            # Get source config
            source_config = config_manager.get_source_config(source_name) or {}
            
            # Authenticate
            await adapter.authenticate(source_config)
            
            # Register with executor
            executor.register_adapter(source_name, adapter)
            configured_sources.append(source_name)
            
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Could not initialize {source_name}: {e}")
    
    return configured_sources


async def chat_loop(
    ai_client: VertexAIClient,
    configured_sources: list[str],
) -> None:
    """Run the interactive chat loop."""
    from devassist.ai.tool_executor import execute_tool
    
    console.print(Panel(
        "[bold green]DevAssist AI Chat[/bold green]\n\n"
        "Chat with AI that can interact with your configured sources.\n"
        f"Available tools: {', '.join(configured_sources) if configured_sources else 'None'}\n\n"
        "Type [bold]'exit'[/bold] or [bold]'quit'[/bold] to end the session.\n"
        "Type [bold]'help'[/bold] to see available commands.",
        title="Welcome",
    ))
    
    if not configured_sources:
        console.print(
            "[yellow]No sources configured. Run 'devassist config add <source>' first.[/yellow]"
        )
        console.print("You can still chat, but the AI won't be able to access your tools.\n")
    
    while True:
        try:
            user_input = Prompt.ask("\n[bold blue]You[/bold blue]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break
        
        user_input = user_input.strip()
        
        if not user_input:
            continue
        
        if user_input.lower() in ("exit", "quit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break
        
        if user_input.lower() == "help":
            console.print(Panel(
                "[bold]Available commands:[/bold]\n"
                "  [cyan]exit/quit[/cyan] - End the chat session\n"
                "  [cyan]help[/cyan] - Show this help\n"
                "  [cyan]sources[/cyan] - Show configured sources\n\n"
                "[bold]Example requests:[/bold]\n"
                "  - 'Search my unread emails'\n"
                "  - 'Show me emails from boss@company.com'\n"
                "  - 'Draft a reply to the latest email'\n"
                "  - 'Send an email to john@example.com about the meeting'",
                title="Help",
            ))
            continue
        
        if user_input.lower() == "sources":
            if configured_sources:
                console.print(f"[green]Configured sources:[/green] {', '.join(configured_sources)}")
            else:
                console.print("[yellow]No sources configured.[/yellow]")
            continue
        
        # Send to AI with tools
        console.print("\n[dim]Thinking...[/dim]")
        
        try:
            response = await ai_client.chat_with_tools(
                message=user_input,
                tool_executor=execute_tool,
                sources=configured_sources if configured_sources else None,
            )
            
            console.print(f"\n[bold green]Assistant[/bold green]")
            console.print(Markdown(response))
            
        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}")


@chat_app.callback(invoke_without_command=True)
def chat(
    ctx: typer.Context,
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        "-k",
        envvar="DEVASSIST_AI__API_KEY",
        help="Google AI API key",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="AI model to use (default: gemini-2.5-flash)",
    ),
) -> None:
    """Start an interactive AI chat session with tool calling.
    
    The AI can use tools to interact with your configured sources
    (Gmail, Slack, JIRA, GitHub) based on your requests.
    
    Examples:
        devassist chat
        devassist chat --api-key YOUR_API_KEY
        devassist chat --model gemini-1.5-pro
    """
    if ctx.invoked_subcommand is not None:
        return
    
    async def run() -> None:
        # Initialize
        config_manager = ConfigManager()
        config = config_manager.load_config()
        
        # Set up AI client
        ai_config = config.ai
        ai_client = VertexAIClient(
            api_key=api_key or ai_config.api_key,
            project_id=ai_config.project_id,
            model=model or ai_config.model,
        )
        
        # Set up adapters
        console.print("[dim]Setting up sources...[/dim]")
        configured_sources = await setup_adapters(config_manager)
        
        # Run chat loop
        await chat_loop(ai_client, configured_sources)
    
    asyncio.run(run())


if __name__ == "__main__":
    chat_app()
