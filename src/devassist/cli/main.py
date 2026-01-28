"""Main CLI entry point for DevAssist.

Provides the primary Typer application and core commands.
"""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from devassist import __version__

# Create main Typer app
app = typer.Typer(
    name="devassist",
    help="Developer Assistant CLI - Your AI-powered morning brief.",
    add_completion=False,
    no_args_is_help=True,
)

# Rich console for formatted output
console = Console()


def show_security_warning() -> None:
    """Display security warning about credential storage.

    Per FR-004: Show security warning on startup for dev mode.
    """
    warning_text = Text()
    warning_text.append("DEV MODE: ", style="bold yellow")
    warning_text.append(
        "Credentials are stored in plain text at ~/.devassist/config.yaml. "
        "Do not use in production without proper secret management."
    )
    console.print(Panel(warning_text, title="Security Notice", border_style="yellow"))


def version_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        console.print(f"devassist version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """DevAssist - Developer Assistant CLI.

    An AI-powered CLI that aggregates context from multiple developer tools
    (Gmail, Slack, JIRA, GitHub) and generates a Unified Morning Brief.
    """
    # Security warning is shown contextually by commands that handle credentials
    pass


@app.command()
def status() -> None:
    """Show current configuration status."""
    import os

    from devassist.core.config_manager import ConfigManager
    from devassist.mcp.config import MCPConfigLoader

    manager = ConfigManager()
    config = manager.load_config()
    sources = manager.list_sources()

    console.print(f"\n[bold]DevAssist v{__version__}[/bold]\n")
    console.print(f"Workspace: {manager.workspace_dir}")
    console.print(f"Config: {manager.config_path}")

    # AI Provider status
    provider = config.ai.provider
    console.print(f"\n[bold]AI Provider:[/bold] {provider}")

    if provider == "claude":
        api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
        vertex_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("CLOUDSDK_CORE_PROJECT")

        # Try gcloud config as fallback
        if not vertex_project:
            from devassist.core.orchestrator import _get_gcloud_project

            vertex_project = _get_gcloud_project()

        if api_key_set:
            console.print("  Auth: [green]Anthropic API Key[/green]")
        elif vertex_project:
            console.print(f"  Auth: [green]Vertex AI[/green] (project: {vertex_project})")
        else:
            console.print("  Auth: [yellow]Not configured[/yellow]")
            console.print("  Set ANTHROPIC_API_KEY or configure gcloud project")
    else:
        console.print(f"  Model: {config.ai.model}")

    # MCP Servers
    mcp_loader = MCPConfigLoader()
    mcp_config = mcp_loader.load()
    mcp_servers = list(mcp_config.mcp_servers.keys())

    if mcp_servers:
        console.print(f"\n[bold]MCP Servers:[/bold] {', '.join(mcp_servers)}")
    else:
        console.print("\n[dim]No MCP servers configured.[/dim]")
        console.print("Run [bold]devassist config mcp add <server>[/bold] to configure.")

    # Legacy adapters
    if sources:
        console.print(f"\n[bold]Legacy Adapters:[/bold] {', '.join(sources)}")
    else:
        console.print("\n[dim]No legacy adapters configured.[/dim]")

    # Daemon status
    from devassist.cli.daemon import get_daemon_pid

    daemon_pid = get_daemon_pid()
    if daemon_pid:
        console.print(f"\n[bold]Daemon:[/bold] [green]Running[/green] (PID {daemon_pid})")
    else:
        console.print(f"\n[bold]Daemon:[/bold] [dim]Not running[/dim]")

    console.print()


# Import and register sub-commands
from devassist.cli.brief import app as brief_app
from devassist.cli.config import app as config_app
from devassist.cli.daemon import app as daemon_app

# Register subcommands
app.add_typer(config_app, name="config")
app.add_typer(brief_app, name="brief")
app.add_typer(daemon_app, name="daemon")


if __name__ == "__main__":
    app()
