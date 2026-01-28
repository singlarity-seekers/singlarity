"""Prompt registry for DevAssist.

Central registry for managing prompt templates.
"""

from devassist.models.prompt import OutputFormat, PromptTemplate


class PromptRegistry:
    """Central registry for prompt templates."""

    _templates: dict[str, PromptTemplate] = {}

    @classmethod
    def register(cls, template: PromptTemplate) -> None:
        """Register a prompt template.

        Args:
            template: PromptTemplate to register.
        """
        cls._templates[template.id] = template

    @classmethod
    def get(cls, prompt_id: str) -> PromptTemplate:
        """Get a prompt template by ID.

        Args:
            prompt_id: Unique prompt identifier.

        Returns:
            PromptTemplate for the given ID.

        Raises:
            ValueError: If prompt ID is not registered.
        """
        if prompt_id not in cls._templates:
            raise ValueError(
                f"Unknown prompt: '{prompt_id}'. "
                f"Available prompts: {', '.join(cls._templates.keys())}"
            )
        return cls._templates[prompt_id]

    @classmethod
    def list_all(cls) -> list[PromptTemplate]:
        """List all registered templates.

        Returns:
            List of all PromptTemplates.
        """
        return list(cls._templates.values())

    @classmethod
    def clear(cls) -> None:
        """Clear all registered templates (for testing)."""
        cls._templates.clear()


# ============================================================================
# Built-in Prompt Definitions
# ============================================================================

STANDUP_PROMPT = PromptTemplate(
    id="standup",
    name="Daily Standup",
    description="Generate Yesterday/Today/Blockers summary for team standup",
    system_prompt="""You are a helpful assistant that creates structured standup summaries.

Output MUST be in YAML format with exactly these three sections:
- yesterday: List of completed work
- today: List of planned work
- blockers: List of impediments (or ["None"] if no blockers)

Guidelines:
- Be concise. Each item should be one line.
- Maximum 5 items per section.
- Focus on concrete deliverables and tasks.
- For blockers, explicitly state "None" if there are no blockers.
- Use action-oriented language.""",
    user_prompt_template="""Based on the following context from the last 24 hours, create a standup summary:

{context}

Generate a YAML-formatted standup with yesterday/today/blockers sections.""",
    temperature=0.2,  # Lower for more structured output
    max_output_tokens=512,
    time_window_hours=24,
    output_format=OutputFormat.STRUCTURED_YAML,
    tags=["daily", "team", "agile"],
)

WEEKLY_SUMMARY_PROMPT = PromptTemplate(
    id="weekly",
    name="Weekly Summary",
    description="Generate a comprehensive weekly retrospective",
    system_prompt="""You are a helpful assistant that creates weekly retrospectives for developers.

Output in Markdown format with these sections:

# Week in Review (DATE_RANGE)

## Key Accomplishments
- Major wins and completed work

## Challenges & Learnings
- Problems solved, lessons learned

## Next Week's Priorities
- Top priorities for upcoming week

## Metrics & Activity
- PR count, issues closed, meetings attended

Guidelines:
- Be specific and actionable.
- Use bullet points for readability.
- Highlight patterns and themes across the week.
- Keep it professional but conversational.""",
    user_prompt_template="""Based on the following context from the last 7 days, create a weekly summary:

{context}

Focus on themes, patterns, and key insights. Provide a comprehensive retrospective.""",
    temperature=0.4,  # Higher for more creative/narrative output
    max_output_tokens=2048,
    time_window_hours=168,  # 7 days
    output_format=OutputFormat.MARKDOWN,
    tags=["weekly", "retrospective"],
)

MEETING_PREP_PROMPT = PromptTemplate(
    id="meeting-prep",
    name="Meeting Preparation",
    description="Gather context for an upcoming meeting",
    system_prompt="""You are a helpful assistant that prepares meeting context briefs.

Your goal is to summarize relevant background information to help the user prepare for a meeting.

Focus on:
- Recent discussions related to the meeting topic
- Open action items and decisions needed
- Key stakeholders and their positions
- Important context the user should be aware of

Guidelines:
- Be concise and highlight actionable information.
- Prioritize recent and relevant context.
- Surface potential discussion points.
- Keep it under 500 words.""",
    user_prompt_template="""Prepare a context brief for a meeting about: {meeting_topic}

Recent activity:
{context}

Provide:
1. Background context (2-3 sentences)
2. Recent relevant activity (bullet points)
3. Suggested talking points or questions""",
    temperature=0.3,
    max_output_tokens=1024,
    time_window_hours=72,  # Last 3 days
    output_format=OutputFormat.TEXT,
    tags=["meetings", "preparation"],
)

PR_SUMMARY_PROMPT = PromptTemplate(
    id="pr-summary",
    name="PR Summary",
    description="Summarize pull request activity",
    system_prompt="""You are a helpful assistant that summarizes pull request activity.

Focus on PRs that need attention or action from the user:
- PRs awaiting your review
- PRs with comments addressed to you
- PRs you authored that need updates
- Blocked PRs that need unblocking
- Recently merged PRs (for awareness)

Guidelines:
- Prioritize by urgency and action required.
- Group by category (needs review, needs update, merged, blocked).
- Include PR titles and key context.
- Highlight blockers and urgent items.
- Keep it actionable and concise.""",
    user_prompt_template="""Summarize the following PR activity from the last 48 hours:

{context}

Prioritize items that need immediate action or attention.""",
    temperature=0.3,
    max_output_tokens=1024,
    time_window_hours=48,  # Last 2 days
    output_format=OutputFormat.TEXT,
    tags=["github", "code-review", "prs"],
)

MORNING_BRIEF_PROMPT = PromptTemplate(
    id="brief",
    name="Morning Brief",
    description="Unified morning brief from all sources",
    system_prompt="""You are a helpful developer assistant that creates concise morning briefs.
Your job is to summarize the developer's notifications, emails, messages, and tasks into an actionable summary.

Guidelines:
- Be concise and actionable
- Prioritize important items (urgent issues, blocking tasks, meeting requests)
- Group related items together
- Highlight action items that need immediate attention
- Use bullet points for clarity
- Keep the total summary under 500 words""",
    user_prompt_template="""Please create a morning brief summary from the following context items from various sources.
Focus on what the developer needs to know and do today.

Context items:
{context}

Please provide:
1. A brief executive summary (2-3 sentences)
2. Key highlights (bullet points)
3. Action items that need attention
4. Any potential blockers or urgent issues""",
    temperature=0.3,
    max_output_tokens=1024,
    time_window_hours=None,  # No time filter for brief
    output_format=OutputFormat.TEXT,
    tags=["daily", "brief"],
)


# Register all built-in prompts
PromptRegistry.register(STANDUP_PROMPT)
PromptRegistry.register(WEEKLY_SUMMARY_PROMPT)
PromptRegistry.register(MEETING_PREP_PROMPT)
PromptRegistry.register(PR_SUMMARY_PROMPT)
PromptRegistry.register(MORNING_BRIEF_PROMPT)
