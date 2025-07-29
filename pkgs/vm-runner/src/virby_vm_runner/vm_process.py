"""VM process lifecycle management for Virby VM."""

import asyncio
import atexit
import fcntl
import logging
import os
import random
import signal
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .api import VfkitAPIClient, VirtualMachineState
from .circuit_breaker import CircuitBreaker
from .config import VMConfig
from .constants import (
    DIFF_DISK_FILE_NAME,
    EFI_VARIABLE_STORE_FILE_NAME,
    SERIAL_LOG_FILE_NAME,
    SSHD_KEYS_SHARED_DIR_NAME,
)
from .exceptions import VMRuntimeError, VMStartupError
from .ip_discovery import IPDiscovery
from .ssh import SSHConnectivityTester

logger = logging.getLogger(__name__)


async def with_timeout(
    coro: Callable[..., Any], timeout: float, operation_name: str, *args, **kwargs
) -> Any:
    """Execute coroutine with timeout and proper error handling."""
    try:
        return await asyncio.wait_for(coro(*args, **kwargs), timeout=timeout)
    except asyncio.TimeoutError:
        raise VMRuntimeError(f"{operation_name} timed out after {timeout} seconds")


class VMProcessState:
    """VM process state enumeration."""

    RUNNING = "running"
    STOPPED = "stopped"
    PAUSED = "paused"
    UNKNOWN = "unknown"


