"""AI Tool definitions for DevAssist.

Defines tools/functions that the AI can call to interact with context sources.
Currently only Gmail is implemented.
"""

from typing import Any

# Tool definitions for Gemini function calling
GMAIL_TOOLS = [
    {
        "name": "search_gmail",
        "description": "Search Gmail messages using Gmail query syntax. Use this to find specific emails.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query (e.g., 'from:boss@company.com', 'subject:urgent', 'is:unread', 'newer_than:1d')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_gmail_message",
        "description": "Get the full content of a specific Gmail message by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The Gmail message ID",
                },
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "get_gmail_thread",
        "description": "Get all messages in a Gmail thread/conversation.",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "The Gmail thread ID",
                },
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "send_gmail",
        "description": "Send a new email via Gmail.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address(es), comma-separated for multiple",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content (plain text)",
                },
                "cc": {
                    "type": "string",
                    "description": "CC recipients (optional)",
                },
                "bcc": {
                    "type": "string",
                    "description": "BCC recipients (optional)",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "reply_gmail",
        "description": "Reply to an existing Gmail message.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The message ID to reply to",
                },
                "body": {
                    "type": "string",
                    "description": "Reply body content",
                },
                "reply_all": {
                    "type": "boolean",
                    "description": "Whether to reply to all recipients (default: False)",
                    "default": False,
                },
            },
            "required": ["message_id", "body"],
        },
    },
    {
        "name": "draft_gmail",
        "description": "Create a draft email (does not send).",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address(es)",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "modify_gmail_labels",
        "description": "Add or remove labels from a Gmail message.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The message ID to modify",
                },
                "add_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to add (e.g., ['STARRED', 'IMPORTANT'])",
                },
                "remove_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to remove (e.g., ['UNREAD'])",
                },
            },
            "required": ["message_id"],
        },
    },
]


def get_all_tools() -> list[dict[str, Any]]:
    """Get all available tools (currently Gmail only)."""
    return GMAIL_TOOLS


def get_tools_for_sources(sources: list[str]) -> list[dict[str, Any]]:
    """Get tools for specific sources.
    
    Args:
        sources: List of source names (currently only 'gmail' supported)
        
    Returns:
        List of tool definitions for those sources.
    """
    tools = []
    source_map = {
        "gmail": GMAIL_TOOLS,
    }
    
    for source in sources:
        source_lower = source.lower()
        if source_lower in source_map:
            tools.extend(source_map[source_lower])
    
    return tools
