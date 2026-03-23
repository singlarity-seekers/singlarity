"""Security notices shared across CLI commands."""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


def show_security_warning(console: Console | None = None) -> None:
    """Display security warning about credential storage (FR-004 dev mode)."""
    c = console or Console()
    config_path = Path.home() / ".devassist" / "config.yaml"
    warning_text = Text()
    warning_text.append("DEV MODE: ", style="bold yellow")
    warning_text.append(
        f"Credentials are stored in plain text at {config_path}. "
        "Do not use in production without proper secret management."
    )
    c.print(Panel(warning_text, title="Security Notice", border_style="yellow"))
