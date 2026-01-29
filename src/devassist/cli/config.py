"""Config CLI commands for DevAssist.

Provides commands to add, list, remove, and test context source configurations.
"""

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from devassist.adapters import get_adapter, list_available_adapters
from devassist.adapters.errors import AuthenticationError, SourceUnavailableError
from devassist.core.config_manager import ConfigManager
from devassist.models.context import SourceType

# Create router for config commands
app = typer.Typer(
    name="config",
    help="Manage context source configurations.",
    no_args_is_help=True,
)

console = Console()


def show_security_warning() -> None:
    """Display security warning about credential storage."""
    from rich.text import Text

    warning_text = Text()
    warning_text.append("DEV MODE: ", style="bold yellow")
    warning_text.append(
        "Credentials are stored in plain text at ~/.devassist/config.yaml. "
        "Do not use in production without proper secret management."
    )
    console.print(Panel(warning_text, title="Security Notice", border_style="yellow"))


@app.command("add")
def add_source(
    source: str = typer.Argument(
        ...,
        help="Source type to add (gmail, slack, jira, github)",
    ),
) -> None:
    """Add and configure a new context source.

    Guides through the authentication setup for the specified source.
    """
    show_security_warning()
    console.print()

    # Validate source type
    try:
        source_type = SourceType(source.lower())
    except ValueError:
        available = ", ".join(s.value for s in SourceType)
        console.print(f"[red]Error:[/red] Unknown source type '{source}'")
        console.print(f"Available sources: {available}")
        raise typer.Exit(1)

    # Get adapter for this source
    adapter = get_adapter(source_type)
    required_fields = adapter.get_required_config_fields()

    console.print(f"\n[bold]Configuring {adapter.display_name}[/bold]\n")

    # Collect required configuration
    config: dict[str, str] = {}

    for field in required_fields:
        # Provide helpful prompts based on field name
        if field == "credentials_file":
            prompt = "Path to OAuth credentials.json file"
        elif field == "bot_token":
            prompt = "Slack Bot Token (xoxb-...)"
        elif field == "api_token":
            prompt = "JIRA API Token"
        elif field == "personal_access_token":
            prompt = "GitHub Personal Access Token (ghp_...)"
        elif field == "url":
            prompt = "JIRA URL (https://company.atlassian.net)"
        elif field == "email":
            prompt = "Your email address"
        else:
            prompt = field.replace("_", " ").title()

        # Get input (password fields are hidden)
        is_secret = "token" in field.lower() or "password" in field.lower()
        value = Prompt.ask(prompt, password=is_secret)
        config[field] = value

    # Attempt authentication
    console.print("\n[dim]Authenticating...[/dim]")

    try:
        success = asyncio.run(adapter.authenticate(config))
        if success:
            console.print("[green]Authentication successful![/green]")
        else:
            console.print("[red]Authentication failed[/red]")
            raise typer.Exit(1)
    except AuthenticationError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        raise typer.Exit(1)

    # Save configuration
    manager = ConfigManager()
    manager.set_source_config(source_type.value, {"enabled": True, **config})

    console.print(f"\n[green]{adapter.display_name} configured successfully![/green]")
    console.print(f"Run [bold]devassist config test {source}[/bold] to verify the connection.\n")


