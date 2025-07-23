"""SSH connectivity testing for Virby VM."""

import asyncio
import logging
from pathlib import Path

from .constants import SSH_KNOWN_HOSTS_FILE_NAME, SSH_USER_PRIVATE_KEY_FILE_NAME, VM_USER

logger = logging.getLogger(__name__)


class SSHConnectivityTester:
    """Cached SSH connectivity tester."""

    def __init__(self, working_dir: Path, username: str = VM_USER):
        self.working_dir = working_dir
        self.username = username
        self.ssh_key_path = working_dir / SSH_USER_PRIVATE_KEY_FILE_NAME
        self.known_hosts_path = working_dir / SSH_KNOWN_HOSTS_FILE_NAME

        # Pre-build SSH command template
        self._ssh_base_command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={self.known_hosts_path}",
            "-p",
            "22",
            "-i",
            str(self.ssh_key_path),
        ]

    async def test_connectivity(self, ip_address: str, timeout: int = 10) -> bool:
        """Test SSH connectivity with cached command."""
        if not self.ssh_key_path.exists():
            logger.debug(f"SSH key not found at {self.ssh_key_path}")
            return False

        # Build final command with IP
        ssh_command = self._ssh_base_command + [
            "-o",
            f"ConnectTimeout={timeout}",
            f"{self.username}@{ip_address}",
            "true",
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *ssh_command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
                success = process.returncode == 0
                if success:
                    logger.debug(f"SSH connection to {ip_address} successful")
                return success
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return False

        except Exception as e:
            logger.debug(f"SSH connectivity test failed: {e}")
            return False


async def test_ssh_connectivity(
    ip_address: str,
    working_dir: Path,
    timeout: int = 30,
    username: str = VM_USER,
) -> bool:
    """
    Test SSH connectivity to a VM.

    Args:
        ip_address: IP address of the VM
        working_dir: Working directory containing SSH keys
        timeout: Connection timeout in seconds
        username: SSH username

    Returns:
        True if SSH connection successful, False otherwise
    """
    ssh_key_path = working_dir / SSH_USER_PRIVATE_KEY_FILE_NAME
    known_hosts_path = working_dir / SSH_KNOWN_HOSTS_FILE_NAME

    if not ssh_key_path.exists():
        logger.debug(f"SSH key not found at {ssh_key_path}")
        return False

    # Build SSH command for testing
    ssh_command = [
        "ssh",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        f"UserKnownHostsFile={known_hosts_path}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "PasswordAuthentication=no",
        "-p",
        "22",
        "-i",
        str(ssh_key_path),
        f"{username}@{ip_address}",
        "true",
    ]

    try:
        logger.debug(f"Testing SSH connectivity to {ip_address}")

        process = await asyncio.create_subprocess_exec(
            *ssh_command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
            success = process.returncode == 0

            if success:
                logger.debug(f"SSH connection to {ip_address} successful")
            else:
                logger.debug(
                    f"SSH connection to {ip_address} failed with exit code {process.returncode}"
                )

            return success

        except asyncio.TimeoutError:
            logger.debug(f" SSH connection to {ip_address} timed out after {timeout} seconds")
            process.kill()
            await process.wait()
            return False

    except Exception as e:
        logger.debug(f"SSH connectivity test failed: {e}")
        return False


async def wait_for_ssh_ready(
    ip_address: str,
    working_dir: Path,
    timeout: int = 30,
    check_interval: float = 0.25,  # Reduced from 1 second to 250ms
) -> bool:
    """
    Wait for SSH to become ready on the VM.

    Args:
        ip_address: IP address of the VM
        working_dir: Working directory containing SSH keys
        timeout: Total timeout in seconds
        check_interval: Initial interval between checks in seconds

    Returns:
        True if SSH becomes ready within timeout, False otherwise
    """
    logger.info(f"Waiting for SSH connectivity to {ip_address}")

    tester = SSHConnectivityTester(working_dir)
    start_time = asyncio.get_event_loop().time()

    while (asyncio.get_event_loop().time() - start_time) < timeout:
        if await tester.test_connectivity(ip_address, timeout=5):
            logger.info("SSH is ready")
            return True

        await asyncio.sleep(check_interval)
        # Gradual backoff: 250ms -> 500ms -> 1s
        check_interval = min(check_interval * 2, 1.0)

    logger.warning(f"SSH not ready within {timeout} seconds")
    return False
