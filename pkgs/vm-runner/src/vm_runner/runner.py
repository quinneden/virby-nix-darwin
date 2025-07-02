"""Virby VM runner."""

import asyncio
import logging
import random
import signal
import sys
from typing import Optional

from .config import VMConfig
from .constants import (
    DIFF_DISK_FILE_NAME,
    EFI_VARIABLE_STORE_FILE_NAME,
    SERIAL_LOG_FILE_NAME,
    SSHD_KEYS_SHARED_DIR_NAME,
)
from .ip_discovery import IPDiscovery
from .ssh import wait_for_ssh_ready

logger = logging.getLogger(__name__)


class VirbyVMRunner:
    """VM runner that integrates with the nix-darwin module."""

    def __init__(self, config: VMConfig):
        self.config = config
        self.working_dir = config.working_directory
        self.vm_process: Optional[asyncio.subprocess.Process] = None
        self.mac_address = self._generate_mac_address()
        self.ip_discovery = IPDiscovery(self.mac_address)
        self._shutdown_requested = False
        self._vm_ip: str | None = None

    def _generate_mac_address(self) -> str:
        """Generate a random MAC address for VM usage."""
        prefix = "02:94"  # Locally administered, unicast
        suffix = ":".join(f"{random.randint(0, 255):02x}" for _ in range(4))
        return f"{prefix}:{suffix}"

    def _build_vfkit_command(self) -> list[str]:
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
            raise RuntimeError("VM process is already running")

        cmd = self._build_vfkit_command()
        logger.info(f"Starting VM with command: {' '.join(cmd)}")

        try:
            self.vm_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE
                if self.config.debug_enabled
                else asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
                if self.config.debug_enabled
                else asyncio.subprocess.DEVNULL,
                cwd=self.working_dir,
            )
            logger.info(f"VM started with PID {self.vm_process.pid}")
        except Exception as e:
            raise RuntimeError(f"Failed to start VM process: {e}")

    async def _discover_vm_ip(self) -> str:
        """Discover the VM's IP address via DHCP."""
        logger.info("Discovering VM IP address...")

        timeout = self.config.ip_discovery_timeout
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if self._shutdown_requested:
                raise RuntimeError("Shutdown requested during IP discovery")

            if self.vm_process and self.vm_process.returncode is not None:
                raise RuntimeError("VM process died during IP discovery")

            ip = await self.ip_discovery.discover_ip()
            if ip:
                logger.info(f"Discovered VM IP: {ip}")
                self._vm_ip = ip
                return ip

            await asyncio.sleep(2)

        raise RuntimeError(f"Failed to discover VM IP within {timeout} seconds")

    async def _wait_for_ssh(self, ip: str) -> None:
        """Wait for SSH to become ready."""
        if not await wait_for_ssh_ready(
            ip, self.working_dir, self.config.ssh_ready_timeout
        ):
            raise RuntimeError("SSH did not become ready in time")

    async def _monitor_vm(self) -> None:
        """Monitor the VM process."""
        if not self.vm_process:
            return

        try:
            returncode = await self.vm_process.wait()
            if not self._shutdown_requested:
                logger.error(f"VM process exited unexpectedly with code {returncode}")
                # Read stderr if available and in debug mode
                if self.config.debug_enabled and self.vm_process.stderr:
                    try:
                        stderr_data = await asyncio.wait_for(
                            self.vm_process.stderr.read(), timeout=1.0
                        )
                        if stderr_data:
                            logger.error(f"VM stderr: {stderr_data.decode()}")
                    except asyncio.TimeoutError:
                        pass
        except Exception as e:
            logger.error(f"Error monitoring VM: {e}")

    async def start(self) -> None:
        """Start the VM and wait for it to be ready."""
        logger.info("Starting Virby VM...")

        try:
            # Start VM process
            await self._start_vm_process()

            # Start monitoring task
            asyncio.create_task(self._monitor_vm())

            # Give VM time to boot
            await asyncio.sleep(5)

            # Discover IP
            ip = await self._discover_vm_ip()

            # Wait for SSH
            await self._wait_for_ssh(ip)

            logger.info(f"VM is ready at {ip}")

        except Exception as e:
            logger.error(f"Failed to start VM: {e}")
            await self.stop()
            raise

    async def stop(self, timeout: int = 30) -> None:
        """Stop the VM gracefully."""
        logger.info("Stopping VM...")
        self._shutdown_requested = True

        if self.vm_process and self.vm_process.returncode is None:
            try:
                # Send SIGTERM
                self.vm_process.terminate()

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

        self.vm_process = None
        self._vm_ip = None

    async def run(self) -> None:
        """Main run loop."""

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            self._shutdown_requested = True

        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            await self.start()

            # Wait for shutdown signal
            while not self._shutdown_requested:
                await asyncio.sleep(1)

                # Check if VM is still running
                if self.vm_process and self.vm_process.returncode is not None:
                    logger.error("VM process died, exiting")
                    break

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"VM runner error: {e}")
            raise
        finally:
            await self.stop()

    @property
    def is_running(self) -> bool:
        """Check if VM is running."""
        return self.vm_process is not None and self.vm_process.returncode is None

    @property
    def vm_ip(self) -> Optional[str]:
        """Get VM IP address."""
        return self._vm_ip


async def main() -> None:
    """Main entry point."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        # Load configuration
        config = VMConfig()

        # Create and run VM
        runner = VirbyVMRunner(config)
        await runner.run()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
