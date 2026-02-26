#!/usr/bin/env python3
"""
Claude Code Metrics Hook -> Langfuse

Captures session-level metrics from direct hook payloads and external APIs,
then emits them as Langfuse numeric scores for dashboard visualization.

Registered on three hook types:
  - PostToolUse:        Increments tool call counters, detects AskUserQuestion
  - PostToolUseFailure: Increments tool_failure or human_interrupt counters
  - Stop:               Reads accumulated state, calls GitHub/Jira APIs, emits to Langfuse

Data models live in models.py (ClaudeSessionMetric and sub-models).

Environment variables:
  CC_METRICS_SYNC=true   Run Stop handler synchronously instead of in a subprocess.
                         Useful for testing/debugging.
"""

import json
import os
import subprocess
import sys
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# --- Fail-open imports ---
try:
    from langfuse import Langfuse, propagate_attributes
except Exception:
    sys.exit(0)

try:
    import httpx
except Exception:
    httpx = None  # HTTP calls will be skipped

# Make sibling modules importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from models import (
        ClaudeSessionMetric,
        TokenMetric,
        GithubMetric,
        JiraMetric,
        InterruptMetric,
        ToolsUsageMetric,
        classify_tool,
    )
    from hook_utils import (
        STATE_DIR,
        FileLock,
        Logger,
        read_hook_payload,
        resolve_langfuse_credentials,
    )
except Exception:
    sys.exit(0)

# --- Paths ---
LOG_FILE = STATE_DIR / "metrics_hook.log"
DEFAULT_OUTPUT_FILE = STATE_DIR / "claude_session_output.txt"

DEBUG = os.environ.get("CC_LANGFUSE_DEBUG", "").lower() == "true"
HTTP_TIMEOUT = 10.0  # seconds per API call

# Set CC_METRICS_SYNC=true to skip subprocess offload and run synchronously.
SYNC_MODE = os.environ.get("CC_METRICS_SYNC", "").lower() == "true"

log = Logger(LOG_FILE, debug_enabled=DEBUG)

# Pricing per 1M tokens (USD) — update when Anthropic changes pricing
# Format: {model_prefix: (input_per_1M, output_per_1M, cache_read_per_1M)}
MODEL_PRICING: Dict[str, Tuple[float, float, float]] = {
    "claude-opus-4":   (15.0, 75.0, 1.50),
    "claude-sonnet-4": (3.0,  15.0, 0.30),
    "claude-sonnet-3": (3.0,  15.0, 0.30),
    "claude-haiku-3":  (0.80, 4.0,  0.08),
    "claude-haiku-4":  (0.80, 4.0,  0.08),
}


# ── State management ──────────────────────────────────────────────────

def _state_file_for_session(session_id: str) -> Path:
    h = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return STATE_DIR / f"metrics_{h}.json"


def _lock_file_for_session(session_id: str) -> Path:
    """Per-session lock file — avoids cross-session contention."""
    h = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return STATE_DIR / f"metrics_{h}.lock"


def load_metrics_state(session_id: str) -> Dict[str, Any]:
    sf = _state_file_for_session(session_id)
    try:
        if sf.exists():
            return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "session_id": session_id,
        "tool_calls": {},
        "tool_calls_total": 0,
        "tool_failures_total": 0,
        "tool_failure_counts": {},
        "tool_failure_reasons": {},
        "unclear_context": 0,
        "human_interrupts": 0,
    }


def save_metrics_state(session_id: str, state: Dict[str, Any]) -> None:
    sf = _state_file_for_session(session_id)
    try:
        state["updated"] = datetime.now(timezone.utc).isoformat()
        tmp = sf.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, sf)
    except Exception as e:
        log.debug(f"save_metrics_state failed: {e}")


# ── PostToolUse handler ───────────────────────────────────────────────

