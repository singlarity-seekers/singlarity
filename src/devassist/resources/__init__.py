"""Resources for DevAssist.

Contains system prompts and MCP server configurations.
"""

from pathlib import Path

RESOURCES_DIR = Path(__file__).parent
SYSTEM_PROMPT_FILE = RESOURCES_DIR / "personal-assistant.md"
MCP_SERVERS_FILE = RESOURCES_DIR / "mcp-servers.json"


def get_system_prompt() -> str:
    """Load the system prompt from file.

    Returns:
        System prompt string.
    """
    if not SYSTEM_PROMPT_FILE.exists():
        return "You are a helpful developer assistant."
    return SYSTEM_PROMPT_FILE.read_text()


def get_mcp_servers_config() -> dict:
    """Load MCP servers configuration from file.

    Returns:
        Dictionary of MCP server configurations.
    """
    import json

    if not MCP_SERVERS_FILE.exists():
        return {}

    with open(MCP_SERVERS_FILE) as f:
        return json.load(f)
