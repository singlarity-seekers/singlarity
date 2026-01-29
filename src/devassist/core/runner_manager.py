"""Runner process lifecycle management for DevAssist.

Handles starting, stopping, and monitoring the background runner process.
"""

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

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

    def start(
        self,
        interval: int | None = None,
        prompt: str | None = None,
        resume: bool = False,
        session_id: str | None = None,
    ) -> None:
        """Start the background runner process.

        Args:
            interval: Interval in minutes between executions.
            prompt: Custom prompt to execute.
            resume: Resume the most recent session.
            session_id: Specific session ID (or prefix) to resume.

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
            # Use subprocess to spawn a truly independent process
            log_path = self.get_log_path()

            # Open log file for stdout/stderr redirection
            log_file = open(log_path, "a")

            # Build environment: start with current env, then source shell profile
            env = os.environ.copy()

            # Source user's shell profile to get MCP credentials and other env vars
            # This ensures background process has access to vars like JIRA_*, GITHUB_TOKEN
            shell_profile = self._get_shell_profile_vars()
            env.update(shell_profile)
            if interval is not None:
                env["DEVASSIST_RUNNER_INTERVAL"] = str(interval)
            if prompt is not None:
                env["DEVASSIST_RUNNER_PROMPT"] = prompt
            if resume:
                env["DEVASSIST_RUNNER_RESUME"] = "1"
            if session_id is not None:
                env["DEVASSIST_RUNNER_SESSION_ID"] = session_id

            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "from devassist.cli.ai import run_background_runner; run_background_runner()",
                ],
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # Detach from parent process group
                env=env,
            )

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

    def _get_shell_profile_vars(self) -> dict[str, str]:
        """Source user's shell profile and extract environment variables.

        Sources ~/.zshrc or ~/.bashrc to get MCP credentials and other
        environment variables that may not be in the current process.

        Returns:
            Dictionary of environment variables from shell profile.
        """
        shell_profile = Path.home() / ".zshrc"
        if not shell_profile.exists():
            shell_profile = Path.home() / ".bashrc"
        if not shell_profile.exists():
            logger.debug("No shell profile found (.zshrc or .bashrc)")
            return {}

        try:
            # Source the profile and print all environment variables
            result = subprocess.run(
                ["bash", "-c", f"source {shell_profile} 2>/dev/null && env"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                logger.debug(f"Failed to source shell profile: {result.stderr}")
                return {}

            # Parse env output into dict
            env_vars = {}
            for line in result.stdout.splitlines():
                if "=" in line:
                    key, _, value = line.partition("=")
                    # Only include MCP-relevant variables
                    if key.startswith(("JIRA_", "GITHUB_", "SLACK_", "GOOGLE_", "ANTHROPIC_")):
                        env_vars[key] = value

            logger.debug(f"Sourced {len(env_vars)} MCP-related env vars from shell profile")
            return env_vars
        except subprocess.TimeoutExpired:
            logger.warning("Timeout sourcing shell profile")
            return {}
        except Exception as e:
            logger.warning(f"Error sourcing shell profile: {e}")
            return {}