def handle_post_tool_use(payload: Dict[str, Any]) -> int:
    """Increment tool call counters. Detect AskUserQuestion (unclear context)."""
    session_id = payload.get("session_id")
    if not session_id:
        return 0

    tool_name = payload.get("tool_name", "unknown")
    tool_type = classify_tool(tool_name).value

    with FileLock(_lock_file_for_session(session_id)):
        state = load_metrics_state(session_id)

        tc = state.get("tool_calls", {})
        tc[tool_type] = tc.get(tool_type, 0) + 1
        state["tool_calls"] = tc

        state["tool_calls_total"] = state.get("tool_calls_total", 0) + 1

        if tool_name == "AskUserQuestion":
            state["unclear_context"] = state.get("unclear_context", 0) + 1

        save_metrics_state(session_id, state)

    log.debug(f"PostToolUse: {tool_name} -> {tool_type} (session={session_id})")
    return 0


# ── Unclear-context detection ─────────────────────────────────────────

# Max length for a response that is purely a clarification question.
# Longer responses likely contain real output alongside a follow-up question.
_MAX_SHORT_RESPONSE = 500
_MAX_TRAILING_QUESTION = 200


def is_clarification_request(text: str) -> bool:
    """Detect if an assistant message is asking the user for clarification.

    Uses structural heuristics instead of keyword matching:
      - A short response (< 500 chars) that ends with '?' is almost certainly
        Claude asking for input rather than delivering work.
      - A longer response whose last line ends with '?' and contains no code
        blocks is also likely a clarification (explanation + question).
      - Responses with code blocks (```) are treated as work output even if
        they end with a question, since the question is a follow-up, not a
        "context unclear" interrupt.
    """
    if not text or "?" not in text:
        return False

    stripped = text.strip()

    # Responses with code blocks are work output, not clarification requests
    if "```" in stripped:
        return False

    # Short response ending with '?' -> clarification
    if stripped.endswith("?") and len(stripped) < _MAX_SHORT_RESPONSE:
        return True

    # Longer response: check if the last line/paragraph is a question
    last_line = stripped.rsplit("\n", 1)[-1].strip()
    if last_line.endswith("?") and len(last_line) < _MAX_TRAILING_QUESTION:
        return True

    return False


def _summarize_error(err: str, max_len: int = 80) -> str:
    """Extract a short reason from the error string.

    Uses the first line of the error, truncated. No pattern matching —
    the error strings come from Claude Code's tool layer and are already
    reasonably structured.
    """
    if not err:
        return "Unknown"
    first_line = err.split("\n", 1)[0].strip()
    if not first_line:
        return "Unknown"
    return first_line[:max_len]


# ── PostToolUseFailure handler ────────────────────────────────────────

def handle_post_tool_use_failure(payload: Dict[str, Any]) -> int:
    """Increment tool_failure or human_interrupt counters."""
    session_id = payload.get("session_id")
    if not session_id:
        return 0

    tool_name = payload.get("tool_name", "unknown")
    tool_type = classify_tool(tool_name).value
    is_interrupt = payload.get("is_interrupt", False)
    err = payload.get("error", "")

    with FileLock(_lock_file_for_session(session_id)):
        state = load_metrics_state(session_id)

        if is_interrupt:
            state["human_interrupts"] = state.get("human_interrupts", 0) + 1
            log.debug(f"PostToolUseFailure: human interrupt on {tool_name}")
        else:
            state["tool_failures_total"] = state.get("tool_failures_total", 0) + 1
            # Track which tool type caused the failure
            tfc = state.get("tool_failure_counts", {})
            tfc[tool_type] = tfc.get(tool_type, 0) + 1
            state["tool_failure_counts"] = tfc
            # Track failure reason keyed by tool_type + reason
            reason = _summarize_error(err)
            reason_key = f"{tool_type}: {reason}"
            trc = state.get("tool_failure_reasons", {})
            trc[reason_key] = trc.get(reason_key, 0) + 1
            state["tool_failure_reasons"] = trc
            log.debug(f"PostToolUseFailure: tool failure on {tool_name} -> {tool_type}: {reason}")

        save_metrics_state(session_id, state)

    return 0


# ── Token usage extraction ────────────────────────────────────────────

def _match_model_pricing(model: str) -> Tuple[float, float, float]:
    model_lower = model.lower()
    for prefix, pricing in MODEL_PRICING.items():
        if prefix in model_lower:
            return pricing
    return (3.0, 15.0, 0.30)


