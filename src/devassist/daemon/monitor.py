"""Background source monitoring for DevAssist daemon.

Periodically checks for new important items and sends notifications.
"""

import asyncio
import json
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from devassist.core.orchestrator import ClaudeOrchestrator
from devassist.daemon.notifier import (
    Notification,
    NotificationBackend,
    Priority,
    create_notifier,
)


# Prompt for checking updates
CHECK_UPDATES_PROMPT = """Check for new important items that need immediate attention.

Look for:
- Urgent emails requiring immediate response
- Direct Slack messages or mentions
- JIRA issues assigned to me with approaching deadlines
- GitHub PRs awaiting my review or with new comments

Only return items that are:
1. NEW since the last check
2. Actually important (not routine notifications)
3. Require some action from me

For each important item, provide:
- Source (GitHub/Slack/JIRA)
- Title (brief description)
- Why it's important
- URL if available

If there are no new important items, just say "No new important items."
"""


class SourceMonitor:
    """Monitors configured sources for new important items."""

    DEFAULT_CHECK_INTERVAL = 300  # 5 minutes
    STATE_FILENAME = "daemon_state.json"

    def __init__(
        self,
        orchestrator: ClaudeOrchestrator | None = None,
        notifier: NotificationBackend | None = None,
        check_interval: int | None = None,
        state_dir: Path | str | None = None,
    ) -> None:
        """Initialize the source monitor.

        Args:
            orchestrator: Claude orchestrator for querying sources.
            notifier: Notification backend for sending alerts.
            check_interval: Seconds between checks.
            state_dir: Directory for persisting state.
        """
        self.orchestrator = orchestrator or ClaudeOrchestrator()
        self.notifier = notifier or create_notifier()
        self.check_interval = check_interval or self.DEFAULT_CHECK_INTERVAL

        if state_dir is None:
            state_dir = Path.home() / ".devassist"
        self.state_dir = Path(state_dir)
        self.state_path = self.state_dir / self.STATE_FILENAME

        self._running = False
        self._last_check: datetime | None = None
        self._seen_items: set[str] = set()

        # Load persisted state
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state from disk."""
        if not self.state_path.exists():
            return

        try:
            with open(self.state_path) as f:
                state = json.load(f)

            if "last_check" in state:
                self._last_check = datetime.fromisoformat(state["last_check"])

            if "seen_items" in state:
                self._seen_items = set(state["seen_items"])

        except Exception as e:
            print(f"Warning: Could not load daemon state: {e}")

    def _save_state(self) -> None:
        """Persist state to disk."""
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)

            state = {
                "last_check": self._last_check.isoformat() if self._last_check else None,
                "seen_items": list(self._seen_items)[-100],  # Keep last 100
            }

            with open(self.state_path, "w") as f:
                json.dump(state, f, indent=2)

        except Exception as e:
            print(f"Warning: Could not save daemon state: {e}")

    async def start(self) -> None:
        """Start the monitoring loop.

        This runs indefinitely until stop() is called or a signal is received.
        """
        self._running = True
        print(f"Daemon started. Checking every {self.check_interval} seconds...")

        # Set up signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        try:
            while self._running:
                try:
                    await self._check_for_updates()
                except Exception as e:
                    print(f"Error during check: {e}")

                # Sleep in small increments to allow for quick shutdown
                for _ in range(self.check_interval):
                    if not self._running:
                        break
                    await asyncio.sleep(1)

        finally:
            self._save_state()
            await self.notifier.close()
            print("Daemon stopped.")

    def _handle_signal(self) -> None:
        """Handle shutdown signals."""
        print("\nShutdown signal received...")
        self._running = False

    def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False

    async def _check_for_updates(self) -> None:
        """Check for new important items and send notifications."""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking for updates...")

        # Build context-aware prompt
        since = self._last_check or (datetime.now() - timedelta(hours=1))
        prompt = f"""Current time: {datetime.now().isoformat()}
Last check: {since.isoformat()}

{CHECK_UPDATES_PROMPT}
"""

        try:
            response = await self.orchestrator.query(prompt)

            # Parse response for new items
            new_items = self._parse_response(response)

            for item in new_items:
                item_id = f"{item['source']}:{item['title'][:50]}"

                if item_id not in self._seen_items:
                    self._seen_items.add(item_id)
                    await self._send_notification(item)

            self._last_check = datetime.now()
            self._save_state()

            if new_items:
                print(f"  Found {len(new_items)} new important items")
            else:
                print("  No new important items")

        except Exception as e:
            print(f"  Error checking updates: {e}")

    def _parse_response(self, response: str) -> list[dict[str, Any]]:
        """Parse Claude's response into structured items.

        Args:
            response: Raw response text.

        Returns:
            List of parsed items.
        """
        items = []

        # Skip if no important items
        if "no new important items" in response.lower():
            return items

        # Simple parsing: look for patterns like "Source:", "Title:", etc.
        # This is a basic parser - Claude's response format can vary
        lines = response.strip().split("\n")
        current_item: dict[str, Any] = {}

        for line in lines:
            line = line.strip()
            if not line:
                if current_item:
                    items.append(current_item)
                    current_item = {}
                continue

            lower_line = line.lower()

            if lower_line.startswith("source:"):
                if current_item:
                    items.append(current_item)
                current_item = {"source": line.split(":", 1)[1].strip()}
            elif lower_line.startswith("title:"):
                current_item["title"] = line.split(":", 1)[1].strip()
            elif lower_line.startswith("url:") or lower_line.startswith("link:"):
                current_item["url"] = line.split(":", 1)[1].strip()
            elif lower_line.startswith("why:") or lower_line.startswith("reason:"):
                current_item["reason"] = line.split(":", 1)[1].strip()
            elif "- " in line and "source" not in current_item:
                # Bullet point format
                current_item["title"] = line.lstrip("- ").strip()
                current_item["source"] = "Unknown"

        if current_item:
            items.append(current_item)

        # Filter to only items with at least source and title
        return [
            item for item in items
            if item.get("source") and item.get("title")
        ]

    async def _send_notification(self, item: dict[str, Any]) -> None:
        """Send a notification for an important item.

        Args:
            item: Parsed item dictionary.
        """
        # Determine priority based on content
        priority = Priority.NORMAL
        title = item.get("title", "")
        reason = item.get("reason", "")

        if any(word in (title + reason).lower() for word in ["urgent", "critical", "blocking"]):
            priority = Priority.URGENT
        elif any(word in (title + reason).lower() for word in ["important", "deadline", "review"]):
            priority = Priority.HIGH

        notification = Notification(
            title=f"[{item.get('source', 'Unknown')}] {title[:50]}",
            body=reason or title,
            source=item.get("source", "Unknown"),
            url=item.get("url"),
            priority=priority,
        )

        await self.notifier.send(notification)


async def run_daemon(
    check_interval: int = 300,
    desktop_notifications: bool = True,
) -> None:
    """Run the daemon with the specified settings.

    Args:
        check_interval: Seconds between checks.
        desktop_notifications: Enable desktop notifications.
    """
    orchestrator = ClaudeOrchestrator()
    notifier = create_notifier(desktop=desktop_notifications)

    monitor = SourceMonitor(
        orchestrator=orchestrator,
        notifier=notifier,
        check_interval=check_interval,
    )

    await monitor.start()
