# DevAssist - Developer Assistant CLI

An AI-powered CLI that aggregates context from multiple developer tools (GitHub, Slack, JIRA) using Claude SDK with MCP (Model Context Protocol) to generate a Unified Morning Brief.

## Features

- **Unified Morning Brief**: AI-generated consolidated summary from all your work tools
- **Claude SDK + MCP Integration**: Claude orchestrates data fetching via MCP servers
- **Personalized Context**: Configure your GitHub username for targeted queries
- **Background Daemon**: Desktop notifications for important items
- **Multiple AI Providers**: Supports Vertex AI (Claude) or direct Anthropic API

## Installation

```bash
# Clone the repository
git clone https://github.com/singlarity-seekers/singlarity.git
cd singlarity

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install in development mode
pip install -e ".[dev]"
```

## Quick Start

### 1. Configure AI Provider

Choose one of:

**Option A: Vertex AI (recommended for GCP users)**
```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

**Option B: Direct Anthropic API**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 2. Set Up Your User Profile

```bash
# Configure your GitHub username for personalized briefs
devassist config user set --github YOUR_GITHUB_USERNAME

# Optionally add organizations to monitor
devassist config user set --orgs "org1,org2"

# View your profile
devassist config user show
```

### 3. Configure MCP Servers

```bash
# Add GitHub MCP server
export GITHUB_PERSONAL_ACCESS_TOKEN="ghp_..."
devassist config mcp add github

# Add Slack (optional)
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_TEAM_ID="T..."
devassist config mcp add slack

# Add JIRA (optional)
export ATLASSIAN_URL="https://yourcompany.atlassian.net"
export ATLASSIAN_EMAIL="you@company.com"
export ATLASSIAN_API_TOKEN="..."
devassist config mcp add jira

# List configured servers
devassist config mcp list
```

### 4. Generate Your Morning Brief

```bash
devassist brief
```

## Usage

### Morning Brief

```bash
# Generate brief from all configured MCP sources
devassist brief

# Force refresh (bypass cache)
devassist brief --refresh

# JSON output for scripting
devassist brief --json

# Use specific AI provider
devassist brief --provider claude   # Default
devassist brief --provider vertex   # Legacy Vertex AI mode
```

### User Profile

```bash
# Set profile information
devassist config user set --github USERNAME --orgs "org1,org2"
devassist config user set --name "Your Name" --email "you@example.com"
devassist config user set --jira "jira_username"

# View current profile
devassist config user show
```

### MCP Server Management

```bash
# Add MCP servers
devassist config mcp add github
devassist config mcp add slack
devassist config mcp add jira
devassist config mcp add custom   # Custom server configuration

# List configured servers
devassist config mcp list

# Test server configurations
devassist config mcp test

# Remove a server
devassist config mcp remove github
```

### Background Daemon

```bash
# Start daemon (runs in background)
devassist daemon start

# Start in foreground
devassist daemon start --foreground

# Configure check interval (default: 300 seconds)
devassist daemon start --interval 600

# Check daemon status
devassist daemon status

# View daemon logs
devassist daemon logs
devassist daemon logs --follow

# Stop daemon
devassist daemon stop
```

### Status

```bash
# Show overall configuration status
devassist status
```

## Configuration Files

All configuration is stored in `~/.devassist/`:

```
~/.devassist/
├── config.yaml      # User profile and preferences
├── .mcp.json        # MCP server configurations
├── daemon.pid       # Daemon process ID
├── daemon.log       # Daemon output log
└── daemon_state.json # Seen items for deduplication
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Direct Anthropic API key |
| `GOOGLE_CLOUD_PROJECT` | GCP project for Vertex AI |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | GitHub token for MCP server |
| `SLACK_BOT_TOKEN` | Slack bot token |
| `SLACK_TEAM_ID` | Slack team/workspace ID |
| `ATLASSIAN_URL` | JIRA instance URL |
| `ATLASSIAN_EMAIL` | JIRA user email |
| `ATLASSIAN_API_TOKEN` | JIRA API token |

## Architecture

```
src/devassist/
├── cli/           # Typer CLI commands (brief, config, daemon)
├── core/          # Core logic
│   ├── orchestrator.py    # Claude SDK + MCP integration
│   ├── config_manager.py  # Configuration management
│   └── brief_generator.py # Legacy Vertex AI brief generation
├── mcp/           # MCP configuration loader
├── daemon/        # Background monitoring
│   ├── monitor.py   # Source monitoring loop
│   └── notifier.py  # Desktop notifications
├── adapters/      # Legacy context source adapters
├── ai/            # AI client implementations
└── models/        # Pydantic data models
```

## How It Works

1. **Claude SDK as Orchestrator**: Instead of custom adapter code, Claude directly uses MCP tools to fetch data from your configured sources.

2. **MCP Servers**: Each source (GitHub, Slack, JIRA) runs as an MCP server that Claude can query via tool use.

3. **Personalized Queries**: Your user profile (GitHub username, orgs) is included in the system prompt so Claude searches for items specifically relevant to you.

4. **Intelligent Summarization**: Claude analyzes all fetched data and generates a prioritized, actionable morning brief.

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=devassist

# Type checking
mypy src/

# Linting
ruff check src/
```

## Requirements

- Python 3.11+
- Node.js (for MCP servers via npx)
- One of:
  - GCP project with Vertex AI API enabled
  - Anthropic API key
- API credentials for desired integrations

## License

MIT License - see LICENSE file for details.