def extract_token_usage(transcript_path: Path) -> TokenMetric:
    """Read transcript JSONL and sum up token usage from assistant messages."""
    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    cost_usd = 0.0
    models_seen: Dict[str, int] = {}

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue

                if msg.get("type") != "assistant":
                    continue
                message = msg.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue

                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue

                model = message.get("model", "unknown")
                models_seen[model] = models_seen.get(model, 0) + 1

                inp = int(usage.get("input_tokens", 0))
                out = int(usage.get("output_tokens", 0))
                cache_create = int(usage.get("cache_creation_input_tokens", 0))
                cache_read = int(usage.get("cache_read_input_tokens", 0))

                totals["input_tokens"] += inp
                totals["output_tokens"] += out
                totals["cache_creation_input_tokens"] += cache_create
                totals["cache_read_input_tokens"] += cache_read

                input_price, output_price, cache_read_price = _match_model_pricing(model)
                cost_usd += (inp / 1_000_000) * input_price
                cost_usd += (out / 1_000_000) * output_price
                cost_usd += (cache_create / 1_000_000) * input_price
                cost_usd += (cache_read / 1_000_000) * cache_read_price

    except Exception as e:
        log.debug(f"extract_token_usage failed: {e}")

    return TokenMetric(
        token_input=totals["input_tokens"],
        token_output=totals["output_tokens"],
        token_cache_creation=totals["cache_creation_input_tokens"],
        token_cache_read=totals["cache_read_input_tokens"],
        token_total=sum(totals.values()),
        estimated_cost_usd=round(cost_usd, 6),
        models_seen=models_seen,
    )


# ── GitHub API ────────────────────────────────────────────────────────

