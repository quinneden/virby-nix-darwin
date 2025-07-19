"""VM process lifecycle management for Virby VM."""

import asyncio
import logging
import os
import random
import signal
from pathlib import Path

from .config import VMConfig
from .constants import (
    DIFF_DISK_FILE_NAME,
    EFI_VARIABLE_STORE_FILE_NAME,
    SERIAL_LOG_FILE_NAME,
    SSHD_KEYS_SHARED_DIR_NAME,
)
from .exceptions import VMRuntimeError, VMStartupError
from .ip_discovery import IPDiscovery
from .ssh import wait_for_ssh_ready

logger = logging.getLogger(__name__)


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
            "tcp://localhost:31223",
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

    async def _start_vm_process(self) -> None:
        """Start the VM process."""
        if self.vm_process is not None:
            raise VMStartupError("VM process is already running")

        cmd = self.build_vfkit_command()
        logger.info(f"Starting VM with command: {' '.join(cmd)}")

        try:
            kwargs: dict = {
                "cwd": self.working_dir,
                "preexec_fn": os.setsid if hasattr(os, "setsid") else None,
            }

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

            # Start background task to consume output if debug is enabled
            if self.config.debug_enabled and self.vm_process.stdout and self.vm_process.stderr:
                self._output_task = asyncio.create_task(self._consume_vm_output())

        except Exception as e:
            raise VMStartupError(f"Failed to start VM process: {e}")

    async def _discover_ip_address(self) -> str:
        """Discover the VM's IP address via DHCP."""
        logger.info("Discovering VM IP address...")

        timeout = self.config.ip_discovery_timeout
        start_time = asyncio.get_event_loop().time()
        interval = 1.0
        max_interval = 5.0

        while (asyncio.get_event_loop().time() - start_time) < timeout:
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
            interval = min(interval * 1.2, max_interval)

        raise VMRuntimeError(f"Failed to discover VM IP within {timeout} seconds")

    async def _wait_for_ssh(self, ip: str) -> None:
        """Wait for SSH to become ready."""
        if not await wait_for_ssh_ready(ip, self.working_dir, self.config.ssh_ready_timeout):
            raise VMRuntimeError("SSH did not become ready in time")

    async def _consume_vm_output(self) -> None:
        """Consume VM stdout/stderr to prevent buffer overflow."""
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

    def _cleanup_vm_state(self) -> None:
        """Clean up VM state after shutdown."""
        # Cancel output consumption task
        if self._output_task and not self._output_task.done():
            self._output_task.cancel()

        # Reset VM state
        self.vm_process = None
        self._ip_address = None
        self._output_task = None

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

            # Give VM time to boot
            await asyncio.sleep(5)

            # Discover IP
            ip = await self._discover_ip_address()

            # Wait for SSH
            await self._wait_for_ssh(ip)

            logger.info(f"VM is ready at {ip}")
            return ip

        except Exception as e:
            logger.error(f"Failed to start VM: {e}")
            await self.stop()
            raise

    async def stop(self, timeout: int = 30) -> None:
        """Stop the VM gracefully."""
        logger.info("Stopping VM...")
        self._shutdown_requested = True

        # Cancel output consumption task
        if self._output_task and not self._output_task.done():
            self._output_task.cancel()
            try:
                await self._output_task
            except asyncio.CancelledError:
                pass

        if self.vm_process and self.vm_process.returncode is None:
            try:
                # Kill process group
                try:
                    pgid = os.getpgid(self.vm_process.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    logger.info(f"Sent SIGTERM to process group {pgid}")
                except (ProcessLookupError, PermissionError):
                    # Fallback to terminating just the main process
                    self.vm_process.terminate()

                # Wait for graceful shutdown
                try:
                    await asyncio.wait_for(self.vm_process.wait(), timeout=timeout)
                    logger.info("VM stopped gracefully")
                except asyncio.TimeoutError:
                    logger.warning("VM did not stop gracefully, killing...")
                    try:
                        pgid = os.getpgid(self.vm_process.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        self.vm_process.kill()
                    await self.vm_process.wait()
                    logger.info("VM killed")
            except Exception as e:
                logger.error(f"Error stopping VM: {e}")

        self._cleanup_vm_state()

    @property
    def is_running(self) -> bool:
        """Check if VM is running."""
        return self.vm_process is not None and self.vm_process.returncode is None

    @property
    def ip_address(self) -> str | None:
        """Get VM IP address."""
        return self._ip_address
