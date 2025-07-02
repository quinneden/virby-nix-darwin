"""IP discovery via DHCP lease parsing for Virby VM."""

import logging
import re
from pathlib import Path
from typing import List, Optional

import aiofiles

from .constants import DHCPD_LEASES_FILE

logger = logging.getLogger(__name__)

# Regex for trimming leading zeros from MAC addresses
LEADING_ZERO_REGEXP = re.compile(r"0([A-Fa-f0-9](:|$))")


class DHCPEntry:
    """Holds a parsed DHCP entry."""

    def __init__(self):
        self.name: Optional[str] = None
        self.ip_address: Optional[str] = None
        self.hw_address: Optional[str] = None
        self.identifier: Optional[str] = None
        self.lease: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"DHCPEntry(name='{self.name}', ip_address='{self.ip_address}', "
            f"hw_address='{self.hw_address}', identifier='{self.identifier}', lease='{self.lease}')"
        )


class IPDiscovery:
    """Discovers VM IP address via DHCP lease file parsing."""

    def __init__(self, mac_address: str, leases_file: str = DHCPD_LEASES_FILE):
        """
        Initialize IP discovery.

        Args:
            mac_address: MAC address to search for
            leases_file: Path to DHCP leases file
        """
        self.mac_address = self._normalize_mac(mac_address)
        self.leases_file = leases_file

    def _normalize_mac(self, mac: str) -> str:
        """Normalize MAC address by trimming leading zeros."""
        return LEADING_ZERO_REGEXP.sub(r"\1", mac.lower())

    async def discover_ip(self) -> Optional[str]:
        """
        Discover IP address for the configured MAC address.

        Returns:
            IP address if found, None otherwise
        """
        try:
            if not Path(self.leases_file).exists():
                logger.debug(f"DHCP leases file not found: {self.leases_file}")
                return None

            async with aiofiles.open(self.leases_file, "r") as file:
                content = await file.read()
                entries = self._parse_dhcp_leases(content)

            for entry in entries:
                if entry.hw_address == self.mac_address:
                    logger.debug(
                        f"Found IP {entry.ip_address} for MAC {self.mac_address}"
                    )
                    return entry.ip_address

            logger.debug(f"No IP found for MAC {self.mac_address}")
            return None

        except Exception as e:
            logger.error(f"Failed to discover IP for MAC {self.mac_address}: {e}")
            return None

    def _parse_dhcp_leases(self, content: str) -> List[DHCPEntry]:
        """
        Parse DHCP leases file content.

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
