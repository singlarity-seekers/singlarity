"""Prompt execution CLI commands for DevAssist.

Commands for executing built-in and custom prompts.
"""

import asyncio
import json
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from devassist.ai.prompt_registry import PromptRegistry
from devassist.core.prompt_executor import PromptExecutor
from devassist.models.prompt import PromptExecutionResult

console = Console()


def display_result(result: PromptExecutionResult, json_output: bool = False) -> None:
    """Display prompt execution result.

    Args:
        result: The execution result to display.
        json_output: Whether to output as JSON instead of formatted text.
    """
    if json_output:
        output = {
            "prompt_id": result.prompt_id,
            "text": result.generated_text,
            "format": result.format.value,
            "context_items": result.context_items_count,
            "execution_time": result.execution_time_seconds,
            "sources_used": result.sources_used,
            "sources_failed": result.sources_failed,
            "generated_at": result.generated_at.isoformat(),
        }
        console.print_json(json.dumps(output, indent=2))
    else:
        # Format based on output type
        if result.format.value == "markdown":
            console.print(Markdown(result.generated_text))
        else:
            console.print(Panel(result.generated_text, border_style="blue"))

        # Show metadata
        console.print(
            f"\n[dim]Context items: {result.context_items_count} | "
            f"Sources: {', '.join(result.sources_used)} | "
            f"Time: {result.execution_time_seconds:.2f}s[/dim]"
        )

        if result.sources_failed:
            console.print(
                f"[yellow]Warning: Failed to fetch from: {', '.join(result.sources_failed)}[/yellow]"
            )


def standup(
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Bypass cache and fetch fresh data"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """Generate daily standup summary (Yesterday/Today/Blockers)."""
    console.print("[dim]Generating standup summary...[/dim]")

    try:
        executor = PromptExecutor()
        result = asyncio.run(executor.execute("standup", refresh=refresh))
        display_result(result, json_output)
    except Exception as e:
        console.print(f"[red]Error generating standup:[/red] {e}")
        raise typer.Exit(1)


def weekly(
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Bypass cache and fetch fresh data"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """Generate weekly retrospective summary."""
    console.print("[dim]Generating weekly summary...[/dim]")

    try:
        executor = PromptExecutor()
        result = asyncio.run(executor.execute("weekly", refresh=refresh))
        display_result(result, json_output)
    except Exception as e:
        console.print(f"[red]Error generating weekly summary:[/red] {e}")
        raise typer.Exit(1)


def meeting_prep(
    topic: str = typer.Argument(..., help="Meeting topic or title"),
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Bypass cache and fetch fresh data"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """Prepare context brief for an upcoming meeting."""
    console.print(f"[dim]Preparing context for meeting: {topic}...[/dim]")

    try:
        executor = PromptExecutor()
        result = asyncio.run(
            executor.execute(
                "meeting-prep", refresh=refresh, context_kwargs={"meeting_topic": topic}
            )
        )
        display_result(result, json_output)
    except Exception as e:
        console.print(f"[red]Error generating meeting prep:[/red] {e}")
        raise typer.Exit(1)


def pr_summary(
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Bypass cache and fetch fresh data"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """Summarize pull request activity."""
    console.print("[dim]Summarizing PR activity...[/dim]")

    try:
        executor = PromptExecutor()
        result = asyncio.run(executor.execute("pr-summary", refresh=refresh))
        display_result(result, json_output)
    except Exception as e:
        console.print(f"[red]Error generating PR summary:[/red] {e}")
        raise typer.Exit(1)


def ask(
    prompt: str = typer.Argument(..., help="Your custom prompt or question"),
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
    """Ask a custom question with optional context aggregation."""
    if no_context:
        console.print("[dim]Executing custom prompt (no context)...[/dim]")
    else:
        console.print(f"[dim]Executing custom prompt (context: last {hours}h)...[/dim]")

    try:
        executor = PromptExecutor()
        result = asyncio.run(
            executor.execute_custom(
                user_prompt=prompt,
                include_context=not no_context,
                time_window_hours=hours,
                temperature=temperature,
            )
        )
        display_result(result, json_output)
    except Exception as e:
        console.print(f"[red]Error executing custom prompt:[/red] {e}")
        raise typer.Exit(1)


def list_prompts() -> None:
    """List all available prompt templates."""
    templates = PromptRegistry.list_all()

    if not templates:
        console.print("[dim]No prompts available.[/dim]")
        return

    console.print("\n[bold]Available Prompts:[/bold]\n")

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="white", no_wrap=True)
    table.add_column("Description", style="dim")
    table.add_column("Tags", style="magenta")

    for template in templates:
        tags_str = ", ".join(template.tags) if template.tags else "-"
        table.add_row(
            template.id,
            template.name,
            template.description[:60] + "..."
            if len(template.description) > 60
            else template.description,
            tags_str,
        )

    console.print(table)
    console.print()
