"""Daemon module for DevAssist.

Provides background monitoring and notification capabilities.
"""

from devassist.daemon.monitor import SourceMonitor
from devassist.daemon.notifier import DesktopNotifier, Notification

__all__ = ["SourceMonitor", "DesktopNotifier", "Notification"]
