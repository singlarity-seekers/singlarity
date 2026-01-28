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
    pass


@app.command(name="ask")
def ask_question(
    query: list[str] = typer.Argument(..., help="Your question"),
    no_context: bool = typer.Option(
        False,
        "--no-context",
        help="Don't include aggregated context (pure AI query)",
    ),
    hours: int = typer.Option(
        24,
        "--hours",
        "-h",
        help="Context time window in hours (default: 24)",
    ),
    temperature: float = typer.Option(
        0.5,
        "--temperature",
        "-t",
        help="AI temperature for generation (0.0-2.0, default: 0.5)",
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """Ask a custom question with context (default if no command specified)."""
    import asyncio
    from devassist.core.prompt_executor import PromptExecutor
    from devassist.cli.prompt_commands import display_result

    full_query = " ".join(query)

    if no_context:
        console.print("[dim]Executing custom question (no context)...[/dim]")
    else:
        console.print(f"[dim]Executing custom question (context: last {hours}h)...[/dim]")

    try:
        executor = PromptExecutor()
        result = asyncio.run(
            executor.execute_custom(
                user_prompt=full_query,
                include_context=not no_context,
                time_window_hours=hours,
                temperature=temperature,
            )
        )
        display_result(result, json_output)
    except Exception as e:
        console.print(f"[red]Error executing question:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show current configuration status."""
    from devassist.core.config_manager import ConfigManager

    manager = ConfigManager()
    sources = manager.list_sources()

    console.print(f"\n[bold]DevAssist v{__version__}[/bold]\n")
    console.print(f"Workspace: {manager.workspace_dir}")
    console.print(f"Config: {manager.config_path}")

    if sources:
        console.print(f"\nConfigured sources: {', '.join(sources)}")
    else:
        console.print("\n[dim]No sources configured yet.[/dim]")
        console.print("Run [bold]devassist config add <source>[/bold] to get started.\n")


# Import and register sub-commands
from devassist.cli.brief import app as brief_app
from devassist.cli.config import app as config_app
from devassist.cli.prompt_commands import prompt

# Register subcommands
app.add_typer(config_app, name="config")
app.add_typer(brief_app, name="brief")

# Register prompt command for built-in templates
app.command(name="prompt")(prompt)


def cli_main():
    """Main entry point with custom argument handling for default behavior."""
    import sys

    # Known subcommands
    known_commands = {"config", "brief", "status", "prompt", "ask", "--help", "-h", "--version", "-v"}

    # If no arguments or first arg is a known command/flag, use normal Typer behavior
    if len(sys.argv) <= 1 or sys.argv[1] in known_commands:
        app()
        return

    # Otherwise, treat entire command line as a question for "ask" command
    # Prepend "ask" to the arguments
    sys.argv.insert(1, "ask")
    app()


if __name__ == "__main__":
    cli_main()
