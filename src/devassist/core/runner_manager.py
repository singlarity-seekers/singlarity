"""Runner process lifecycle management for DevAssist.

Handles starting, stopping, and monitoring the background runner process.
"""

import logging
import multiprocessing
import os
import signal
import time
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from devassist.utils.process import (
    acquire_lock,
    is_process_running,
    read_pid_file,
    release_lock,
    write_pid_file,
)

logger = logging.getLogger(__name__)


class RunnerStatus(BaseModel):
    """Status of the background runner."""

    status: str  # "not_running", "running", "error"
    pid: int | None = None

    def to_dict(self) -> dict[str, int | str | None]:
        """Convert to dictionary.

        Returns:
            Dictionary representation of status.
        """
        return {"status": self.status, "pid": self.pid}


class RunnerManager:
    """Manages the lifecycle of the background runner process.

    Handles:
    - Starting background process
    - Stopping running process (graceful and forced)
    - Checking process status
    - Managing PID and lock files
    """

    def __init__(self, workspace_dir: Path | str | None = None) -> None:
        """Initialize RunnerManager.

        Args:
            workspace_dir: Path to workspace directory. Defaults to ~/.devassist
        """
        if workspace_dir is None:
            workspace_dir = Path.home() / ".devassist"
        self.workspace_dir = Path(workspace_dir)
        self.pid_file = self.workspace_dir / "runner.pid"
        self.lock_file = self.workspace_dir / "runner.lock"

        # Ensure directories exist
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / "logs").mkdir(exist_ok=True)

    def is_running(self) -> bool:
        """Check if runner is currently running.

        Returns:
            True if running, False otherwise.
        """
        pid = read_pid_file(self.pid_file)
        if pid is None:
            return False

        if is_process_running(pid):
            return True

        # Clean up stale PID file
        self.pid_file.unlink(missing_ok=True)
        return False

    def get_status(self) -> RunnerStatus:
        """Get current runner status.

        Returns:
            RunnerStatus object with current state.
        """
        if not self.is_running():
            return RunnerStatus(status="not_running", pid=None)

        pid = read_pid_file(self.pid_file)
        return RunnerStatus(status="running", pid=pid)

    def start(self, target: Callable[[], None], daemon: bool = True) -> None:
        """Start the background runner process.

        Args:
            target: The function to run in the background.
            daemon: Whether to run as daemon process.

        Raises:
            RuntimeError: If runner is already running or cannot acquire lock.
        """
        # Check if already running
        if self.is_running():
            raise RuntimeError("Runner is already running")

        # Try to acquire lock
        if not acquire_lock(self.lock_file, timeout=0.1):
            raise RuntimeError("Could not acquire lock - another instance may be starting")

        try:
            # Create and start process
            process = multiprocessing.Process(target=target, daemon=daemon)
            process.start()

            # Write PID file
            if process.pid is not None:
                write_pid_file(self.pid_file, process.pid)
                logger.info(f"Started runner process (PID: {process.pid})")
            else:
                raise RuntimeError("Failed to start process - no PID assigned")

        except Exception as e:
            # Clean up on failure
            release_lock(self.lock_file)
            raise RuntimeError(f"Failed to start runner: {e}") from e

    def stop(self, force: bool = False, timeout: float = 10.0) -> None:
        """Stop the background runner process.

        Args:
            force: If True, send SIGKILL immediately. If False, try graceful shutdown.
            timeout: Maximum time to wait for graceful shutdown (seconds).
        """
        pid = read_pid_file(self.pid_file)
        if pid is None:
            logger.info("No runner process to stop")
            return

        if not is_process_running(pid):
            logger.info(f"Process {pid} is not running - cleaning up")
            self._cleanup()
            return

        try:
            if force:
                # Force kill immediately
                logger.info(f"Force killing process {pid}")
                os.kill(pid, signal.SIGKILL)
            else:
                # Try graceful shutdown
                logger.info(f"Sending SIGTERM to process {pid}")
                os.kill(pid, signal.SIGTERM)

                # Wait for process to exit
                start_time = time.time()
                while time.time() - start_time < timeout:
                    if not is_process_running(pid):
                        logger.info("Process exited gracefully")
                        break
                    time.sleep(0.1)
                else:
                    # Timeout - force kill
                    logger.warning(f"Graceful shutdown timeout - force killing {pid}")
                    os.kill(pid, signal.SIGKILL)

        except ProcessLookupError:
            # Process already dead
            logger.info(f"Process {pid} already exited")
        except PermissionError as e:
            logger.error(f"Permission denied when stopping process {pid}: {e}")
            raise
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        """Clean up PID and lock files."""
        self.pid_file.unlink(missing_ok=True)
        release_lock(self.lock_file)
        logger.debug("Cleaned up runner files")

    def get_log_path(self) -> Path:
        """Get path to runner log file.

        Returns:
            Path to log file.
        """
        return self.workspace_dir / "logs" / "runner.log"
