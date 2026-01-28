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
from devassist.mcp.config import MCPConfigLoader, MCPServerConfig
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


# MCP subcommand group
mcp_app = typer.Typer(
    name="mcp",
    help="Manage MCP (Model Context Protocol) server configurations.",
    no_args_is_help=True,
)
app.add_typer(mcp_app, name="mcp")


# Available MCP server templates
MCP_SERVER_TEMPLATES = {
    "github": {
        "display_name": "GitHub",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env_vars": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "description": "GitHub notifications, PRs, and issues",
    },
    "slack": {
        "display_name": "Slack",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env_vars": ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
        "description": "Slack messages and mentions",
    },
    "jira": {
        "display_name": "JIRA",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-atlassian"],
        "env_vars": ["ATLASSIAN_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN"],
        "description": "JIRA issues and tasks",
    },
}


@mcp_app.command("add")
def mcp_add(
    server: str = typer.Argument(
        ...,
        help="MCP server to add (github, slack, jira) or 'custom' for manual config",
    ),
) -> None:
    """Add an MCP server configuration.

    Guides through the setup for connecting to an MCP server.
    Environment variables are used for sensitive values.
    """
    show_security_warning()
    console.print()

    loader = MCPConfigLoader()
    server_name = server.lower()

    if server_name == "custom":
        # Custom server configuration
        console.print("[bold]Custom MCP Server Configuration[/bold]\n")

        name = Prompt.ask("Server name (e.g., 'myserver')")
        server_type = Prompt.ask("Server type", choices=["stdio", "http", "sse"], default="stdio")

        if server_type == "stdio":
            command = Prompt.ask("Command to run (e.g., 'npx')")
            args_str = Prompt.ask("Arguments (comma-separated)", default="")
            args = [a.strip() for a in args_str.split(",") if a.strip()]

            env_str = Prompt.ask("Environment variables (KEY=value, comma-separated)", default="")
            env = {}
            for pair in env_str.split(","):
                if "=" in pair:
                    key, val = pair.split("=", 1)
                    env[key.strip()] = val.strip()

            server_config = MCPServerConfig(
                type="stdio",
                command=command,
                args=args,
                env=env,
                enabled=True,
            )
        else:
            url = Prompt.ask("Server URL")
            headers_str = Prompt.ask("Headers (Key:Value, comma-separated)", default="")
            headers = {}
            for pair in headers_str.split(","):
                if ":" in pair:
                    key, val = pair.split(":", 1)
                    headers[key.strip()] = val.strip()

            server_config = MCPServerConfig(
                type=server_type,
                url=url,
                headers=headers,
                enabled=True,
            )

        loader.set_server(name, server_config)
        console.print(f"\n[green]Custom MCP server '{name}' configured![/green]")

    elif server_name in MCP_SERVER_TEMPLATES:
        template = MCP_SERVER_TEMPLATES[server_name]
        console.print(f"[bold]Configuring {template['display_name']} MCP Server[/bold]")
        console.print(f"[dim]{template['description']}[/dim]\n")

        # Check for required environment variables
        missing_vars = []
        env_config = {}

        for var in template["env_vars"]:
            import os
            if os.environ.get(var):
                env_config[var] = f"${{{var}}}"  # Use env var reference
                console.print(f"[green]Found {var}[/green] in environment")
            else:
                missing_vars.append(var)

        if missing_vars:
            console.print(f"\n[yellow]Missing environment variables:[/yellow] {', '.join(missing_vars)}")
            console.print("Set these before running devassist brief:\n")
            for var in missing_vars:
                console.print(f"  export {var}='your-value-here'")

            # Ask if they want to set values now
            set_now = Prompt.ask("\nSet values now?", choices=["y", "n"], default="n")
            if set_now.lower() == "y":
                for var in missing_vars:
                    value = Prompt.ask(f"  {var}", password=True)
                    env_config[var] = value
            else:
                # Use env var references
                for var in missing_vars:
                    env_config[var] = f"${{{var}}}"

        # Create server config
        server_config = MCPServerConfig(
            type=template["type"],
            command=template["command"],
            args=template["args"],
            env=env_config,
            enabled=True,
        )

        loader.set_server(server_name, server_config)
        console.print(f"\n[green]{template['display_name']} MCP server configured![/green]")
        console.print(f"Run [bold]devassist config mcp list[/bold] to see all servers.\n")

    else:
        available = ", ".join(MCP_SERVER_TEMPLATES.keys())
        console.print(f"[red]Error:[/red] Unknown server '{server}'")
        console.print(f"Available: {available}, custom")
        raise typer.Exit(1)


@mcp_app.command("list")
def mcp_list() -> None:
    """List all configured MCP servers."""
    loader = MCPConfigLoader()
    servers = loader.list_servers()

    if not servers:
        console.print("\n[dim]No MCP servers configured yet.[/dim]")
        console.print("Run [bold]devassist config mcp add <server>[/bold] to get started.\n")

        console.print("Available MCP servers:")
        for name, template in MCP_SERVER_TEMPLATES.items():
            console.print(f"  - {template['display_name']} ({name}) - {template['description']}")
        console.print("  - custom - Configure a custom MCP server")
        console.print()
        return

    table = Table(title="Configured MCP Servers")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Command/URL", style="white")
    table.add_column("Status", style="green")

    for name in servers:
        config = loader.get_server(name)
        if not config:
            continue

        status = "[green]Enabled[/green]" if config.enabled else "[dim]Disabled[/dim]"

        if config.type == "stdio":
            location = f"{config.command} {' '.join(config.args[:2])}..."
        else:
            location = config.url or "-"

        table.add_row(name, config.type, location[:40], status)

    console.print()
    console.print(table)
    console.print()


