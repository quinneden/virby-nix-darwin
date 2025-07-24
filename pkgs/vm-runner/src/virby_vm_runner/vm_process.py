"""VM process lifecycle management for Virby VM."""

import asyncio
import atexit
import logging
import os
import random
import signal
import time
from pathlib import Path

import httpx

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


def cleanup_orphaned_vfkit_processes(working_dir: Path) -> None:
    """
    Cleanup orphaned vfkit processes using PID files.

    This function can be called during startup to clean up any processes
    that were orphaned due to unclean shutdowns.
    """
    pid_file = working_dir / "vfkit.pid"

    # Quick check - if no PID file, no cleanup needed
    if not pid_file.exists():
        return

    try:
        pid_str = pid_file.read_text().strip()
        if not pid_str:  # Empty file
            pid_file.unlink()
            return

        pid = int(pid_str)

        # Quick check if process exists
        try:
            os.kill(pid, 0)  # Process exists
            logger.info(f"Found orphaned vfkit process with PID {pid}")

            # Kill gracefully then forcefully if needed
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)  # Reduced wait time from 1s to 0.5s

            try:
                os.kill(pid, 0)  # Still exists?
                os.kill(pid, signal.SIGKILL)
                logger.info(f"Force killed orphaned vfkit process {pid}")
            except ProcessLookupError:
                logger.info(f"Orphaned vfkit process {pid} terminated gracefully")

        except ProcessLookupError:
            # Process doesn't exist, just clean up the PID file
            logger.debug(f"Orphaned vfkit process {pid} no longer exists")

        pid_file.unlink()
        logger.info("Cleaned up orphaned vfkit process")

    except (ValueError, OSError) as e:
        logger.error(f"Error cleaning up orphaned vfkit process: {e}")
        try:
            pid_file.unlink()
        except Exception:
            pass


class VMProcess:
    """Manages VM process lifecycle independent of networking concerns."""

    def __init__(self, config: VMConfig, working_dir: Path):
        """
        Initialize VM process manager.

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

    async def _vfkit_api_request(
        self, endpoint: str = "/vm/state", method: str = "POST", data: dict = {}
    ) -> dict | None:
        """Make a request to the VM's restful API."""
        if not self.is_running:
            raise VMRuntimeError("Cannot make API request: VM is not running")

        url = f"http://localhost:{self._vfkit_api_port}{endpoint}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(method, url, json=data)
                response.raise_for_status()
                return response.json() or None

        except httpx.HTTPError as e:
            raise VMRuntimeError(f"vfkit API request failed: {e}")
        except Exception as e:
            raise VMRuntimeError(f"Unexpected error in vfkit API request: {e}")

    async def _get_vm_state(self) -> dict:
        """Get the current state of the VM via vfkit API."""
        return await self._vfkit_api_request(method="GET") or {}

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
        interval = 0.1  # Start with 100ms instead of 1s for faster discovery
        max_interval = 2.0  # Reduced max interval from 5s to 2s

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
        """Write process PID to file for external cleanup."""
        try:
            self.pid_file.write_text(str(pid))
            logger.debug(f"Wrote PID {pid} to {self.pid_file}")
        except Exception as e:
            logger.error(f"Error writing PID file: {e}")

    def _cleanup_pid_file(self) -> None:
        """Remove PID file."""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
                logger.debug(f"Removed PID file {self.pid_file}")
        except Exception as e:
            logger.error(f"Error removing PID file: {e}")

    def _cleanup_on_exit(self) -> None:
        """Cleanup handler called by atexit."""
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
        # Cancel output task
        if self._output_task and not self._output_task.done():
            self._output_task.cancel()

        # Reset VM state
        self.vm_process = None
        self._ip_address = None
        self._output_task = None

        # Cleanup PID file
        self._cleanup_pid_file()

    async def start(self) -> str:
        """
        Start the VM and wait for it to be ready.

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
        """Pause the VM"""
        logger.info("Pausing the VM...")
        if self.vm_process and self.vm_process.returncode is None:
            vm_state = await self._get_vm_state()
            can_pause = vm_state.get("canPause", False)

            if not can_pause:
                logger.warning("VM cannot be paused, attempting to stop instead...")
                await self.stop(timeout)
                return
            else:
                try:
                    await self._vfkit_api_request(data={"state": "Pause"})
                    logger.info("VM paused")
                except Exception as e:
                    logger.error(f"Error pausing VM: {e}")

    async def resume(self) -> None:
        """Pause the VM"""
        logger.info("Resuming the VM...")
        if self.vm_process and self.vm_process.returncode is None:
            vm_state = await self._get_vm_state()
            can_resume = vm_state.get("canResume", False)

            if not can_resume:
                logger.warning("VM cannot resume, attempting to start instead...")
                await self.start()
                return
            else:
                try:
                    await self._vfkit_api_request(data={"state": "Resume"})
                    logger.info("VM resumed")
                except Exception as e:
                    logger.error(f"Error resuming VM: {e}")

    @property
    def is_running(self) -> bool:
        """Check if VM is running."""
        return self.vm_process is not None and self.vm_process.returncode is None

    @property
    def ip_address(self) -> str | None:
        """Get VM IP address."""
        return self._ip_address
