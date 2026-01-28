# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Singlarity** (DevAssist) is a Python CLI application that aggregates context from multiple developer tools (Gmail, Slack, JIRA, GitHub) and uses **Claude Agent SDK** to generate intelligent morning briefs. The project uses **Model Context Protocol (MCP) servers** for context sources and features a **unified AppConfig architecture** with **static session management**.

## Development Commands

### Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install in development mode
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage (minimum 80% required)
pytest --cov=devassist

# Run unit tests only
pytest tests/unit/

# Run integration tests (requires real API credentials, skipped in CI)
pytest tests/integration/ -m integration

# Run contract tests (validate adapter implementations)
pytest tests/contract/

# Run specific test file
pytest tests/unit/test_brief_generator.py -v

# Skip slow/integration tests
pytest -m "not integration and not slow"
```

### Code Quality

```bash
# Type checking (strict mode enabled)
mypy src/

# Linting
ruff check src/

# Format code
ruff format src/
```

**Code Quality Policy**: Linter and type checker warnings should be ignored unless they are breaking functionality. The project prioritizes working features over perfect code quality metrics. Fix errors that prevent the code from running, but warnings from ruff and mypy can be addressed later during refactoring phases.

### Running the CLI

```bash
# Show version and current configuration
devassist --version
devassist status

# Configure through config files and environment variables
# Workspace directory (~/.devassist/) is created automatically
# Create ~/.devassist/config.yaml with your settings
export JIRA_URL="https://yourcompany.atlassian.net"
export JIRA_API_TOKEN="your-token"

# Generate morning brief
devassist brief
devassist brief --sources gmail,slack     # specific sources
devassist brief --model "Opus 4"         # user-friendly AI model names
devassist brief --resume                 # continue previous conversation
devassist brief --session-id session-123 # use specific session

# Session management
devassist brief sessions                 # list recent sessions
devassist brief clean --days 7          # clean old sessions
devassist brief clear session-123       # clear specific session
```

## Architecture

### Modern Unified Structure

```
src/devassist/
├── ai/          # Claude Agent SDK integration
├── cli/         # Typer CLI commands (presentation layer)
├── core/        # Business logic (brief_generator)
├── models/      # Pydantic data models (config_unified, brief, context)
├── resources/   # System prompts, MCP server configurations
└── utils/       # Utility functions
```

### Key Architectural Principles

The architecture follows modern patterns for maintainability and extensibility:

1. **Unified Configuration**: Single `AppConfig` class handles all configuration needs
2. **Self-Contained Components**: Each component manages its own state and dependencies
3. **Static Session Management**: Sessions persist across component instances
4. **MCP Integration**: Uses industry-standard Model Context Protocol servers
### Core Components

1. **AppConfig** (`models/config_unified.py`): Unified configuration with smart deserialization
2. **ClaudeClient** (`ai/claude_client.py`): Claude Agent SDK wrapper with static session management
3. **BriefGenerator** (`core/brief_generator.py`): Orchestrates brief generation workflow

### MCP Integration

Context sources are accessed through **Model Context Protocol (MCP) servers** configured in `resources/mcp_servers.yaml`:

- **Gmail**: OAuth2-based email access
- **Slack**: Bot/user token integration
- **JIRA**: API token authentication
- **GitHub**: Personal access token

Each MCP server handles its own authentication and data fetching.

### Data Flow: Morning Brief Generation

```
User runs `devassist brief`
    ↓
CLI (brief.py) → AppConfig (unified configuration)
    ↓
BriefGenerator (orchestrator) → ClaudeClient (AI integration)
    ↓
Claude Agent SDK → MCP Servers (context fetching)
    ↓
Claude API → AI processing and summarization
    ↓
Brief model → structured response
    ↓
