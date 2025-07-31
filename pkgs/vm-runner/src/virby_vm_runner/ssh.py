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