async def cleanup_orphaned_vfkit_processes(working_dir: Path) -> None:
    """Async cleanup of orphaned vfkit processes using PID files.

    This function can be called during startup to clean up any processes
    that were orphaned due to unclean shutdowns.
    """
    pid_file = working_dir / "vfkit.pid"

    try:
        with open(pid_file, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            pid_str = f.read().strip()

            if not pid_str:
                pid_file.unlink(missing_ok=True)
                return

            try:
                pid = int(pid_str)
            except ValueError:
                logger.warning(f"Invalid PID in file {pid_file}: {pid_str}")
                pid_file.unlink(missing_ok=True)
                return

            if pid <= 0:
                logger.warning(f"Invalid PID value: {pid}")
                pid_file.unlink(missing_ok=True)
                return

            # Quick check if process exists
            try:
                os.kill(pid, 0)  # Process exists
                logger.info(f"Found orphaned vfkit process with PID {pid}")

                # Kill gracefully then forcefully if needed
                os.kill(pid, signal.SIGTERM)
                await asyncio.sleep(0.5)  # Non-blocking sleep

                try:
                    os.kill(pid, 0)  # Still exists?
                    os.kill(pid, signal.SIGKILL)
                    logger.info(f"Force killed orphaned vfkit process {pid}")
                except ProcessLookupError:
                    logger.info(f"Orphaned vfkit process {pid} terminated gracefully")

            except ProcessLookupError:
                # Process doesn't exist, just clean up the PID file
                logger.debug(f"Orphaned vfkit process {pid} no longer exists")

            pid_file.unlink(missing_ok=True)
            logger.info("Cleaned up orphaned vfkit process")

    except (FileNotFoundError, BlockingIOError):
        return
    except Exception as e:
        logger.error(f"Error cleaning up orphaned vfkit process: {e}")


def cleanup_orphaned_vfkit_processes_sync(working_dir: Path) -> None:
    """Synchronous wrapper for atexit compatibility."""
    try:
        # Try to get current event loop
        loop = asyncio.get_running_loop()
        # If we're in an async context, schedule async
        loop.create_task(cleanup_orphaned_vfkit_processes(working_dir))
    except RuntimeError:
        # No event loop, use synchronous
        _cleanup_orphaned_vfkit_processes_sync(working_dir)


def _cleanup_orphaned_vfkit_processes_sync(working_dir: Path) -> None:
    """Synchronous implementation for atexit."""
    pid_file = working_dir / "vfkit.pid"

    try:
        with open(pid_file, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            pid_str = f.read().strip()

            if not pid_str:
                pid_file.unlink(missing_ok=True)
                return

            try:
                pid = int(pid_str)
            except ValueError:
                logger.warning(f"Invalid PID in file {pid_file}: {pid_str}")
                pid_file.unlink(missing_ok=True)
                return

            if pid <= 0:
                logger.warning(f"Invalid PID value: {pid}")
                pid_file.unlink(missing_ok=True)
                return

            # Quick check if process exists
            try:
                os.kill(pid, 0)  # Process exists
                logger.info(f"Found orphaned vfkit process with PID {pid}")

                # Kill gracefully then forcefully if needed
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)  # Synchronous sleep for atexit

                try:
                    os.kill(pid, 0)  # Still exists?
                    os.kill(pid, signal.SIGKILL)
                    logger.info(f"Force killed orphaned vfkit process {pid}")
                except ProcessLookupError:
                    logger.info(f"Orphaned vfkit process {pid} terminated gracefully")

            except ProcessLookupError:
                # Process doesn't exist, just clean up the PID file
                logger.debug(f"Orphaned vfkit process {pid} no longer exists")

            pid_file.unlink(missing_ok=True)
            logger.info("Cleaned up orphaned vfkit process")

    except (FileNotFoundError, BlockingIOError):
        # File doesn't exist or is locked by active process
        return
    except Exception as e:
        logger.error(f"Error cleaning up orphaned vfkit process: {e}")


class VMProcess:
    """Manages VM process lifecycle independent of networking concerns."""

    def __init__(self, config: VMConfig, working_dir: Path):
        """Initialize VM process manager.

        Args:
            config: VM configuration
            working_dir: Working directory for VM files
        """
        self.config = config
        self.working_dir = working_dir

        # Validate working directory
        if not self.working_dir.exists():
            raise VMStartupError(f"Working directory does not exist: {self.working_dir}")
        if not self.working_dir.is_dir():
            raise VMStartupError(f"Working directory is not a directory: {self.working_dir}")

        # VM process state
        self.vm_process: asyncio.subprocess.Process | None = None
        self.mac_address = self._generate_mac_address()
        self.ip_discovery = IPDiscovery(self.mac_address)
        self._ip_address: str | None = None
        self._output_task: asyncio.Task | None = None
        self._shutdown_requested = False
        self._vfkit_api_port = self.config.port + 1

        # Process management
        self.pid_file = self.working_dir / "vfkit.pid"

        # Initialize vfkit API client
        self.api_client = VfkitAPIClient(
            api_port=self._vfkit_api_port,
            is_running_check=self.is_running,
        )

        # Initialize circuit breaker for API operations
        self._api_circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=10.0)

        # Setup cleanup handler
        atexit.register(self._cleanup_on_exit)

    def _generate_mac_address(self) -> str:
        """Generate a random MAC address for VM usage."""
        prefix = "02:94"  # Locally administered, unicast
        suffix = ":".join(f"{random.randint(0, 255):02x}" for _ in range(4))
        return f"{prefix}:{suffix}"

    def build_vfkit_command(self) -> list[str]:
        """Build vfkit command from configuration."""
        diff_disk = self.working_dir / DIFF_DISK_FILE_NAME
        efi_store = self.working_dir / EFI_VARIABLE_STORE_FILE_NAME
        sshd_keys = self.working_dir / SSHD_KEYS_SHARED_DIR_NAME

        cmd = [
            "vfkit",
            "--cpus",
            str(self.config.cores),
            "--memory",
            str(self.config.memory),
            "--bootloader",
            f"efi,variable-store={efi_store},create",
            "--device",
            f"virtio-blk,path={diff_disk}",
            "--device",
            f"virtio-fs,sharedDir={sshd_keys},mountTag=sshd-keys",
            "--device",
            f"virtio-net,nat,mac={self.mac_address}",
            "--restful-uri",
            f"tcp://localhost:{self._vfkit_api_port}",
            "--device",
            "virtio-rng",
            "--device",
            "virtio-balloon",
        ]

        if self.config.debug_enabled:
            serial_log = self.working_dir / SERIAL_LOG_FILE_NAME
            cmd.extend(["--device", f"virtio-serial,logFilePath={serial_log}"])

        if self.config.rosetta_enabled:
            cmd.extend(["--device", "rosetta,mountTag=rosetta"])

        return cmd

    async def _get_state_info(self, max_retries: int = 3) -> dict | None:
        """Get VM state via vfkit API with retry logic for transient failures."""
        for attempt in range(max_retries):
            try:
                return await self.api_client.get("/vm/state")
            except VMRuntimeError as e:
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    delay = (0.1 * (2**attempt)) + random.uniform(0, 0.05)
                    logger.debug(f"VM state query failed, retrying in {delay:.2f}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"VM state query failed after {max_retries} attempts: {e}")

        return None

    async def _get_state_info_with_breaker(self) -> dict | None:
        """Get VM state with circuit breaker protection."""
        try:
            return await self._api_circuit_breaker.call(self._get_state_info_raw)
        except VMRuntimeError:
            logger.warning("Circuit breaker prevented VM state query")
            return None

    async def _get_state_info_raw(self) -> dict | None:
        """Raw VM state query with no retry logic."""
        return await self.api_client.get("/vm/state")

    async def get_current_state(self) -> str:
        """Get current VM process state with validation and recovery.

        Returns:
            str: One of VMProcessState constants
        """
        if not self.is_running:
            return VMProcessState.STOPPED

        # Try to get state with circuit breaker
        state_info = await self._get_state_info_with_breaker()

        if not state_info:
            # If API is unavailable, check process status
            if self.vm_process and self.vm_process.returncode is None:
                logger.warning("VM API unavailable but process running")
                return VMProcessState.UNKNOWN
            else:
                return VMProcessState.STOPPED

        if "state" not in state_info:
            logger.warning("Invalid VM state response")
            return VMProcessState.UNKNOWN

        vm_state = state_info.get("state")
        if vm_state == VirtualMachineState.RUNNING:
            return VMProcessState.RUNNING
        elif vm_state == VirtualMachineState.PAUSED:
            return VMProcessState.PAUSED
        elif vm_state == VirtualMachineState.STOPPED:
            return VMProcessState.STOPPED
        else:
            logger.debug(f"Unhandled VM state returned: {vm_state}")
            return VMProcessState.UNKNOWN

    async def can_pause(self) -> bool:
        """Check if VM can be paused."""
        if not self.is_running:
            return False
        vm_state = await self._get_state_info()
        return vm_state.get("canPause", False) if vm_state else False

    async def can_resume(self) -> bool:
        """Check if VM can be resumed."""
        if not self.is_running:
            return False
        vm_state = await self._get_state_info()
        return vm_state.get("canResume", False) if vm_state else False

    async def _start_vm_process(self) -> None:
        """Start the VM process."""
        if self.vm_process is not None:
            raise VMStartupError("VM process is already running")

        cmd = self.build_vfkit_command()
        logger.info(f"Starting VM with command: {' '.join(cmd)}")

        try:
            kwargs: dict = {"cwd": self.working_dir}

            if self.config.debug_enabled:
                kwargs.update(
                    {
                        "stdout": asyncio.subprocess.PIPE,
                        "stderr": asyncio.subprocess.PIPE,
                    }
                )
            else:
                kwargs.update(
                    {
                        "stdout": asyncio.subprocess.DEVNULL,
                        "stderr": asyncio.subprocess.DEVNULL,
                    }
                )

            self.vm_process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
            logger.info(f"VM started with PID {self.vm_process.pid}")

            # Write PID file for external cleanup
            self._write_pid_file(self.vm_process.pid)

            # Start background task to consume output if debug is enabled
            if self.config.debug_enabled and self.vm_process.stdout and self.vm_process.stderr:
                self._output_task = asyncio.create_task(self._consume_vm_process_output())

        except Exception as e:
            raise VMStartupError(f"Failed to start VM process: {e}")

    async def _discover_ip_address(self) -> str:
        """Discover the VM's IP address via DHCP."""
        logger.info("Discovering VM IP address...")

        timeout = self.config.ip_discovery_timeout
        start_time = asyncio.get_event_loop().time()
        interval = 0.1  # Start with 100ms
        max_interval = 2.0  # Cap at 2s

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            # Check for shutdown signals
            await self._check_shutdown_signals()

            if self._shutdown_requested:
                raise VMRuntimeError("Shutdown requested during IP discovery")

            if self.vm_process and self.vm_process.returncode is not None:
                raise VMRuntimeError("VM process died during IP discovery")

            ip = await self.ip_discovery.discover_ip()
            if ip:
                logger.info(f"Discovered VM IP: {ip}")
                self._ip_address = ip
                return ip

            await asyncio.sleep(interval)
            # Exponential backoff: 100ms -> 200ms -> 400ms -> 800ms -> 1.6s -> 2s
            interval = min(interval * 2, max_interval)

        raise VMRuntimeError(f"Failed to discover VM IP within {timeout} seconds")

    async def _consume_vm_process_output(self) -> None:
        """Consume VM process (vfkit) stdout/stderr to prevent buffer overflow."""
        if not self.vm_process or not self.vm_process.stdout or not self.vm_process.stderr:
            return

        async def read_stream(stream, name):
            try:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    logger.debug(f"VM {name}: {line.decode().rstrip()}")
            except Exception as e:
                logger.debug(f"Error reading VM {name}: {e}")

        try:
            await asyncio.gather(
                read_stream(self.vm_process.stdout, "stdout"),
                read_stream(self.vm_process.stderr, "stderr"),
                return_exceptions=True,
            )
        except Exception as e:
            logger.error(f"Error consuming VM output: {e}")

    async def _check_shutdown_signals(self) -> None:
        """Check for shutdown signals from environment."""
        if os.environ.get("VIRBY_SHUTDOWN_REQUESTED"):
            logger.info("Early shutdown signal detected")
            self._shutdown_requested = True
            os.environ.pop("VIRBY_SHUTDOWN_REQUESTED", None)

    async def _monitor_vm(self) -> None:
        """Monitor VM process for unexpected death."""
        if self.vm_process:
            await self.vm_process.wait()

            # Log VM shutdown
            if self.vm_process.returncode == 0:
                logger.info("VM shut down normally")
            elif not self._shutdown_requested:
                logger.error(f"VM process died unexpectedly with code {self.vm_process.returncode}")

            # Clean up VM state so it can be restarted
            self._cleanup_vm_state()

    def _write_pid_file(self, pid: int) -> None:
        """Write process PID to file atomically."""
        try:
            # Write to temporary file first
            pid_dir = self.pid_file.parent
            with tempfile.NamedTemporaryFile(
                mode="w", dir=pid_dir, prefix=f"{self.pid_file.name}.tmp.", delete=False
            ) as tmp_file:
                tmp_file.write(str(pid))
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
                tmp_path = tmp_file.name

            # Atomic move to final location
            os.rename(tmp_path, self.pid_file)
            logger.debug(f"Wrote PID {pid} to {self.pid_file}")

        except Exception as e:
            logger.error(f"Error writing PID file: {e}")
            # Clean up temporary file if it exists
            try:
                if "tmp_path" in locals():
                    os.unlink(tmp_path)
            except Exception:
                pass

    def _validate_pid_file(self) -> bool:
        """Validate PID file format and content."""
        try:
            if not self.pid_file.exists():
                return False

            content = self.pid_file.read_text().strip()
            if not content:
                return False

            pid = int(content)
            if pid <= 0:
                return False

            # Check if process exists
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                # Process doesn't exist, remove stale PID file
                self._cleanup_pid_file()
                return False

        except (ValueError, OSError) as e:
            logger.warning(f"Invalid PID file {self.pid_file}: {e}")
            self._cleanup_pid_file()
            return False

    def _cleanup_pid_file(self) -> None:
        """Remove PID file."""
        try:
            self.pid_file.unlink(missing_ok=True)
            logger.debug(f"Removed PID file {self.pid_file}")
        except Exception as e:
            logger.error(f"Error removing PID file: {e}")

    def _cleanup_on_exit(self) -> None:
        """Cleanup handler called by atexit - must be synchronous."""
        logger.debug("atexit cleanup handler called")
        try:
            self._cleanup_process_sync()
            self._cleanup_pid_file()
        except Exception as e:
            logger.error(f"Error in atexit cleanup: {e}")

    def _cleanup_process_sync(self) -> None:
        """Synchronous process cleanup for atexit handler."""
        if self.vm_process and self.vm_process.returncode is None:
            try:
                pid = self.vm_process.pid
                logger.debug(f"Synchronously terminating VM process {pid}")

                try:
                    # Try graceful termination first
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(2)

                    # Force kill if still running
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # Already dead

                except ProcessLookupError:
                    pass  # Process already dead

            except Exception as e:
                logger.error(f"Error in synchronous process cleanup: {e}")

    def _cleanup_vm_state(self) -> None:
        """Clean up VM state after shutdown."""
        # Schedule API client cleanup
        if self.api_client:
            asyncio.create_task(self.api_client.close())

        # Cancel output task
        if self._output_task and not self._output_task.done():
            self._output_task.cancel()

        # Reset state variables
        self.vm_process = None
        self._ip_address = None
        self._output_task = None

        logger.debug("VM state cleaned up")
        # Cleanup PID file
        self._cleanup_pid_file()

    async def start(self) -> str:
        """Start the VM and wait for it to be ready.

        Returns:
            IP address of the started VM
        """
        logger.info("Starting Virby VM...")

        try:
            # Start VM process
            await self._start_vm_process()

            # Start monitoring task
            asyncio.create_task(self._monitor_vm())

            # Pre-create SSH tester while discovering IP
            ssh_tester = SSHConnectivityTester(self.working_dir)

            # Discover IP
            ip = await self._discover_ip_address()

            logger.info(f"VM IP discovered: {ip}, testing SSH connectivity...")

            # Wait for SSH
            if not await self._wait_for_ssh(ip, ssh_tester):
                raise VMRuntimeError("SSH did not become ready in time")

            logger.info(f"VM is ready at {ip}")
            return ip

        except Exception as e:
            logger.error(f"Failed to start VM: {e}")
            await self.stop()
            raise

    async def _wait_for_ssh(self, ip: str, ssh_tester) -> bool:
        """Wait for SSH to become ready."""
        logger.info(f"Waiting for SSH connectivity to {ip}")

        timeout = self.config.ssh_ready_timeout
        start_time = asyncio.get_event_loop().time()
        check_interval = 0.5

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if await ssh_tester.test_connectivity(ip, timeout=5):
                logger.info("SSH is ready")
                return True

            await asyncio.sleep(check_interval)
            # Gradual backoff
            check_interval = min(check_interval * 1.5, 1.0)

        logger.warning(f"SSH not ready within {timeout} seconds")
        return False

    async def stop(self, timeout: int = 30) -> None:
        """Stop the VM gracefully."""
        logger.info("Stopping VM...")
        self._shutdown_requested = True

        # Close API client first
        await self.api_client.close()

        # Cancel output task
        if self._output_task and not self._output_task.done():
            self._output_task.cancel()
            try:
                await self._output_task
            except asyncio.CancelledError:
                pass

        if self.vm_process and self.vm_process.returncode is None:
            try:
                self.vm_process.terminate()
                logger.info(f"Sent SIGTERM to VM process {self.vm_process.pid}")

                # Wait for graceful shutdown
                try:
                    await asyncio.wait_for(self.vm_process.wait(), timeout=timeout)
                    logger.info("VM stopped gracefully")
                except asyncio.TimeoutError:
                    logger.warning("VM did not stop gracefully, killing...")
                    self.vm_process.kill()
                    await self.vm_process.wait()
                    logger.info("VM killed")
            except Exception as e:
                logger.error(f"Error stopping VM: {e}")

        self._cleanup_vm_state()

    async def pause(self, timeout: int = 30) -> None:
        """Pause the VM via the vfkit API with timeout."""
        logger.info("Pausing the VM...")

        if not self.is_running:
            raise VMRuntimeError("Cannot pause: VM is not running")

        # Check if VM can be paused with timeout
        can_pause = await with_timeout(self.can_pause, 5.0, "Can pause check")

        if not can_pause:
            raise VMRuntimeError("VM cannot be paused in current state")

        try:
            data = {"state": "Pause"}
            await with_timeout(
                lambda: self.api_client.post("/vm/state", data),
                timeout=timeout,
                operation_name="VM pause",
            )
            logger.info("VM paused successfully")

        except VMRuntimeError:
            raise
        except Exception as e:
            raise VMRuntimeError(f"Error pausing VM: {e}")

    async def resume(self, timeout: int = 30) -> None:
        """Resume the VM via the vfkit API with timeout."""
        logger.info("Resuming the VM...")

        if not self.is_running:
            raise VMRuntimeError("Cannot resume: VM is not running")

        # Check if VM can be resumed with timeout
        can_resume = await with_timeout(self.can_resume, 5.0, "Can resume check")

        if not can_resume:
            raise VMRuntimeError("VM cannot be resumed in current state")

        try:
            data = {"state": "Resume"}
            await with_timeout(
                lambda: self.api_client.post("/vm/state", data),
                timeout=timeout,
                operation_name="VM resume",
            )
            logger.info("VM resumed successfully")

        except VMRuntimeError:
            raise
        except Exception as e:
            raise VMRuntimeError(f"Error resuming VM: {e}")

    async def safe_pause_or_stop(self, timeout: int = 30) -> bool:
        """Attempt to pause VM with progressive timeout, fall back to stop.

        Args:
            timeout: Total timeout for the operation

        Returns:
            bool: True if paused, False if stopped
        """
        if not self.is_running:
            logger.debug("VM not running, nothing to pause or stop")
            return False

        # Try to pause with shorter timeout first
        try:
            pause_timeout = min(timeout // 2, 15)  # Half timeout or 15s max
            if await with_timeout(self.can_pause, 3.0, "Can pause check"):
                await self.pause(pause_timeout)
                return True
            else:
                logger.debug("VM cannot be paused, falling back to stop")

        except VMRuntimeError as e:
            logger.warning(f"Failed to pause VM: {e}, falling back to stop")

        # Fall back to stop with remaining timeout
        stop_timeout = max(timeout - pause_timeout if "pause_timeout" in locals() else timeout, 10)
        await self.stop(stop_timeout)
        return False

    async def safe_resume_or_start(self) -> str:
        """Attempt to resume VM, fall back to start if resume fails.

        Returns:
            str: IP address of the VM
        """
        current_state = await self.get_current_state()

        # If VM is already running, return IP
        if current_state == VMProcessState.RUNNING:
            if self._ip_address:
                return self._ip_address
            else:
                logger.debug("VM running but no cached IP found, rediscovering...")
                ip = await self._discover_ip_address()
                return ip

        # If VM is paused, try to resume
        if current_state == VMProcessState.PAUSED:
            try:
                if await self.can_resume():
                    logger.info("Attempting to resume paused VM instead of starting...")
                    await self.resume()

                    # VM should now be running, return cached IP or rediscover
                    if self._ip_address:
                        logger.info(f"Successfully resumed VM at {self._ip_address}")
                        return self._ip_address
                    else:
                        # IP might have changed, rediscover
                        logger.debug("VM resumed but IP not cached, rediscovering...")
                        ip = await self._discover_ip_address()
                        return ip
                else:
                    logger.debug("VM cannot be resumed, falling back to start")
            except Exception as e:
                logger.warning(f"Failed to resume VM, falling back to start: {e}")
                # Ensure VM is properly stopped before starting
                await self.stop()

        # Fall back to normal start
        logger.info("Starting VM from stopped state...")
        return await self.start()

    @property
    def is_running(self) -> bool:
        """Check if VM is running."""
        return self.vm_process is not None and self.vm_process.returncode is None

    @property
    def ip_address(self) -> str | None:
        """Get VM IP address."""
        return self._ip_address
