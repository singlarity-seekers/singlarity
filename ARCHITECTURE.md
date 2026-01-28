# Singlarity (DevAssist) - Architecture Documentation

## Overview

Singlarity is a Python CLI application that aggregates context from multiple developer tools and uses Claude Agent SDK to generate unified morning briefs. The architecture follows a modern, self-contained design with minimal dependencies and clear separation of concerns.

## Architecture Principles

### 🎯 **Self-Contained Components**
- Each component manages its own configuration and state
- Minimal external dependencies between components
- Clear, explicit interfaces

### 🔧 **Unified Configuration**
- Single `AppConfig` class handles all configuration needs
- Smart deserialization from CLI inputs, environment variables, and files
- User-friendly parameter mapping

### 📦 **Static Session Management**
- Sessions persist for the entire Python process lifetime
- Shared across all component instances
- No external storage dependencies

### 🔌 **MCP-Based Context Sources**
- Uses Model Context Protocol (MCP) servers instead of custom adapters
- Configured through AppConfig with environment variable substitution
- Supports Gmail, Slack, JIRA, GitHub, and more

## Core Components

### 1. Configuration Layer

#### **AppConfig** (`src/devassist/models/config_unified.py`)
*The heart of the new architecture*

```python
config = AppConfig(
    sources=['gmail', 'slack'],
    ai_model='Sonnet 4',           # User-friendly names
    ai_timeout_seconds=120,
    output_format='markdown'
)
```

**Key Features:**
- **Smart Deserialization**: Converts strings to proper types automatically
- **User-Friendly AI Models**: Maps "Sonnet 4" → "claude-sonnet-4@20250514"
- **Auto-Discovery**: Finds available sources from MCP configuration
- **Environment Integration**: Supports env vars with `DEVASSIST_*` prefix
- **File Integration**: Loads from `~/.devassist/config.yaml`
- **Validation**: Ensures valid combinations and clamped values

### 2. AI Integration Layer

#### **ClaudeClient** (`src/devassist/ai/claude_client.py`)
*Self-contained Claude Agent SDK wrapper*

```python
client = ClaudeClient(config)
response = await client.make_call("Generate my brief", session_id="session-123")
```

**Key Features:**
- **Static Session Store**: `_session_store` persists across all instances
- **MCP Server Integration**: Configures servers from AppConfig
- **Session Management**: Create, resume, list, and clear sessions
- **SDK Abstraction**: Wraps Claude Agent SDK complexity

**Session Management:**
```python
# List all sessions across any client instance
sessions = client.list_sessions()
session_count = ClaudeClient.get_session_count()

# Get specific session by ID
session = ClaudeClient.get_session_by_id("session-123")

# Sessions persist until Python process ends
client1 = ClaudeClient(config)
client2 = ClaudeClient(config)
# Both see the same sessions!
```

### 3. Business Logic Layer

#### **BriefGenerator** (`src/devassist/core/brief_generator.py`)
*Orchestrates brief generation workflow*

```python
generator = BriefGenerator(config=config)
brief = await generator.generate(sources=['gmail', 'jira'])
```

**Simplified Dependencies:**
- Takes `AppConfig` directly (no manager classes)
- Uses ClaudeClient for AI calls
- Leverages static session store for continuity

### 4. Presentation Layer

#### **CLI Commands** (`src/devassist/cli/`)
*Typer-based command interface*

```bash
# Modern workflow
devassist status                    # Shows AppConfig status
devassist brief --sources gmail,slack
devassist brief --session-id session-123
devassist brief clean --days 7     # Uses ClaudeClient directly
```

## Data Flow

### Morning Brief Generation
```
User CLI Command
    ↓
AppConfig (unified configuration)
    ↓
BriefGenerator (orchestration)
    ↓
ClaudeClient (AI calls via Claude Agent SDK)
    ↓
MCP Servers (Gmail, Slack, JIRA, GitHub)
    ↓
Claude API (AI processing)
    ↓
Brief Model (structured response)
    ↓
Rich Console (formatted output)
```

### Session Management Flow
```
ClaudeClient.create_session()
    ↓
Static Session Store (shared across instances)
    ↓
make_call(session_id=...)
    ↓
Claude Agent SDK (with session context)
    ↓
Response + Updated Session State
```

## Configuration Management

### Priority Order (Highest to Lowest)
1. **CLI Arguments**: `--sources gmail,slack`
2. **Environment Variables**: `DEVASSIST_AI_MODEL=fast`
3. **Configuration Files**: `~/.devassist/config.yaml`
4. **Defaults**: Sensible fallbacks

### Configuration Examples

#### CLI Arguments
```bash
devassist brief \
  --sources gmail,jira \
  --model "Opus 4" \
  --timeout 180 \
  --output json
```

#### Environment Variables
```bash
export DEVASSIST_AI_MODEL="fast"
export DEVASSIST_SOURCES="gmail,slack"
export DEVASSIST_AI_TIMEOUT_SECONDS=120
```

