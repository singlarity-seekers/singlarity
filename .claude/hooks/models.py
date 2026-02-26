"""
Pydantic data models for Claude Code session metrics.

Used by metrics_hook.py to structure, validate, serialize, and publish
session-level metrics to Langfuse and output files.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field


class ToolCallType(str, Enum):
    """All known Claude Code tool types and MCP tool categories."""

    # --- Core file tools ---
    READ = "Read"
    WRITE = "Write"
    EDIT = "Edit"
    MULTI_EDIT = "MultiEdit"
    GLOB = "Glob"
    GREP = "Grep"
    NOTEBOOK_EDIT = "NotebookEdit"

    # --- Execution ---
    BASH = "Bash"

    # --- Web ---
    WEB_FETCH = "WebFetch"
    WEB_SEARCH = "WebSearch"

    # --- Task / Agent ---
    TASK = "Task"
    TASK_CREATE = "TaskCreate"
    TASK_UPDATE = "TaskUpdate"
    TASK_GET = "TaskGet"
    TASK_LIST = "TaskList"
    TASK_STOP = "TaskStop"
    TASK_OUTPUT = "TaskOutput"

    # --- Interaction ---
    ASK_USER_QUESTION = "AskUserQuestion"
    ENTER_PLAN_MODE = "EnterPlanMode"
    EXIT_PLAN_MODE = "ExitPlanMode"
    SKILL = "Skill"
    ENTER_WORKTREE = "EnterWorktree"

    # --- MCP tool categories ---
    MCP_GITHUB = "mcp_github"
    MCP_JIRA = "mcp_jira"
    MCP_CONFLUENCE = "mcp_confluence"
    MCP_ATLASSIAN = "mcp_atlassian"
    MCP_IDE = "mcp_ide"
    MCP_OTHER = "mcp_other"

    # --- Catch-all ---
    OTHER = "other"



# O(1) lookup table — built once at module load, replaces the O(n) linear scan.
_TOOL_BY_VALUE: Dict[str, ToolCallType] = {m.value: m for m in ToolCallType}


def classify_tool(raw_name: str) -> ToolCallType:
    """Map a raw tool name from Claude Code to a ToolCallType.

    Direct matches use an O(1) dict lookup; MCP tools are mapped to their
    category (mcp_github, mcp_jira, etc.); anything else becomes OTHER.
    """
    # O(1) direct lookup
    t = _TOOL_BY_VALUE.get(raw_name)
    if t is not None:
        return t

    # MCP tool classification (names like "mcp__github-readonly__...")
    raw_lower = raw_name.lower()
    if raw_lower.startswith("mcp__") or raw_lower.startswith("mcp_"):
        if "github" in raw_lower:
            return ToolCallType.MCP_GITHUB
        if "jira" in raw_lower:
            return ToolCallType.MCP_JIRA
        if "confluence" in raw_lower:
            return ToolCallType.MCP_CONFLUENCE
        if "atlassian" in raw_lower:
            return ToolCallType.MCP_ATLASSIAN
        if "ide" in raw_lower:
            return ToolCallType.MCP_IDE
        return ToolCallType.MCP_OTHER

    return ToolCallType.OTHER


# ── Metric sub-models ───────────────────────────────────────────────


class TokenMetric(BaseModel):
    """Token usage and estimated cost for a session."""

    token_input: int = 0
    token_output: int = 0
    token_cache_creation: int = 0
    token_cache_read: int = 0
    token_total: int = 0
    estimated_cost_usd: float = 0.0
    models_seen: Dict[str, int] = Field(
        default_factory=dict,
        description="Model name -> number of API responses using that model",
    )


class GithubMetric(BaseModel):
    """GitHub pull-request activity for the authenticated user (today)."""

    github_prs_created: int = 0
    github_prs_merged: int = 0
    github_prs_reviewed: int = 0


class JiraMetric(BaseModel):
    """Jira ticket activity for the authenticated user (today)."""

    jira_tickets_resolved: int = 0


class InterruptMetric(BaseModel):
    """Counts of session interruptions by type."""

    interrupt_tool_failure_total: int = 0
    interrupt_tool_failure_count: Dict[str, int] = Field(
        default_factory=dict,
        description="ToolCallType value -> failure count. Example: {'Bash': 2, 'mcp_github': 1}",
    )
    interrupt_tool_reason_count: Dict[str, int] = Field(
        default_factory=dict,
        description="Tool Call Failure Reason -> failure count. Example: {'Workspace Dir Not Found': 2, 'Authentication Failure github': 1}",
    )
    interrupt_unclear_context: int = 0
    interrupt_human: int = 0


class ToolsUsageMetric(BaseModel):
    """Tool call counts for the session."""

    tool_calls_total: int = 0
    tool_calls_group: Dict[str, int] = Field(
        default_factory=dict,
        description="ToolCallType value -> count.  Example: {'Bash': 5, 'Read': 3, 'mcp_github': 2}",
    )


# ── Top-level session metric ────────────────────────────────────────


class ClaudeSessionMetric(BaseModel):
    """Aggregate metrics for a single Claude Code session."""

    session_id: str
    user_id: str
    timestamp: str = ""
    token_metrics: TokenMetric = Field(default_factory=TokenMetric)
    github_metrics: GithubMetric = Field(default_factory=GithubMetric)
    jira_metrics: JiraMetric = Field(default_factory=JiraMetric)
    tools_usage_metric: ToolsUsageMetric = Field(default_factory=ToolsUsageMetric)
    interrupt_metric: InterruptMetric = Field(default_factory=InterruptMetric)

    def to_flat_scores(self) -> Dict[str, float]:
        """Flatten all metrics into a single {score_name: value} dict for Langfuse."""
        scores: Dict[str, float] = {}

        # Interrupt
        scores["interrupt_tool_failure_total"] = float(self.interrupt_metric.interrupt_tool_failure_total)
        for tool_type, count in self.interrupt_metric.interrupt_tool_failure_count.items():
            safe = tool_type.replace(" ", "_").replace(".", "_")
            scores[f"interrupt_tool_failure_{safe}"] = float(count)
        for reason, count in self.interrupt_metric.interrupt_tool_reason_count.items():
            safe = reason.replace(" ", "_").replace(".", "_")
            scores[f"interrupt_reason_{safe}"] = float(count)
        scores["interrupt_unclear_context"] = float(self.interrupt_metric.interrupt_unclear_context)
        scores["interrupt_human"] = float(self.interrupt_metric.interrupt_human)

        # Tool usage
        scores["tool_calls_total"] = float(self.tools_usage_metric.tool_calls_total)
        for tool_type, count in self.tools_usage_metric.tool_calls_group.items():
            safe = tool_type.replace(" ", "_").replace(".", "_")
            scores[f"tool_calls_{safe}"] = float(count)

        # Tokens
        scores["token_input"] = float(self.token_metrics.token_input)
        scores["token_output"] = float(self.token_metrics.token_output)
        scores["token_cache_creation"] = float(self.token_metrics.token_cache_creation)
        scores["token_cache_read"] = float(self.token_metrics.token_cache_read)
        scores["token_total"] = float(self.token_metrics.token_total)
        scores["estimated_cost_usd"] = self.token_metrics.estimated_cost_usd

        # GitHub
        scores["github_prs_created"] = float(self.github_metrics.github_prs_created)
        scores["github_prs_merged"] = float(self.github_metrics.github_prs_merged)
        scores["github_prs_reviewed"] = float(self.github_metrics.github_prs_reviewed)

        # Jira
        scores["jira_tickets_resolved"] = float(self.jira_metrics.jira_tickets_resolved)

        return scores
