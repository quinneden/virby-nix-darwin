"""SSH connectivity testing for Virby VM."""

import asyncio
import logging
from pathlib import Path

from .constants import SSH_KNOWN_HOSTS_FILE_NAME, SSH_USER_PRIVATE_KEY_FILE_NAME, VM_USER

logger = logging.getLogger(__name__)


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
    check_interval: int = 2,
) -> bool:
    """
    Wait for SSH to become ready on the VM.

    Args:
        ip_address: IP address of the VM
        working_dir: Working directory containing SSH keys
        timeout: Total timeout in seconds
        check_interval: Interval between checks in seconds

    Returns:
        True if SSH becomes ready within timeout, False otherwise
    """
    logger.info(f"Waiting for SSH connectivity to {ip_address}")

    start_time = asyncio.get_event_loop().time()

    while (asyncio.get_event_loop().time() - start_time) < timeout:
        if await test_ssh_connectivity(ip_address, working_dir, timeout=30):
            logger.info("SSH is ready")
            return True

        await asyncio.sleep(check_interval)

    logger.warning(f"SSH not ready within {timeout} seconds")
    return False
