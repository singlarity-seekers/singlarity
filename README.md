# DevAssist - Developer Assistant CLI

A Python CLI application that aggregates context from multiple developer tools (Gmail, Slack, JIRA, GitHub) and uses AI to generate a Unified Morning Brief and other productivity features.

## Features

- **Unified Morning Brief**: Consolidated summary from all your communication and work tracking tools
- **AI Chat with Tool Calling**: Interactive chat where AI can search, read, send, and draft emails via Gmail
- **Context Source Configuration**: Easy setup for Gmail, Slack, JIRA, and GitHub integrations
- **Preference Learning**: (Planned) Learns your priorities over time to improve relevance
- **EC2 Sandbox Toggle**: (Planned) Start/stop development instances from the CLI
- **Auto-Response Drafts**: (Planned) AI-generated responses with human-in-the-loop approval
- **Quarterly Notes**: (Planned) Generate contribution summaries for performance reviews

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

```bash
# Configure AI (choose one):
# Option 1: API Key (simpler)
export DEVASSIST_AI__API_KEY=your-google-ai-api-key

# Option 2: GCP Application Default Credentials
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID

# Add context sources (workspace directory ~/.devassist/ is created automatically)
# Each command will prompt for required credentials interactively
devassist config add gmail

# Start AI chat (can search, read, send, draft emails)
devassist chat

# Or generate morning brief
devassist brief
```

## Usage

### Morning Brief

```bash
# Generate brief from all sources
devassist brief

# Brief from specific sources
devassist brief --sources gmail,jira

# Force refresh (ignore cache)
devassist brief --refresh

# JSON output
devassist brief --json
```

### AI Chat with Tool Calling

```bash
# Start interactive chat session
devassist chat

# Chat with specific API key
devassist chat --api-key YOUR_API_KEY

# Use a different model
devassist chat --model gemini-2.5-pro
```

The AI can interact with your Gmail using natural language:
- "Search my unread emails"
- "Show me emails from boss@company.com"
- "Draft an email to john@example.com about the meeting"
- "Reply to the latest email saying thanks"

### Configuration

```bash
# List configured sources
devassist config list

# Test connections
devassist config test

# Remove a source
devassist config remove slack
```


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

## Architecture

```
src/devassist/
├── cli/         # Typer CLI commands
├── core/        # Business logic (aggregator, ranker, brief_generator)
├── adapters/    # Context source adapters (gmail, slack, jira, github)
├── ai/          # Vertex AI integration
├── preferences/ # Preference learning
└── models/      # Pydantic data models
```

## Requirements

- Python 3.11+
- GCP project with Vertex AI API enabled
- API credentials for desired integrations

## License

MIT License - see LICENSE file for details.