@app.command("list")
def list_sources() -> None:
    """List all configured context sources."""
    manager = ConfigManager()
    sources = manager.list_sources()

    if not sources:
        console.print("\n[dim]No sources configured yet.[/dim]")
        console.print("Run [bold]devassist config add <source>[/bold] to get started.\n")

        # Show available sources
        available = list_available_adapters()
        console.print("Available sources:")
        for source_type, display_name in available:
            console.print(f"  - {display_name} ({source_type.value})")
        console.print()
        return

    table = Table(title="Configured Sources")
    table.add_column("Source", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")

    for source_name in sources:
        source_config = manager.get_source_config(source_name)
        enabled = source_config.get("enabled", True) if source_config else False
        status = "[green]Enabled[/green]" if enabled else "[dim]Disabled[/dim]"

        try:
            adapter = get_adapter(source_name)
            display_name = adapter.display_name
        except ValueError:
            display_name = source_name.title()

        table.add_row(source_name, display_name, status)

    console.print()
    console.print(table)
    console.print()


@app.command("remove")
def remove_source(
    source: str = typer.Argument(
        ...,
        help="Source to remove (gmail, slack, jira, github)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Remove without confirmation",
    ),
) -> None:
    """Remove a configured context source."""
    manager = ConfigManager()

    # Check if source exists
    if source.lower() not in manager.list_sources():
        console.print(f"[red]Error:[/red] Source '{source}' is not configured.")
        raise typer.Exit(1)

    # Confirm removal
    if not force:
        confirm = Prompt.ask(
            f"Remove {source} configuration? This will delete stored credentials",
            choices=["y", "n"],
            default="n",
        )
        if confirm.lower() != "y":
            console.print("Cancelled.")
            raise typer.Exit(0)

    # Remove configuration
    manager.remove_source_config(source.lower())
    console.print(f"[green]Removed {source} configuration.[/green]")


@app.command("test")
def test_source(
    source: Optional[str] = typer.Argument(
        None,
        help="Source to test (gmail, slack, jira, github). Tests all if not specified.",
    ),
) -> None:
    """Test connection to configured context sources."""
    manager = ConfigManager()
    sources_to_test = []

    if source:
        if source.lower() not in manager.list_sources():
            console.print(f"[red]Error:[/red] Source '{source}' is not configured.")
            raise typer.Exit(1)
        sources_to_test = [source.lower()]
    else:
        sources_to_test = manager.list_sources()

    if not sources_to_test:
        console.print("\n[dim]No sources configured to test.[/dim]\n")
        raise typer.Exit(0)

    console.print("\n[bold]Testing source connections...[/bold]\n")

    results: list[tuple[str, bool, str]] = []

    for source_name in sources_to_test:
        source_config = manager.get_source_config(source_name)
        if not source_config:
            results.append((source_name, False, "No configuration found"))
            continue

        try:
            adapter = get_adapter(source_name)

            # First authenticate with stored config
            asyncio.run(adapter.authenticate(source_config))

            # Then test connection
            success = asyncio.run(adapter.test_connection())
            if success:
                results.append((source_name, True, "Connected"))
            else:
                results.append((source_name, False, "Connection test failed"))

        except AuthenticationError as e:
            results.append((source_name, False, f"Auth error: {e}"))
        except SourceUnavailableError as e:
            results.append((source_name, False, f"Unavailable: {e}"))
        except Exception as e:
            results.append((source_name, False, f"Error: {e}"))

    # Display results
    table = Table(title="Connection Test Results")
    table.add_column("Source", style="cyan")
    table.add_column("Status")
    table.add_column("Message")

    for source_name, success, message in results:
        status = "[green]OK[/green]" if success else "[red]FAIL[/red]"
        table.add_row(source_name, status, message)

    console.print(table)
    console.print()

    # Exit with error if any tests failed
    if any(not success for _, success, _ in results):
        raise typer.Exit(1)


@app.command("migrate")
def migrate_config() -> None:
    """Migrate config.yaml to .mcp.json format.

    Converts the legacy config.yaml format to the new .mcp.json format,
    creating a backup of the original file.
    """
    from devassist.models.runner_config import AIProviderConfig, MCPConfig, VertexConfig

    manager = ConfigManager()
    legacy_path = manager.workspace_dir / "config.yaml"
    mcp_path = manager.workspace_dir / ".mcp.json"

    # Check if legacy config exists
    if not legacy_path.exists():
        console.print("\n[yellow]No config.yaml found to migrate.[/yellow]")
        console.print("Already using .mcp.json or no configuration exists.\n")
        return

    # Check if .mcp.json already exists
    if mcp_path.exists():
        console.print("\n[yellow].mcp.json already exists![/yellow]")
        overwrite = Prompt.ask(
            "Overwrite existing .mcp.json?",
            choices=["y", "n"],
            default="n",
        )
        if overwrite.lower() != "y":
            console.print("Migration cancelled.")
            raise typer.Exit(0)

    console.print("\n[bold]Migrating config.yaml to .mcp.json...[/bold]\n")

    # Load legacy config
    legacy_config = manager._load_legacy_config(legacy_path)

    # Transform to MCPConfig
    mcp_config = MCPConfig(
        version="1.0",
        ai=AIProviderConfig(
            provider="vertex",  # Default to vertex if they had AI configured
            vertex=VertexConfig(
                api_key=legacy_config.ai.api_key,
                project_id=legacy_config.ai.project_id,
                location=legacy_config.ai.location,
                model=legacy_config.ai.model,
            ),
        ),
        sources=legacy_config.sources,
    )

    # Save new config
    manager.save_config(mcp_config)

    # Backup legacy config
    backup_path = manager.workspace_dir / "config.yaml.bak"
    import shutil
    shutil.copy(legacy_path, backup_path)

    console.print(f"[green]Migration successful![/green]")
    console.print(f"- New config: {mcp_path}")
    console.print(f"- Backup: {backup_path}")
    console.print("\n[dim]You can safely delete config.yaml.bak after verifying the migration.[/dim]\n")