Rich Console → formatted terminal output
```

### Configuration Precedence

The system uses three-tier configuration:
1. CLI flags (highest priority)
2. Environment variables
3. Config files: `~/.devassist/config.yaml` (lowest priority)

### Storage Model

All data is stored locally in `~/.devassist/`:

```
~/.devassist/
├── config.yaml          # User configuration (YAML format)
└── briefs/              # Historical briefs (planned)
```

**Key Changes from Legacy:**
- **No cache directory**: MCP servers handle their own caching
- **No session persistence**: Sessions are in-memory only (static store)
- **Simplified structure**: Only configuration and optional brief history

**Workspace Creation**: The `~/.devassist/` directory is created automatically by `AppConfig` when first accessed. No separate `init` command needed.

**Security**: Use environment variables for credentials in production. Configuration files should only contain non-sensitive settings.

## Development Workflow

### Test-Driven Development (Mandatory)

This project follows strict TDD (Red-Green-Refactor):

1. **Red**: Write failing test first
2. **Green**: Implement minimal code to pass
3. **Refactor**: Improve code while keeping tests green

All new features require:
- Unit tests in `tests/unit/` (mock external dependencies)
- Integration tests in `tests/integration/` (test real API interactions, marked with `@pytest.mark.integration`)
- Minimum 80% code coverage for `src/devassist/`

### Adding a New Context Source (MCP-Based)

1. **Create MCP Server**: Implement or find an existing MCP server for your source
2. **Add MCP Configuration**: Update `src/devassist/resources/mcp_servers.yaml`:
   ```yaml
   newsource:
     command: "mcp-server-newsource"
     env:
       NEWSOURCE_API_TOKEN: "${NEWSOURCE_API_TOKEN}"
   ```
3. **Update SourceType**: Add to enum in `src/devassist/models/context.py`
4. **Configure Environment Mapping**: Add to `AppConfig._get_mcp_servers_config()` for env var substitution
5. **Test Integration**: Write integration tests for the new source

**No custom adapter code needed!** MCP servers handle all the integration complexity.
5. Register in CLI config commands

### Error Handling Requirements

The spec (FR-005) requires graceful degradation:

- **Source failures**: Don't crash - show partial results and note which sources failed
- **AI unavailable**: Fall back to raw data presentation with clear messaging
- **Rate limiting**: Exponential backoff with user notification
- **Token expiration**: Detect, notify user, guide re-authentication
- **Transient errors**: Retry up to 3 times before failing

## Key Technical Decisions

### Python 3.11+ Required

The codebase uses modern Python features:
- Type hints with `|` union syntax (not `Union`)
- `str | None` instead of `Optional[str]`
- Strict mypy checking enabled

### Claude Agent SDK Integration

The project uses **Claude Agent SDK** for AI interactions:
- **Brief summarization**: Generate intelligent morning briefs
- **Conversation continuity**: Session-based interactions
- **MCP server coordination**: Automatic context aggregation

ClaudeClient handles all SDK complexity and provides a simple interface:
```python
client = ClaudeClient(config)
response = await client.make_call("Generate my morning brief")
```

### Pydantic for Data Validation

All data models use Pydantic v2 for:
- Configuration validation and smart deserialization
- Data model validation
- Environment variable handling

### Rich for Terminal Output

Use Rich library for all CLI output:
- Tables for session listings
- Panels for brief summaries
- Styled text for status and errors
- Markdown rendering for AI responses

### Asynchronous Operations

Key async operations:
- `ClaudeClient.make_call()` - AI interactions
- `ClaudeClient.create_session()` - Session initialization
- `BriefGenerator.generate()` - Brief orchestration
```

## Specification-First Workflow

This project follows a specification-first approach. All specs live in `specs/[feature-id]/`:

- `spec.md` - Technology-agnostic feature specification
- `plan.md` - Technical implementation plan
- `data-model.md` - Entity models and relationships
- `contracts/` - Interface contracts (e.g., `context-source.md`)
- `tasks.md` - Granular implementation tasks
- `checklists/requirements.md` - Quality validation checklist

When implementing features:
1. Read the spec first to understand user value and acceptance criteria
2. Follow the plan for technical approach and structure decisions
3. Refer to contracts for interface requirements
4. Use tasks.md for step-by-step implementation guide

## Important Constraints

- **Performance**: Morning brief generation must complete in < 60 seconds for 4 sources
- **Sessions**: In-memory only (don't survive process restarts)
- **Coverage**: Minimum 80% test coverage for core modules
- **Token Limits**: AI prompts must stay within Claude model token limits
- **Single User**: Designed for single-user local execution (no multi-user support)
- **MCP Dependency**: Requires properly configured MCP servers for context sources

## Project Status

**Current Architecture: Unified & Modernized**

- ✅ **Phase 1**: Unified AppConfig with smart deserialization
- ✅ **Phase 2**: Self-contained ClaudeClient with static session management
- ✅ **Phase 3**: Deprecated manager classes removed
- ✅ **Core Infrastructure**: Claude Agent SDK integration
- ✅ **Configuration**: User-friendly model names and auto-discovery
- ✅ **Brief Generation**: Full workflow with Claude Agent SDK
- ✅ **Session Management**: Persistent conversations across CLI calls
- ✅ **MCP Integration**: Industry-standard context server protocol
- ✅ **Testing**: 45+ comprehensive tests covering new architecture
- ⏳ **MCP Server Deployment**: Actual server implementations (planned)
- ⏳ **Preference Learning**: User priority learning (planned)
- ⏳ **Advanced Features**: EC2 management, auto-responses (planned)

## Current Implementation Status

### ✅ **Fully Implemented**
- `devassist status` - Show unified configuration status
- `devassist brief` - Generate morning brief with Claude
- `devassist brief sessions` - List and manage conversation sessions
- `devassist brief clean/clear` - Session cleanup
- Session resumption and conversation continuity
- User-friendly AI model configuration
- Environment variable and file-based configuration

### 🚧 **Partially Implemented**
- MCP server configurations (defined but servers need deployment)
- Legacy config commands (show deprecation notices)

### ⏳ **Planned Features**
- Live MCP server deployments
- Preference learning system
- Quarterly contribution summaries
- EC2 sandbox management
- Auto-response drafting

**Architecture is complete and ready for MCP server integration!**
