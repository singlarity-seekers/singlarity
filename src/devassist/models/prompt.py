"""Prompt template models for DevAssist.

Defines data structures for prompt management and execution.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OutputFormat(str, Enum):
    """Output format for prompt results."""

    TEXT = "text"
    STRUCTURED_YAML = "yaml"
    JSON = "json"
    MARKDOWN = "markdown"


class PromptTemplate(BaseModel):
    """Template for AI prompt execution."""

    id: str = Field(..., description="Unique prompt identifier")
    name: str = Field(..., description="Display name")
    description: str = Field(..., description="User-facing description")

    # Prompt content
    system_prompt: str = Field(..., description="System instruction for AI")
    user_prompt_template: str = Field(
        ..., description="User prompt with {context} placeholder"
    )

    # AI configuration
    temperature: float = Field(
        0.3, ge=0.0, le=2.0, description="Sampling temperature for AI model"
    )
    max_output_tokens: int = Field(
        1024, ge=1, le=8192, description="Maximum response length in tokens"
    )

    # Context filtering
    time_window_hours: int | None = Field(
        None, description="Filter context to last N hours (None = no filter)"
    )
    source_filter: list[str] | None = Field(
        None, description="Limit to specific sources (None = all sources)"
    )

    # Output formatting
    output_format: OutputFormat = Field(
        OutputFormat.TEXT, description="Expected output format"
    )

    # Metadata
    tags: list[str] = Field(default_factory=list, description="Categorization tags")
    version: str = Field("1.0", description="Template version")


class PromptExecutionResult(BaseModel):
    """Result of prompt execution."""

    prompt_id: str = Field(..., description="ID of executed prompt")
    generated_text: str = Field(..., description="AI-generated response")
    format: OutputFormat = Field(..., description="Output format used")
    context_items_count: int = Field(..., description="Number of context items used")
    execution_time_seconds: float = Field(..., description="Execution time in seconds")
    generated_at: datetime = Field(..., description="Timestamp of generation")
    sources_used: list[str] = Field(..., description="Sources that provided context")
    sources_failed: list[str] = Field(
        default_factory=list, description="Sources that failed to fetch"
    )