def fetch_github_metrics(today_str: str) -> Tuple[Optional[str], GithubMetric]:
    """Fetch PR metrics from GitHub. Returns (username, GithubMetric)."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token or httpx is None:
        log.debug("GitHub: missing token or httpx, skipping")
        return None, GithubMetric()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    username = None
    result = GithubMetric()

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.get("https://api.github.com/user", headers=headers)
            if resp.status_code != 200:
                log.debug(f"GitHub /user failed: {resp.status_code}")
                return None, result
            username = resp.json().get("login")
            if not username:
                return None, result

            queries = {
                "github_prs_created": f"is:pr author:{username} created:{today_str}",
                "github_prs_merged": f"is:pr author:{username} is:merged merged:{today_str}",
                "github_prs_reviewed": f"is:pr reviewed-by:{username} created:>={today_str}",
            }

            counts: Dict[str, int] = {}
            for metric_name, q in queries.items():
                try:
                    resp = client.get(
                        "https://api.github.com/search/issues",
                        params={"q": q},
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        counts[metric_name] = resp.json().get("total_count", 0)
                    else:
                        log.debug(f"GitHub search '{metric_name}' failed: {resp.status_code}")
                except Exception as e:
                    log.debug(f"GitHub search '{metric_name}' error: {e}")

            result = GithubMetric(
                github_prs_created=counts.get("github_prs_created", 0),
                github_prs_merged=counts.get("github_prs_merged", 0),
                github_prs_reviewed=counts.get("github_prs_reviewed", 0),
            )

    except Exception as e:
        log.debug(f"GitHub API error: {e}")

    log.info(f"GitHub metrics for {username}: {result.model_dump()}")
    return username, result


# ── Jira API ──────────────────────────────────────────────────────────

def fetch_jira_metrics(today_str: str) -> Tuple[Optional[str], JiraMetric]:
    """Fetch ticket metrics from Jira. Returns (username, JiraMetric)."""
    jira_url = os.environ.get("JIRA_URL", "https://issues.redhat.com")
    jira_token = os.environ.get("JIRA_PERSONAL_TOKEN")
    jira_username = os.environ.get("JIRA_USERNAME")

    if not jira_token or not jira_username or httpx is None:
        log.debug("Jira: missing credentials or httpx, skipping")
        return jira_username, JiraMetric()

    headers = {
        "Authorization": f"Bearer {jira_token}",
        "Accept": "application/json",
    }

    result = JiraMetric()

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, verify=False) as client:
            jql = f'assignee = "{jira_username}" AND resolved >= startOfDay()'
            resp = client.get(
                f"{jira_url.rstrip('/')}/rest/api/2/search",
                params={"jql": jql, "maxResults": "0"},
                headers=headers,
            )
            if resp.status_code == 200:
                result = JiraMetric(
                    jira_tickets_resolved=resp.json().get("total", 0),
                )
            else:
                log.debug(f"Jira search failed: {resp.status_code} {resp.text[:200]}")

    except Exception as e:
        log.debug(f"Jira API error: {e}")

    log.info(f"Jira metrics for {jira_username}: {result.model_dump()}")
    return jira_username, result


# ── User ID resolution ────────────────────────────────────────────────

def resolve_user_id(
    session_id: str,
    github_username: Optional[str] = None,
    jira_username: Optional[str] = None,
) -> str:
    uid = os.environ.get("CC_USER_ID")
    if uid:
        return uid
    if github_username:
        return github_username
    if jira_username:
        return jira_username
    return hashlib.sha256(session_id.encode()).hexdigest()[:12]


# ── Build ClaudeSessionMetric from state + APIs ───────────────────────

def build_session_metric(
    session_id: str,
    user_id: str,
    metrics_state: Dict[str, Any],
    token_metrics: TokenMetric,
    github_metrics: GithubMetric,
    jira_metrics: JiraMetric,
) -> ClaudeSessionMetric:
    """Assemble the top-level metric model from all sources."""
    tool_calls_group = metrics_state.get("tool_calls", {})

    return ClaudeSessionMetric(
        session_id=session_id,
        user_id=user_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        token_metrics=token_metrics,
        github_metrics=github_metrics,
        jira_metrics=jira_metrics,
        tools_usage_metric=ToolsUsageMetric(
            tool_calls_total=metrics_state.get("tool_calls_total", 0),
            tool_calls_group=tool_calls_group,
        ),
        interrupt_metric=InterruptMetric(
            interrupt_tool_failure_total=metrics_state.get("tool_failures_total", 0),
            interrupt_tool_failure_count=metrics_state.get("tool_failure_counts", {}),
            interrupt_tool_reason_count=metrics_state.get("tool_failure_reasons", {}),
            interrupt_unclear_context=metrics_state.get("unclear_context", 0),
            interrupt_human=metrics_state.get("human_interrupts", 0),
        ),
    )


# ── Output file logging ───────────────────────────────────────────────

def write_session_output(metric: ClaudeSessionMetric) -> None:
    """Append the session metric as a JSON line to the output file.

    Path is controlled by CC_METRICS_OUTPUT_FILE env var; defaults to
    .claude/hooks/state/claude_session_output.txt
    """
    output_path = Path(
        os.environ.get("CC_METRICS_OUTPUT_FILE", str(DEFAULT_OUTPUT_FILE))
    )
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(metric.model_dump_json() + "\n")
        log.debug(f"Session metric written to {output_path}")
    except Exception as e:
        log.debug(f"write_session_output failed: {e}")


# ── Langfuse emission ─────────────────────────────────────────────────

def emit_metrics(langfuse: Langfuse, metric: ClaudeSessionMetric) -> None:
    """Create a Langfuse summary trace with numeric scores from the model."""
    all_scores = metric.to_flat_scores()

    with propagate_attributes(
        session_id=metric.session_id,
        user_id=metric.user_id,
        tags=["claude-code", "metrics"],
    ):
        with langfuse.start_as_current_span(
            name="Claude Code - Session Metrics",
            input={"session_id": metric.session_id, "user_id": metric.user_id},
            metadata={
                "source": "claude-code-metrics",
                "session_id": metric.session_id,
                "user_id": metric.user_id,
                "collected_at": metric.timestamp,
                "score_names": list(all_scores.keys()),
                "models_seen": metric.token_metrics.models_seen,
            },
        ) as metrics_span:
            for score_name, score_value in all_scores.items():
                try:
                    metrics_span.score(
                        name=score_name,
                        value=float(score_value),
                        data_type="NUMERIC",
                    )
                except Exception as e:
                    log.debug(f"Failed to emit score {score_name}: {e}")

            metrics_span.update(
                output=metric.model_dump(),
            )

    log.debug(f"Emitted {len(all_scores)} scores to Langfuse")


# ── Stop handler ──────────────────────────────────────────────────────

def handle_stop(payload: Dict[str, Any]) -> int:
    """Offload the heavy Stop work to a detached subprocess and return immediately.

    This keeps the hook latency near-zero for Claude Code. The subprocess
    runs _handle_stop_work() in the background after the session ends.

    Set CC_METRICS_SYNC=true to run synchronously (useful for debugging).
    """
    if os.environ.get("TRACE_TO_LANGFUSE", "").lower() != "true":
        return 0

    if SYNC_MODE:
        return _handle_stop_work(payload)

    # Write the payload to a temp file so the subprocess can read it.
    tmp = STATE_DIR / f"stop_payload_{os.getpid()}.json"
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--deferred", str(tmp)],
            start_new_session=True,   # detach from Claude Code's process group
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        log.debug(f"Failed to spawn deferred process: {e}; running synchronously")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return _handle_stop_work(payload)

    return 0


def _handle_stop_work(payload: Dict[str, Any]) -> int:
    """Execute the actual Stop logic: read state, extract tokens, emit to Langfuse."""
    start = time.time()

    public_key, secret_key, host = resolve_langfuse_credentials()
    if not public_key or not secret_key:
        log.debug("Missing Langfuse keys, skipping")
        return 0

    session_id = payload.get("session_id")
    transcript_path_str = payload.get("transcript_path")
    if not session_id:
        log.debug("Missing session_id in Stop payload")
        return 0

    transcript_path = None
    if transcript_path_str:
        try:
            transcript_path = Path(transcript_path_str).expanduser().resolve()
        except Exception:
            pass

    try:
        langfuse = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    except Exception as e:
        log.debug(f"Langfuse init failed: {e}")
        return 0

    try:
        # 1. Load accumulated metrics from state file
        with FileLock(_lock_file_for_session(session_id)):
            metrics_state = load_metrics_state(session_id)

            # Check if Claude's response is asking for clarification (plain text, no tool)
            last_msg = payload.get("last_assistant_message", "")
            if last_msg and is_clarification_request(last_msg):
                metrics_state["unclear_context"] = metrics_state.get("unclear_context", 0) + 1
                save_metrics_state(session_id, metrics_state)
                log.debug("Stop: detected clarification request in last_assistant_message")

        # 2. Extract token usage from transcript
        token_metrics = TokenMetric()
        if transcript_path and transcript_path.exists():
            token_metrics = extract_token_usage(transcript_path)
            log.debug(
                f"Token usage: {token_metrics.token_total} tokens, "
                f"${token_metrics.estimated_cost_usd}"
            )

        # 3. Resolve user identity
        user_id = resolve_user_id(session_id)

        # 4. Build the session metric model
        session_metric = build_session_metric(
            session_id=session_id,
            user_id=user_id,
            metrics_state=metrics_state,
            token_metrics=token_metrics,
            github_metrics=GithubMetric(),
            jira_metrics=JiraMetric(),
        )

        # 5. Write to output file
        write_session_output(session_metric)

        # 6. Emit to Langfuse
        emit_metrics(langfuse, session_metric)

        try:
            langfuse.flush()
        except Exception:
            pass

        dur = time.time() - start
        log.info(f"Metrics emitted in {dur:.2f}s (session={session_id}, user={user_id})")
        return 0

    except Exception as e:
        log.error(f"Stop handler failed: {e}")
        return 0

    finally:
        try:
            langfuse.shutdown()
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────────────────

def main() -> int:
    # Deferred mode: invoked by handle_stop via subprocess.
    # Payload was serialized to a temp file to avoid stdin piping issues.
    if len(sys.argv) >= 3 and sys.argv[1] == "--deferred":
        payload_file = Path(sys.argv[2])
        payload: Dict[str, Any] = {}
        try:
            payload = json.loads(payload_file.read_text(encoding="utf-8"))
        except Exception:
            return 0
        finally:
            try:
                payload_file.unlink(missing_ok=True)
            except Exception:
                pass
        return _handle_stop_work(payload)

    payload = read_hook_payload()
    hook_event = payload.get("hook_event_name", "")

    log.debug(f"metrics_hook invoked: hook_event={hook_event}")

    if hook_event == "PostToolUse":
        return handle_post_tool_use(payload)
    elif hook_event == "PostToolUseFailure":
        return handle_post_tool_use_failure(payload)
    elif hook_event == "Stop":
        return handle_stop(payload)
    else:
        log.debug(f"Unknown hook event: {hook_event}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
