"""Desktop notification system for DevAssist daemon.

Provides cross-platform desktop notifications using the desktop-notifier library.
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

# Desktop notifier import - optional, checked at runtime
try:
    from desktop_notifier import DesktopNotifier as DN
    from desktop_notifier import Urgency

    NOTIFIER_AVAILABLE = True
except ImportError:
    NOTIFIER_AVAILABLE = False
    DN = None  # type: ignore
    Urgency = None  # type: ignore


class Priority(str, Enum):
    """Notification priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class Notification:
    """A notification to be sent to the user."""

    title: str
    body: str
    source: str
    url: str | None = None
    priority: Priority = Priority.NORMAL
    icon: str | None = None


class NotificationBackend(Protocol):
    """Protocol for notification backends."""

    async def send(self, notification: Notification) -> bool:
        """Send a notification.

        Args:
            notification: The notification to send.

        Returns:
            True if sent successfully, False otherwise.
        """
        ...

    async def close(self) -> None:
        """Clean up resources."""
        ...


class DesktopNotifier(NotificationBackend):
    """Cross-platform desktop notifications using desktop-notifier library."""

    def __init__(self, app_name: str = "DevAssist") -> None:
        """Initialize the desktop notifier.

        Args:
            app_name: Application name shown in notifications.
        """
        self.app_name = app_name
        self._notifier: DN | None = None

    def _get_notifier(self) -> DN:
        """Get or create the notifier instance.

        Returns:
            DesktopNotifier instance.

        Raises:
            RuntimeError: If desktop-notifier is not available.
        """
        if not NOTIFIER_AVAILABLE:
            raise RuntimeError(
                "desktop-notifier not installed. Run: pip install desktop-notifier"
            )

        if self._notifier is None:
            self._notifier = DN(app_name=self.app_name)

        return self._notifier

    def _map_priority(self, priority: Priority) -> "Urgency":
        """Map Priority enum to desktop-notifier Urgency.

        Args:
            priority: Our priority level.

        Returns:
            Corresponding Urgency level.
        """
        if not NOTIFIER_AVAILABLE:
            return None  # type: ignore

        mapping = {
            Priority.LOW: Urgency.Low,
            Priority.NORMAL: Urgency.Normal,
            Priority.HIGH: Urgency.Critical,
            Priority.URGENT: Urgency.Critical,
        }
        return mapping.get(priority, Urgency.Normal)

    async def send(self, notification: Notification) -> bool:
        """Send a desktop notification.

        Args:
            notification: The notification to send.

        Returns:
            True if sent successfully.
        """
        try:
            notifier = self._get_notifier()

            await notifier.send(
                title=notification.title,
                message=notification.body,
                urgency=self._map_priority(notification.priority),
            )
            return True

        except Exception as e:
            print(f"Failed to send notification: {e}")
            return False

    async def close(self) -> None:
        """Clean up notifier resources."""
        if self._notifier is not None:
            # desktop-notifier doesn't have a close method,
            # but we clear the reference
            self._notifier = None


class ConsoleNotifier(NotificationBackend):
    """Fallback notifier that prints to console."""

    def __init__(self) -> None:
        """Initialize console notifier."""
        pass

    async def send(self, notification: Notification) -> bool:
        """Print notification to console.

        Args:
            notification: The notification to display.

        Returns:
            Always True.
        """
        priority_icons = {
            Priority.LOW: "[dim]",
            Priority.NORMAL: "",
            Priority.HIGH: "[yellow]!",
            Priority.URGENT: "[red]!!",
        }

        icon = priority_icons.get(notification.priority, "")
        print(f"\n{icon}[{notification.source}] {notification.title}")
        print(f"  {notification.body}")
        if notification.url:
            print(f"  Link: {notification.url}")
        print()

        return True

    async def close(self) -> None:
        """No cleanup needed for console."""
        pass


class CompositeNotifier(NotificationBackend):
    """Sends notifications to multiple backends."""

    def __init__(self, backends: list[NotificationBackend]) -> None:
        """Initialize with multiple backends.

        Args:
            backends: List of notification backends to use.
        """
        self.backends = backends

    async def send(self, notification: Notification) -> bool:
        """Send to all backends.

        Args:
            notification: The notification to send.

        Returns:
            True if at least one backend succeeded.
        """
        results = await asyncio.gather(
            *[backend.send(notification) for backend in self.backends],
            return_exceptions=True,
        )

        # Return True if any backend succeeded
        return any(r is True for r in results)

    async def close(self) -> None:
        """Close all backends."""
        await asyncio.gather(
            *[backend.close() for backend in self.backends],
            return_exceptions=True,
        )


def create_notifier(desktop: bool = True, console: bool = False) -> NotificationBackend:
    """Create a notifier with the specified backends.

    Args:
        desktop: Enable desktop notifications.
        console: Enable console output.

    Returns:
        A configured notifier.
    """
    backends: list[NotificationBackend] = []

    if desktop:
        if NOTIFIER_AVAILABLE:
            backends.append(DesktopNotifier())
        else:
            print("Warning: desktop-notifier not available, using console only")
            backends.append(ConsoleNotifier())

    if console:
        backends.append(ConsoleNotifier())

    if not backends:
        backends.append(ConsoleNotifier())

    if len(backends) == 1:
        return backends[0]

    return CompositeNotifier(backends)
