"""Config CLI commands for DevAssist.

DEPRECATED: These commands used the legacy adapter-based configuration system.
The new architecture uses MCP servers configured through ClientConfig.

Use ClientConfig.from_cli_args() or ClientConfig configuration files instead.
These legacy commands have been removed.
"""

import typer
from rich.console import Console
from rich.panel import Panel

# Create router for config commands
app = typer.Typer(
    name="config",
    help="[DEPRECATED] Legacy config commands. Use ClientConfig instead.",
    no_args_is_help=True,
)

console = Console()


@app.command()
def add() -> None:
    """[DEPRECATED] Add a context source."""
    _show_deprecation_message()


@app.command()
def list() -> None:
    """[DEPRECATED] List configured sources."""
    _show_deprecation_message()


@app.command()
def remove() -> None:
    """[DEPRECATED] Remove a context source."""
    _show_deprecation_message()


@app.command()
def test() -> None:
    """[DEPRECATED] Test a context source."""
    _show_deprecation_message()


def _show_deprecation_message() -> None:
    """Show deprecation message for legacy config commands."""
    message = """
[bold red]DEPRECATED:[/bold red] Legacy config commands have been removed.

[bold]The new architecture uses:[/bold]
• [cyan]ClientConfig[/cyan] from [green]devassist.models.config[/green]
• [cyan]MCP servers[/cyan] for context sources
• [cyan]Configuration files[/cyan] at [yellow]~/.devassist/config.yaml[/yellow]

[bold]Migration:[/bold]
1. Use [green]ClientConfig()[/green] directly in your code
2. Configure MCP servers through [yellow]config.yaml[/yellow]
3. Use environment variables for credentials

[bold]Example:[/bold]
[dim]from devassist.models.config import ClientConfig
config = ClientConfig(sources=['gmail', 'slack'])[/dim]
    """

    console.print(Panel(message, title="Legacy Config Commands Deprecated", border_style="red"))
    raise typer.Exit(1)