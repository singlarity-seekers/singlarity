"""Daemon CLI commands for DevAssist.

Provides commands to start, stop, and manage the background monitoring daemon.
"""

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

# Create router for daemon commands
app = typer.Typer(
    name="daemon",
    help="Background monitoring daemon for notifications.",
)

console = Console()

# PID file location
PID_FILE = Path.home() / ".devassist" / "daemon.pid"


def get_daemon_pid() -> int | None:
    """Get the PID of the running daemon, if any.

    Returns:
        PID if daemon is running, None otherwise.
    """
    if not PID_FILE.exists():
        return None

    try:
        pid = int(PID_FILE.read_text().strip())

        # Check if process is actually running
        os.kill(pid, 0)
        return pid

    except (ValueError, ProcessLookupError, PermissionError):
        # PID file is stale
        PID_FILE.unlink(missing_ok=True)
        return None


def write_pid() -> None:
    """Write the current PID to the PID file."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def remove_pid() -> None:
    """Remove the PID file."""
    PID_FILE.unlink(missing_ok=True)


@app.command("start")
def start(
    interval: int = typer.Option(
        300,
        "--interval",
        "-i",
        help="Check interval in seconds (default: 300 = 5 minutes)",
    ),
    foreground: bool = typer.Option(
        False,
        "--foreground",
        "-f",
        help="Run in foreground instead of background",
    ),
    no_desktop: bool = typer.Option(
        False,
        "--no-desktop",
        help="Disable desktop notifications (console output only)",
    ),
) -> None:
    """Start the background monitoring daemon.

    The daemon periodically checks configured MCP sources for new important
    items and sends desktop notifications when action is needed.
    """
    # Check if already running
    existing_pid = get_daemon_pid()
    if existing_pid:
        console.print(f"[yellow]Daemon is already running (PID {existing_pid})[/yellow]")
        console.print("Run [bold]devassist daemon stop[/bold] to stop it first.")
        raise typer.Exit(1)

    # Check for required configuration
    from devassist.mcp.config import MCPConfigLoader

    loader = MCPConfigLoader()
    mcp_config = loader.load()

    if not mcp_config.mcp_servers:
        console.print("[yellow]Warning:[/yellow] No MCP servers configured.")
        console.print("Run [bold]devassist config mcp add <server>[/bold] to configure sources.")
        console.print()

    # Check for Claude credentials (either direct API or Vertex AI)
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    vertex_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("CLOUDSDK_CORE_PROJECT")

    # Try gcloud config as fallback
    if not vertex_project:
        from devassist.core.orchestrator import _get_gcloud_project

        vertex_project = _get_gcloud_project()

    if not has_api_key and not vertex_project:
        console.print("[red]Error:[/red] No Claude credentials found")
        console.print("\nSet one of the following:")
        console.print("  1. ANTHROPIC_API_KEY for direct Anthropic API access")
        console.print("  2. Configure gcloud with: gcloud config set project YOUR_PROJECT")
        raise typer.Exit(1)

    if vertex_project and not has_api_key:
        console.print(f"[dim]Using Vertex AI with project: {vertex_project}[/dim]")

    if foreground:
        # Run in foreground
        console.print(f"[green]Starting daemon in foreground (interval: {interval}s)...[/green]")
        console.print("Press Ctrl+C to stop.\n")

        write_pid()
        try:
            from devassist.daemon.monitor import run_daemon

            asyncio.run(run_daemon(
                check_interval=interval,
                desktop_notifications=not no_desktop,
            ))
        finally:
            remove_pid()
    else:
        # Background mode
        console.print(f"[green]Starting daemon (interval: {interval}s)...[/green]")

        # Fork to background on Unix
        if sys.platform != "win32":
            pid = os.fork()
            if pid > 0:
                # Parent process
                console.print(f"Daemon started with PID {pid}")
                console.print("Run [bold]devassist daemon status[/bold] to check status.")
                console.print("Run [bold]devassist daemon stop[/bold] to stop.")
                raise typer.Exit(0)

            # Child process - detach
            os.setsid()

            # Redirect stdout/stderr to log file
            log_path = Path.home() / ".devassist" / "daemon.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(log_path, "a") as log_file:
                os.dup2(log_file.fileno(), sys.stdout.fileno())
                os.dup2(log_file.fileno(), sys.stderr.fileno())

            write_pid()
            try:
                from devassist.daemon.monitor import run_daemon

                asyncio.run(run_daemon(
                    check_interval=interval,
                    desktop_notifications=not no_desktop,
                ))
            finally:
                remove_pid()
        else:
            # Windows - just run in foreground
            console.print("[yellow]Background mode not supported on Windows.[/yellow]")
            console.print("Running in foreground. Press Ctrl+C to stop.\n")

            write_pid()
            try:
                from devassist.daemon.monitor import run_daemon

                asyncio.run(run_daemon(
                    check_interval=interval,
                    desktop_notifications=not no_desktop,
                ))
            finally:
                remove_pid()


@app.command("stop")
def stop() -> None:
    """Stop the running daemon."""
    pid = get_daemon_pid()

    if not pid:
        console.print("[dim]Daemon is not running.[/dim]")
        raise typer.Exit(0)

    console.print(f"Stopping daemon (PID {pid})...")

    try:
        os.kill(pid, signal.SIGTERM)

        # Wait briefly for graceful shutdown
        import time
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break

        # Check if still running
        try:
            os.kill(pid, 0)
            # Still running, force kill
            os.kill(pid, signal.SIGKILL)
            console.print("[yellow]Daemon force killed.[/yellow]")
        except ProcessLookupError:
            console.print("[green]Daemon stopped.[/green]")

        remove_pid()

    except PermissionError:
        console.print("[red]Error:[/red] Permission denied. Try with sudo?")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error stopping daemon:[/red] {e}")
        raise typer.Exit(1)


@app.command("status")
def status() -> None:
    """Show daemon status."""
    pid = get_daemon_pid()

    if pid:
        console.print(f"[green]Daemon is running[/green] (PID {pid})")

        # Show log tail if available
        log_path = Path.home() / ".devassist" / "daemon.log"
        if log_path.exists():
            console.print(f"\nLog file: {log_path}")

            # Show last few lines
            try:
                lines = log_path.read_text().strip().split("\n")
                if lines:
                    console.print("\n[dim]Recent log entries:[/dim]")
                    for line in lines[-5:]:
                        console.print(f"  {line}")
            except Exception:
                pass

    else:
        console.print("[dim]Daemon is not running.[/dim]")
        console.print("Run [bold]devassist daemon start[/bold] to start it.")


@app.command("logs")
def logs(
    follow: bool = typer.Option(
        False,
        "--follow",
        "-f",
        help="Follow log output (like tail -f)",
    ),
    lines: int = typer.Option(
        20,
        "--lines",
        "-n",
        help="Number of lines to show",
    ),
) -> None:
    """View daemon logs."""
    log_path = Path.home() / ".devassist" / "daemon.log"

    if not log_path.exists():
        console.print("[dim]No log file found.[/dim]")
        console.print("The daemon hasn't been run yet, or logs have been cleared.")
        raise typer.Exit(0)

    if follow:
        console.print(f"[dim]Following {log_path} (Ctrl+C to stop)...[/dim]\n")

        import subprocess
        try:
            subprocess.run(["tail", "-f", str(log_path)])
        except KeyboardInterrupt:
            pass
    else:
        # Show last N lines
        try:
            all_lines = log_path.read_text().strip().split("\n")
            for line in all_lines[-lines:]:
                console.print(line)
        except Exception as e:
            console.print(f"[red]Error reading logs:[/red] {e}")
            raise typer.Exit(1)
