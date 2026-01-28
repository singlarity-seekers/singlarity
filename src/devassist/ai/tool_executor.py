"""Tool executor for DevAssist.

Executes AI tool calls by routing them to the appropriate adapters.
Currently only Gmail is supported.
"""

from typing import Any

from devassist.adapters.base import ContextSourceAdapter


class ToolExecutor:
    """Executes tools by routing to configured adapters."""

    def __init__(self) -> None:
        """Initialize ToolExecutor."""
        self._adapters: dict[str, ContextSourceAdapter] = {}

    def register_adapter(self, name: str, adapter: ContextSourceAdapter) -> None:
        """Register an adapter for tool execution.
        
        Args:
            name: Adapter name (e.g., 'gmail').
            adapter: Initialized and authenticated adapter instance.
        """
        self._adapters[name.lower()] = adapter

    def get_registered_sources(self) -> list[str]:
        """Get list of registered source names."""
        return list(self._adapters.keys())

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Execute a tool call.
        
        Args:
            tool_name: Name of the tool to execute.
            args: Tool arguments.
            
        Returns:
            Tool execution result.
            
        Raises:
            ValueError: If tool is not found or adapter not registered.
        """
        # Route to Gmail handler
        if tool_name in [
            "search_gmail",
            "get_gmail_message",
            "get_gmail_thread",
            "send_gmail",
            "reply_gmail",
            "draft_gmail",
            "modify_gmail_labels",
        ]:
            return await self._execute_gmail_tool(tool_name, args)
        
        raise ValueError(f"Unknown tool: {tool_name}")

    async def _execute_gmail_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Execute Gmail-related tools."""
        adapter = self._adapters.get("gmail")
        if not adapter:
            raise ValueError("Gmail adapter not registered. Configure Gmail first with 'devassist config add gmail'")

        # Import here to avoid circular imports
        from devassist.adapters.gmail import GmailAdapter
        if not isinstance(adapter, GmailAdapter):
            raise ValueError("Invalid Gmail adapter type")

        if tool_name == "search_gmail":
            return await adapter.search_gmail(
                query=args.get("query", ""),
                max_results=args.get("max_results", 10),
            )
        
        elif tool_name == "get_gmail_message":
            return await adapter.get_gmail_message(
                message_id=args["message_id"],
            )
        
        elif tool_name == "get_gmail_thread":
            return await adapter.get_gmail_thread(
                thread_id=args["thread_id"],
            )
        
        elif tool_name == "send_gmail":
            return await adapter.send_gmail(
                to=args["to"],
                subject=args["subject"],
                body=args["body"],
                cc=args.get("cc"),
                bcc=args.get("bcc"),
            )
        
        elif tool_name == "reply_gmail":
            return await adapter.reply_gmail(
                message_id=args["message_id"],
                body=args["body"],
                reply_all=args.get("reply_all", False),
            )
        
        elif tool_name == "draft_gmail":
            return await adapter.draft_gmail(
                to=args["to"],
                subject=args["subject"],
                body=args["body"],
            )
        
        elif tool_name == "modify_gmail_labels":
            return await adapter.modify_gmail_labels(
                message_id=args["message_id"],
                add_labels=args.get("add_labels"),
                remove_labels=args.get("remove_labels"),
            )
        
        raise ValueError(f"Unknown Gmail tool: {tool_name}")


# Global executor instance
_executor: ToolExecutor | None = None


def get_tool_executor() -> ToolExecutor:
    """Get or create the global tool executor."""
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor


async def execute_tool(tool_name: str, args: dict[str, Any]) -> Any:
    """Execute a tool using the global executor.
    
    This is a convenience function for use with VertexAIClient.chat_with_tools().
    
    Args:
        tool_name: Tool name.
        args: Tool arguments.
        
    Returns:
        Tool result.
    """
    executor = get_tool_executor()
    return await executor.execute(tool_name, args)
