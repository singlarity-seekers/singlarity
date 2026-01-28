"""Prompt execution CLI commands for DevAssist.

Commands for executing built-in and custom prompts.
"""

import asyncio
import json

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from devassist.ai.prompt_registry import PromptRegistry
from devassist.core.prompt_executor import PromptExecutor
from devassist.models.prompt import PromptExecutionResult

console = Console()

# Mapping of command names to prompt template IDs
PROMPT_COMMANDS = {
    "standup": "standup",
    "weekly": "weekly",
    "meeting-prep": "meeting-prep",
    "pr-summary": "pr-summary",
    "list": "__list__",  # Special command to list prompts
}


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
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Name", style="white", no_wrap=True)
    table.add_column("Description", style="dim")
    table.add_column("Tags", style="magenta")

    for template in templates:
        tags_str = ", ".join(template.tags) if template.tags else "-"
        # Find the command for this template
        cmd = next(
            (cmd for cmd, tid in PROMPT_COMMANDS.items() if tid == template.id),
            template.id,
        )
        table.add_row(
            cmd,
            template.name,
            template.description[:60] + "..."
            if len(template.description) > 60
            else template.description,
            tags_str,
        )

    console.print(table)
    console.print("\n[dim]Use: devassist prompt <command> to run a built-in prompt[/dim]")
    console.print("[dim]Use: devassist \"your question\" for custom queries (default)[/dim]")
    console.print("[dim]Examples: devassist prompt standup, devassist \"What's urgent?\"[/dim]\n")


def prompt(
    query: list[str] = typer.Argument(..., help="Command (standup/weekly/etc) or custom question"),
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Bypass cache and fetch fresh data"
    ),
    no_context: bool = typer.Option(
        False,
        "--no-context",
        help="Don't include aggregated context (for custom questions only)",
    ),
    hours: int = typer.Option(
        24,
        "--hours",
        "-h",
        help="Context time window in hours (for custom questions, default: 24)",
    ),
    temperature: float = typer.Option(
        0.5,
        "--temperature",
        "-t",
        help="AI temperature for generation (for custom questions, 0.0-2.0, default: 0.5)",
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """Execute a prompt template or ask a custom question.

    Examples:
        devassist prompt standup              # Run daily standup prompt
        devassist prompt weekly               # Run weekly retrospective
        devassist prompt meeting-prep "Sprint Planning"  # Meeting prep with topic
        devassist prompt pr-summary           # PR activity summary
        devassist prompt list                 # List available prompts
        devassist prompt "What are the urgent issues?"    # Custom question with context
        devassist prompt "Explain decorators" --no-context  # Pure AI query
    """
    # Check if first argument is a known command
    first_arg = query[0].lower()

    # Special case: list command
    if first_arg == "list":
        list_prompts()
        return

    # Check if it's a known prompt command
    if first_arg in PROMPT_COMMANDS:
        command = first_arg
        args = " ".join(query[1:]) if len(query) > 1 else None
        prompt_id = PROMPT_COMMANDS[command]

        try:
            executor = PromptExecutor()

            # Handle commands that need additional arguments
            if command == "meeting-prep":
                if not args:
                    console.print("[red]Error: meeting-prep requires a topic[/red]")
                    console.print("Example: devassist prompt meeting-prep \"Sprint Planning\"")
                    raise typer.Exit(1)
                console.print(f"[dim]Preparing context for meeting: {args}...[/dim]")
                result = asyncio.run(
                    executor.execute(
                        prompt_id, refresh=refresh, context_kwargs={"meeting_topic": args}
                    )
                )
            else:
                console.print(f"[dim]Running {command}...[/dim]")
                result = asyncio.run(executor.execute(prompt_id, refresh=refresh))

            display_result(result, json_output)
        except Exception as e:
            console.print(f"[red]Error executing {command}:[/red] {e}")
            raise typer.Exit(1)
    else:
        # Handle custom questions
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
            console.print(f"[red]Error executing custom question:[/red] {e}")
            raise typer.Exit(1)
