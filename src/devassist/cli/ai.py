"""AI CLI commands for DevAssist.

Provides commands for managing the background AI runner.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from devassist.ai.agent_client import AgentClient
from devassist.ai.prompts import get_runner_system_prompt
from devassist.core.config_manager import ConfigManager
from devassist.core.runner_manager import RunnerManager
from devassist.models.mcp_config import MCPConfig

# Create router for AI commands
app = typer.Typer(
    name="ai",
    help="Manage background AI runner.",
    no_args_is_help=True,
)

console = Console()


def get_ai_client(config: MCPConfig):
    """Create AI client based on configuration.

    Supports three modes:
    1. Vertex AI via CLAUDE_CODE_USE_VERTEX=1 (uses GCP Application Default Credentials)
    2. Claude API via api_key in config
    3. Vertex AI (Gemini) via config.ai.provider == "vertex"

    Args:
        config: MCP configuration.

    Returns:
        Configured AI client (Claude or Vertex).

    Raises:
        RuntimeError: If no valid authentication configured.
    """
    # Check for Vertex AI mode via environment variable (Claude on Vertex)
    use_vertex_auth = os.environ.get("CLAUDE_CODE_USE_VERTEX", "").lower() in ("1", "true")

    if config.ai.provider == "claude":
        from devassist.ai.claude_client import ClaudeClient

        if use_vertex_auth:
            # Use Vertex AI authentication (GCP ADC)
            project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
            region = os.environ.get("CLOUD_ML_REGION", "us-east5")

            if not project_id:
                raise RuntimeError(
                    "Vertex AI mode requires ANTHROPIC_VERTEX_PROJECT_ID env var. "
                    "Run: export ANTHROPIC_VERTEX_PROJECT_ID=your-project-id"
                )

            return ClaudeClient(
                model=config.ai.claude.model,
                max_tokens=config.ai.claude.max_tokens,
                temperature=config.ai.claude.temperature,
                project_id=project_id,
                region=region,
            )
        else:
            # Use direct Anthropic API key
            api_key = config.ai.claude.api_key
            if not api_key:
                raise RuntimeError(
                    "Claude API key not configured. Either:\n"
                    "  1. Set ANTHROPIC_API_KEY env var, or\n"
                    "  2. Add api_key to .mcp.json, or\n"
                    "  3. Set CLAUDE_CODE_USE_VERTEX=1 for Vertex AI auth"
                )
            return ClaudeClient(
                api_key=api_key,
                model=config.ai.claude.model,
                max_tokens=config.ai.claude.max_tokens,
                temperature=config.ai.claude.temperature,
            )
    else:
        from devassist.ai.vertex_client import VertexAIClient

        return VertexAIClient(
            api_key=config.ai.vertex.api_key,
            project_id=config.ai.vertex.project_id,
            location=config.ai.vertex.location,
            model=config.ai.vertex.model,
        )


def get_agent_client() -> AgentClient:
    """Create an AgentClient with session management.

    Returns:
        Configured AgentClient.
    """
    return AgentClient(
        system_prompt=get_runner_system_prompt(),
    )


def run_background_runner() -> None:
    """Entry point for background runner process.

    This function is called in a separate process and runs the runner loop.
    Uses AgentClient for automatic session management.

    Reads CLI options from environment variables:
    - DEVASSIST_RUNNER_INTERVAL: Interval in minutes
    - DEVASSIST_RUNNER_PROMPT: Custom prompt
    """
    import asyncio
    import logging

    from devassist.core.aggregator import ContextAggregator
    from devassist.core.runner import Runner

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Load configuration
    manager = ConfigManager()
    config = manager.load_config()

    if not isinstance(config, MCPConfig):
        logging.error("Legacy config.yaml not supported for runner. Use .mcp.json")
        return

    # Override config with environment variables (from CLI flags)
    if interval_str := os.environ.get("DEVASSIST_RUNNER_INTERVAL"):
        try:
            config.runner.interval_minutes = int(interval_str)
        except ValueError:
            logging.warning(f"Invalid interval value: {interval_str}")

    if prompt := os.environ.get("DEVASSIST_RUNNER_PROMPT"):
        config.runner.prompt = prompt

    # Create AgentClient with session management
    ai_client = get_agent_client()

    # Create aggregator
    aggregator = ContextAggregator()

    # Create and run runner
    runner = Runner(
        config=config,
        ai_client=ai_client,
        aggregator=aggregator,
    )

    # Run the event loop
    asyncio.run(runner.run())


@app.command("run")
def run_runner(
    interval: Optional[int] = typer.Option(
        None,
        "--interval",
        "-i",
        help="Interval in minutes between executions.",
    ),
    prompt: Optional[str] = typer.Option(
        None,
        "--prompt",
        "-p",
        help="Custom prompt to execute.",
    ),
    foreground: bool = typer.Option(
        False,
        "--foreground",
        "-f",
        help="Run in foreground instead of background.",
    ),
) -> None:
    """Start the background AI runner.

    The runner executes a custom prompt at regular intervals using context
    from configured sources.
    """
    # Load configuration
    manager = ConfigManager()
    config = manager.load_config()

    if not isinstance(config, MCPConfig):
        console.print("[red]Error:[/red] Legacy config.yaml not supported for runner.")
        console.print("Run [bold]devassist config migrate[/bold] to upgrade.")
        raise typer.Exit(1)

    # Update config with CLI options
    if interval is not None:
        config.runner.interval_minutes = interval
    if prompt is not None:
        config.runner.prompt = prompt

    # Create runner manager
    runner_manager = RunnerManager()

    # Check if already running
    if runner_manager.is_running():
        status = runner_manager.get_status()
        console.print(f"[yellow]Runner is already running (PID: {status.pid})[/yellow]")
        console.print("Run [bold]devassist ai kill[/bold] to stop it first.")
        raise typer.Exit(1)

    if foreground:
        # Run in foreground
        console.print("[bold]Starting AI runner in foreground...[/bold]")
        console.print(f"  Interval: {config.runner.interval_minutes} minutes")
        console.print(f"  Prompt: {config.runner.prompt[:50]}...")
        console.print("  Session: Managed by Agent SDK (auto-resume)")
        console.print("\nPress Ctrl+C to stop.\n")

        import asyncio

        from devassist.core.aggregator import ContextAggregator
        from devassist.core.runner import Runner

        ai_client = get_agent_client()
        aggregator = ContextAggregator()
        runner = Runner(
            config=config,
            ai_client=ai_client,
            aggregator=aggregator,
        )

        try:
            asyncio.run(runner.run())
        except KeyboardInterrupt:
            console.print("\n[yellow]Runner stopped by user.[/yellow]")

    else:
        # Run in background
        try:
            runner_manager.start(interval=interval, prompt=prompt)
            status = runner_manager.get_status()

            console.print(
                Panel(
                    f"[green]Background AI runner started[/green]\n\n"
                    f"  PID: {status.pid}\n"
                    f"  Interval: {config.runner.interval_minutes} minutes\n"
                    f"  Prompt: {config.runner.prompt[:50]}...\n"
                    f"  Output: {config.runner.output_destination}\n"
                    f"  Logs: {runner_manager.get_log_path()}",
                    title="Runner Started",
                    border_style="green",
                )
            )

            console.print("\nRun [bold]devassist ai status[/bold] to check progress")
            console.print("Run [bold]devassist ai kill[/bold] to stop")

        except RuntimeError as e:
            console.print(f"[red]Error starting runner:[/red] {e}")
            raise typer.Exit(1)


@app.command("kill")
def kill_runner(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force kill without graceful shutdown.",
    ),
) -> None:
    """Stop the background AI runner."""
    runner_manager = RunnerManager()

    if not runner_manager.is_running():
        console.print("[yellow]No runner is currently running.[/yellow]")
        return

    status = runner_manager.get_status()
    console.print(f"Stopping runner (PID: {status.pid})...")

    try:
        runner_manager.stop(force=force)
        console.print("[green]Runner stopped successfully.[/green]")
    except Exception as e:
        console.print(f"[red]Error stopping runner:[/red] {e}")
        raise typer.Exit(1)


@app.command("status")
def show_status() -> None:
    """Show current runner status."""
    runner_manager = RunnerManager()
    manager = ConfigManager()
    config = manager.load_config()

    status = runner_manager.get_status()

    # Check session status
    agent_client = get_agent_client()
    has_session = agent_client.session_id is not None

    # Build status table
    table = Table(show_header=False, box=None)
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    if status.status == "running":
        table.add_row("Status", f"[green]Running[/green] (PID: {status.pid})")
    else:
        table.add_row("Status", "[dim]Not running[/dim]")

    if isinstance(config, MCPConfig):
        table.add_row("Interval", f"{config.runner.interval_minutes} minutes")
        table.add_row("AI Provider", "Claude Agent SDK")

        if has_session:
            table.add_row("Session", f"[green]Active[/green] ({agent_client.session_id[:8]}...)")
        else:
            table.add_row("Session", "[dim]None (will create on first run)[/dim]")

        table.add_row("Output File", config.runner.output_destination)

        if config.runner.sources:
            table.add_row("Sources", ", ".join(config.runner.sources))
        else:
            table.add_row("Sources", "[dim]All configured[/dim]")

    table.add_row("Logs", str(runner_manager.get_log_path()))

    console.print()
    console.print(Panel(table, title="AI Runner Status", border_style="blue"))
    console.print()


@app.command("logs")
def show_logs(
    follow: bool = typer.Option(
        False,
        "--follow",
        "-f",
        help="Follow log output (like tail -f).",
    ),
    lines: int = typer.Option(
        50,
        "--lines",
        "-n",
        help="Number of lines to show.",
    ),
) -> None:
    """Show runner logs."""
    runner_manager = RunnerManager()
    log_path = runner_manager.get_log_path()

    if not log_path.exists():
        console.print("[yellow]No log file found.[/yellow]")
        console.print("The runner may not have been started yet.")
        return

    if follow:
        # Follow mode - use tail -f behavior
        console.print(f"[dim]Following {log_path} (Ctrl+C to stop)[/dim]\n")

        import subprocess

        try:
            subprocess.run(["tail", "-f", str(log_path)])
        except KeyboardInterrupt:
            pass
    else:
        # Show last N lines
        content = log_path.read_text()
        log_lines = content.strip().split("\n")

        if len(log_lines) > lines:
            log_lines = log_lines[-lines:]

        if log_lines:
            console.print(f"[dim]Last {len(log_lines)} lines from {log_path}:[/dim]\n")
            for line in log_lines:
                console.print(line)
        else:
            console.print("[yellow]Log file is empty.[/yellow]")


@app.command("clear")
def clear_session() -> None:
    """Clear the runner session (conversation history).

    This resets the conversation history so the next run starts fresh.
    Use this at the start of a new day or when you want a clean slate.
    """
    agent_client = get_agent_client()

    # Check if there's a session to clear
    if agent_client.session_id:
        agent_client.clear_session()
        console.print("[green]Session cleared successfully.[/green]")
        console.print("The next run will start a fresh conversation.")
    else:
        console.print("[yellow]No active session to clear.[/yellow]")