@mcp_app.command("remove")
def mcp_remove(
    server: str = typer.Argument(
        ...,
        help="MCP server to remove",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Remove without confirmation",
    ),
) -> None:
    """Remove an MCP server configuration."""
    loader = MCPConfigLoader()

    if server.lower() not in loader.list_servers():
        console.print(f"[red]Error:[/red] MCP server '{server}' is not configured.")
        raise typer.Exit(1)

    if not force:
        confirm = Prompt.ask(
            f"Remove MCP server '{server}'?",
            choices=["y", "n"],
            default="n",
        )
        if confirm.lower() != "y":
            console.print("Cancelled.")
            raise typer.Exit(0)

    loader.remove_server(server.lower())
    console.print(f"[green]Removed MCP server '{server}'.[/green]")


@mcp_app.command("test")
def mcp_test(
    server: Optional[str] = typer.Argument(
        None,
        help="MCP server to test. Tests all if not specified.",
    ),
) -> None:
    """Test MCP server configurations.

    Note: This currently only validates configuration, not actual connectivity.
    """
    import os

    loader = MCPConfigLoader()
    servers_to_test = []

    if server:
        if server.lower() not in loader.list_servers():
            console.print(f"[red]Error:[/red] MCP server '{server}' is not configured.")
            raise typer.Exit(1)
        servers_to_test = [server.lower()]
    else:
        servers_to_test = loader.list_servers()

    if not servers_to_test:
        console.print("\n[dim]No MCP servers configured to test.[/dim]\n")
        raise typer.Exit(0)

    console.print("\n[bold]Testing MCP server configurations...[/bold]\n")

    results: list[tuple[str, bool, str]] = []

    for name in servers_to_test:
        config = loader.get_server(name)
        if not config:
            results.append((name, False, "Configuration not found"))
            continue

        # Check if required env vars are set
        missing_vars = []
        for key, value in config.env.items():
            if value.startswith("${") and value.endswith("}"):
                var_name = value[2:-1]
                if not os.environ.get(var_name):
                    missing_vars.append(var_name)

        if missing_vars:
            results.append((name, False, f"Missing env vars: {', '.join(missing_vars)}"))
        elif config.type == "stdio" and not config.command:
            results.append((name, False, "No command specified"))
        elif config.type in ("http", "sse") and not config.url:
            results.append((name, False, "No URL specified"))
        else:
            results.append((name, True, "Configuration valid"))

    # Display results
    table = Table(title="MCP Configuration Test Results")
    table.add_column("Server", style="cyan")
    table.add_column("Status")
    table.add_column("Message")

    for name, success, message in results:
        status = "[green]OK[/green]" if success else "[red]FAIL[/red]"
        table.add_row(name, status, message)

    console.print(table)
    console.print()

    if any(not success for _, success, _ in results):
        raise typer.Exit(1)


# User profile subcommand group
user_app = typer.Typer(
    name="user",
    help="Manage user profile settings for personalized briefs.",
    no_args_is_help=True,
)
app.add_typer(user_app, name="user")


@user_app.command("set")
def user_set(
    github_username: Optional[str] = typer.Option(
        None, "--github", "-g", help="Your GitHub username"
    ),
    github_orgs: Optional[str] = typer.Option(
        None, "--orgs", "-o", help="GitHub organizations (comma-separated)"
    ),
    email: Optional[str] = typer.Option(
        None, "--email", "-e", help="Your email address"
    ),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Your display name"
    ),
    jira_username: Optional[str] = typer.Option(
        None, "--jira", help="Your JIRA username"
    ),
) -> None:
    """Set user profile information for personalized briefs.

    Example:
        devassist config user set --github myusername --orgs "myorg,company"
    """
    manager = ConfigManager()
    config = manager.load_config()

    updated = False

    if github_username is not None:
        config.user.github_username = github_username
        console.print(f"[green]Set GitHub username:[/green] {github_username}")
        updated = True

    if github_orgs is not None:
        orgs = [o.strip() for o in github_orgs.split(",") if o.strip()]
        config.user.github_orgs = orgs
        console.print(f"[green]Set GitHub orgs:[/green] {', '.join(orgs)}")
        updated = True

    if email is not None:
        config.user.email = email
        console.print(f"[green]Set email:[/green] {email}")
        updated = True

    if name is not None:
        config.user.name = name
        console.print(f"[green]Set name:[/green] {name}")
        updated = True

    if jira_username is not None:
        config.user.jira_username = jira_username
        console.print(f"[green]Set JIRA username:[/green] {jira_username}")
        updated = True

    if updated:
        manager.save_config(config)
        console.print("\n[dim]User profile saved.[/dim]")
    else:
        console.print("[yellow]No options provided. Use --help to see available options.[/yellow]")


@user_app.command("show")
def user_show() -> None:
    """Show current user profile settings."""
    manager = ConfigManager()
    config = manager.load_config()
    user = config.user

    console.print("\n[bold]User Profile[/bold]\n")

    table = Table(show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Name", user.name or "[dim]Not set[/dim]")
    table.add_row("Email", user.email or "[dim]Not set[/dim]")
    table.add_row("GitHub Username", user.github_username or "[dim]Not set[/dim]")
    table.add_row("GitHub Orgs", ", ".join(user.github_orgs) if user.github_orgs else "[dim]Not set[/dim]")
    table.add_row("JIRA Username", user.jira_username or "[dim]Not set[/dim]")

    console.print(table)
    console.print()

    if not any([user.name, user.email, user.github_username]):
        console.print("[dim]Tip: Set your GitHub username for personalized briefs:[/dim]")
        console.print("  devassist config user set --github YOUR_USERNAME\n")
