"""IP discovery via DHCP lease parsing for Virby VM."""

import logging
import re
from pathlib import Path

import aiofiles

from .constants import DHCPD_LEASES_FILE_PATH
from .exceptions import IPDiscoveryError

logger = logging.getLogger(__name__)


# Regex for trimming leading zeros from MAC addresses
LEADING_ZERO_REGEXP = re.compile(r"0([A-Fa-f0-9](:|$))")


class DHCPEntry:
    """Holds a parsed DHCP entry."""

    def __init__(self):
        self.name: str | None = None
        self.ip_address: str | None = None
        self.hw_address: str | None = None
        self.identifier: str | None = None
        self.lease: str | None = None

    def __repr__(self) -> str:
        return (
            f"DHCPEntry(name='{self.name}', ip_address='{self.ip_address}', "
            f"hw_address='{self.hw_address}', identifier='{self.identifier}', lease='{self.lease}')"
        )


class IPDiscovery:
    """Discovers VM IP address via DHCP lease file parsing."""

    def __init__(self, mac_address: str, leases_file: str = DHCPD_LEASES_FILE_PATH):
        """Initialize IP discovery.

        Args:
            mac_address: MAC address to search for
            leases_file: Path to DHCP leases file
        """
        self.mac_address = self._normalize_mac(mac_address)
        self.leases_file = leases_file
        # Cache for file reading optimization
        self._cached_entries: list[DHCPEntry] | None = None
        self._cached_mtime: float | None = None

    def _normalize_mac(self, mac: str) -> str:
        """Normalize MAC address by trimming leading zeros."""
        return LEADING_ZERO_REGEXP.sub(r"\1", mac.lower())

    async def discover_ip(self) -> str | None:
        """Discover IP address for the configured MAC address.

        Returns:
            IP address if found, None otherwise
        """
        try:
            leases_path = Path(self.leases_file)
            if not leases_path.exists():
                logger.debug(f"DHCP leases file not found: {self.leases_file}")
                return None

            # Check if file has been modified since last read
            current_mtime = leases_path.stat().st_mtime
            if (
                self._cached_entries is not None
                and self._cached_mtime is not None
                and current_mtime == self._cached_mtime
            ):
                # Use cached entries
                entries = self._cached_entries
            else:
                # Read and cache new entries
                async with aiofiles.open(self.leases_file, "r") as file:
                    content = await file.read()
                    entries = self._parse_dhcp_leases(content)
                    self._cached_entries = entries
                    self._cached_mtime = current_mtime

            for entry in entries:
                if entry.hw_address == self.mac_address:
                    logger.debug(f"Found IP {entry.ip_address} for MAC {self.mac_address}")
                    return entry.ip_address

            logger.debug(f"No IP found for MAC {self.mac_address}")
            return None

        except (OSError, IOError) as e:
            logger.error(f"Failed to read DHCP leases file {self.leases_file}: {e}")
            # Clear cache on error
            self._cached_entries = None
            self._cached_mtime = None
            return None
        except Exception as e:
            logger.error(f"Unexpected error discovering IP for MAC {self.mac_address}: {e}")
            raise IPDiscoveryError(f"IP discovery failed: {e}") from e

    def _parse_dhcp_leases(self, content: str) -> list[DHCPEntry]:
        """Parse DHCP leases file content.

        Args:
            content: Raw file content

        Returns:
            List of DHCP entries
        """
        entries = []
        current_entry = None

        for line in content.splitlines():
            line = line.strip()

            if line == "{":
                current_entry = DHCPEntry()
                continue
            elif line == "}":
                if current_entry:
                    entries.append(current_entry)
                    current_entry = None
                continue

            if current_entry is None:
                continue

            # Parse key=value pairs
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if key == "name":
                current_entry.name = value
            elif key == "ip_address":
                current_entry.ip_address = value
            elif key == "hw_address":
                # Remove "1," prefix from hardware address
                if value.startswith("1,"):
                    current_entry.hw_address = self._normalize_mac(value[2:])
                else:
                    current_entry.hw_address = self._normalize_mac(value)
            elif key == "identifier":
                current_entry.identifier = value
            elif key == "lease":
                current_entry.lease = value

        return entries