#### Configuration File (`~/.devassist/config.yaml`)
```yaml
ai_model: "Sonnet 4"
sources: ["gmail", "slack", "jira"]
ai_timeout_seconds: 120
output_format: "markdown"
source_configs:
  gmail:
    enabled: true
    credentials_file: "/path/to/gmail.json"
  slack:
    enabled: true
    token: "xoxb-your-token"
```

## MCP Server Integration

### Server Configuration
MCP servers are configured through the resources module and AppConfig:

```yaml
# resources/mcp_servers.yaml
gmail:
  command: "docker"
  args: ["run", "--rm", "mcp-server-gmail"]
  env:
    GMAIL_CREDENTIALS_FILE: "${GMAIL_CREDENTIALS_FILE}"

jira:
  command: "mcp-server-jira"
  env:
    JIRA_URL: "${JIRA_URL}"
    JIRA_EMAIL: "${JIRA_EMAIL}"
    JIRA_API_TOKEN: "${JIRA_API_TOKEN}"
```

### Environment Variable Substitution
AppConfig automatically substitutes environment variables in MCP configs:
- `${GMAIL_CREDENTIALS_FILE}` → actual file path
- `${JIRA_URL}` → JIRA instance URL
- `${SLACK_API_TOKEN}` → Slack bot token

## Storage & Persistence

### Session Storage
- **Location**: In-memory static dictionary
- **Lifetime**: Entire Python process
- **Sharing**: Across all ClaudeClient instances
- **Persistence**: No disk storage (sessions don't survive restarts)

### Configuration Storage
- **Location**: `~/.devassist/config.yaml`
- **Format**: YAML with validation
- **Merging**: CLI args > env vars > files > defaults

### Cache Storage (Legacy)
The old cache system has been deprecated. MCP servers handle their own caching as needed.

## Error Handling & Resilience

### Graceful Degradation
- **Source Failures**: Continue with available sources, report failures
- **AI Unavailable**: Fallback to raw data presentation
- **Rate Limiting**: Exponential backoff with user notification
- **Token Expiration**: Clear error messages with re-authentication guidance

### Exception Hierarchy
- `AuthenticationError`: Invalid credentials
- `SourceUnavailableError`: Service outages
- `RateLimitError`: API limits exceeded
- `ConfigurationError`: Invalid settings

## Performance Characteristics

### Targets
- **Brief Generation**: < 60 seconds for 4 sources
- **Session Startup**: < 2 seconds
- **Memory Usage**: < 100MB typical

### Optimization Strategies
- **Parallel Fetching**: MCP servers run concurrently
- **Session Reuse**: Avoid recreation overhead
- **Smart Defaults**: Minimal configuration required

## Security Considerations

### Credential Management
- **Environment Variables**: Preferred for production
- **File Storage**: Development convenience only
- **No Hardcoding**: Never embed secrets in code
- **MCP Isolation**: Each server handles its own auth

### Permission Model
- **Claude SDK**: Configurable permission modes
- **MCP Servers**: Sandboxed execution
- **Local Files**: Standard filesystem permissions

## Migration from Legacy Architecture

### What Changed
- ❌ **ConfigManager** → ✅ **AppConfig**
- ❌ **SessionManager** → ✅ **ClaudeClient static sessions**
- ❌ **CacheManager** → ✅ **MCP server caching**
- ❌ **Custom Adapters** → ✅ **MCP servers**
- ❌ **Multiple Config Classes** → ✅ **Single AppConfig**

### Migration Benefits
- **50% fewer classes**: Simpler architecture
- **Zero external dependencies**: For session/config management
- **Better testing**: Easier to mock and test
- **User experience**: More intuitive configuration

## Development Workflow

### Testing Strategy
- **Unit Tests**: 45+ passing tests with comprehensive coverage
- **Integration Tests**: Real MCP server connections
- **Contract Tests**: Validate interfaces
- **Performance Tests**: Brief generation timing

### Code Organization
```
src/devassist/
├── ai/                    # Claude Agent SDK integration
├── cli/                   # Command-line interface
├── core/                  # Business logic (BriefGenerator)
├── models/                # Data models (AppConfig, Brief, etc)
├── resources/             # System prompts, MCP configs
└── utils/                 # Utility functions
```

## Future Extensibility

### Adding New Sources
1. Add MCP server configuration to resources
2. Update SourceType enum in context.py
3. Configure environment variable mapping
4. No code changes required!

### Custom AI Models
1. Add model mapping to AppConfig.MODEL_MAPPING
2. Users can immediately use friendly names
3. Technical IDs handled automatically

### Session Persistence
If needed, can extend ClaudeClient to save/restore sessions from disk while maintaining the static store pattern.

## Conclusion

The new architecture represents a significant simplification while maintaining all functionality:
- **Unified Configuration**: Single source of truth
- **Self-Contained Components**: Minimal dependencies
- **Modern Patterns**: Static sessions, smart deserialization
- **MCP Integration**: Industry-standard context servers
- **Developer Experience**: Intuitive and maintainable

This architecture scales from simple single-source usage to complex multi-source enterprise deployments while remaining easy to understand and extend.