"""Configuration management for the Virby VM runner."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from .constants import VM_USER, WORKING_DIRECTORY
from .exceptions import VMConfigurationError

logger = logging.getLogger(__name__)


class VMConfig:
    """VM configuration management."""

    def __init__(self, config_path: str | None = None):
        """Initialize VM configuration.

        Args:
            config_path: Path to JSON configuration file.
        """
        if not config_path:
            raise ValueError("Configuration file path must be provided")

        self.config_path: Path = Path(config_path)
        self._config: Dict[str, Any] = self._load_config()
        self._validate_and_store_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path) as f:
                config: Dict[str, Any] = json.load(f)
            logger.debug(f"Loaded configuration from {self.config_path}")
            return config
        except FileNotFoundError:
            raise VMConfigurationError(f"Configuration file not found: {self.config_path}")
        except json.JSONDecodeError as e:
            raise VMConfigurationError(f"Invalid JSON in configuration file: {e}")
        except Exception as e:
            raise VMConfigurationError(f"Failed to load configuration: {e}")

    def _validate_and_store_config(self) -> None:
        """Validate configuration parameters and store validated values."""
        required_fields = ["cores", "memory"]

        for field in required_fields:
            if field not in self._config:
                raise VMConfigurationError(f"Required configuration field missing: {field}")

        # Validate and store cores
        cores = self._config["cores"]
        if not isinstance(cores, int) or cores < 1:
            raise VMConfigurationError(
                f"Invalid cores setting: {cores}. Expected: positive integer"
            )
        self._cores = cores

        # Validate and store memory
        memory = self._config["memory"]
        if not isinstance(memory, int) or memory < 1024:
            raise VMConfigurationError(
                f"Invalid memory setting: {memory}. Expected: at least 1024 MiB"
            )
        self._memory = memory

        # Validate and store debug
        debug = self._config.get("debug", False)
        if not isinstance(debug, bool):
            raise VMConfigurationError(f"Invalid debug setting: {debug}. Expected: boolean")
        self._debug_enabled = debug

        # Validate and store port
        port = self._config.get("port", None)
        if not isinstance(port, int) or port < 1024 or port > 65535:
            raise VMConfigurationError(
                f"Invalid port: {port}. Expected: integer between 1024 and 65535"
            )
        self._port = port

        # Validate and store rosetta
        rosetta = self._config.get("rosetta", False)
        if not isinstance(rosetta, bool):
            raise VMConfigurationError(f"Invalid rosetta setting: {rosetta}. Expected: boolean")
        self._rosetta_enabled = rosetta

        # Validate and store on-demand
        on_demand = self._config.get("on-demand", False)
        if not isinstance(on_demand, bool):
            raise VMConfigurationError(f"Invalid on-demand setting: {on_demand}. Expected: boolean")
        self._on_demand_enabled = on_demand

        # Validate and store TTL
        ttl = self._config.get("ttl", 10800)
        if not isinstance(ttl, int) or ttl < 0:
            raise VMConfigurationError(f"Invalid ttl: {ttl}. Expected: non-negative integer")
        self._ttl = ttl

        # Store other config values
        self._ip_discovery_timeout = self._config.get("ip_discovery_timeout", 60)
        self._ssh_ready_timeout = self._config.get("ssh_ready_timeout", 30)

        # VM operation timeouts
        self._vm_pause_timeout = self._config.get("vm_pause_timeout", 30)
        self._vm_resume_timeout = self._config.get("vm_resume_timeout", 30)
        self._vm_stop_timeout = self._config.get("vm_stop_timeout", 30)

        for timeout_name, timeout_val in [
            ("vm_pause_timeout", self._vm_pause_timeout),
            ("vm_resume_timeout", self._vm_resume_timeout),
            ("vm_stop_timeout", self._vm_stop_timeout),
        ]:
            if not isinstance(timeout_val, int) or timeout_val < 1:
                raise VMConfigurationError(f"Invalid {timeout_name}: {timeout_val}")

    @property
    def cores(self) -> int:
        """Get number of CPU cores."""
        return self._cores

    @property
    def memory(self) -> int:
        """Get memory size in MiB."""
        return self._memory

    @property
    def debug_enabled(self) -> bool:
        """Check if debug mode is enabled."""
        return self._debug_enabled

    @property
    def port(self) -> int:
        """Get SSH port."""
        return self._port

    @property
    def rosetta_enabled(self) -> bool:
        """Check if Rosetta is enabled."""
        return bool(self._rosetta_enabled)

    @property
    def working_directory(self) -> Path:
        """Get working directory."""
        value = os.getenv("VIRBY_WORKING_DIRECTORY", WORKING_DIRECTORY)
        return Path(value)

    @property
    def VM_USER(self) -> str:
        """Get VM SSH user."""
        return str(VM_USER)

    @property
    def ip_discovery_timeout(self) -> int:
        """Get IP discovery timeout in seconds."""
        return int(self._ip_discovery_timeout)

    @property
    def ssh_ready_timeout(self) -> int:
        """Get SSH ready timeout in seconds."""
        return int(self._ssh_ready_timeout)

    @property
    def on_demand_enabled(self) -> bool:
        """Check if on-demand activation is enabled."""
        return bool(self._on_demand_enabled)

    @property
    def ttl(self) -> int:
        """Get TTL (time to live) in seconds for on-demand VM shutdown."""
        return int(self._ttl)

    @property
    def vm_pause_timeout(self) -> int:
        """Get VM pause timeout in seconds."""
        return self._vm_pause_timeout

    @property
    def vm_resume_timeout(self) -> int:
        """Get VM resume timeout in seconds."""
        return self._vm_resume_timeout

    @property
    def vm_stop_timeout(self) -> int:
        """Get VM stop timeout in seconds."""
        return self._vm_stop_timeout

    def __repr__(self) -> str:
        """String representation of configuration."""
        return ", ".join(
            [
                f"VMConfig(cores={self.cores}",
                f"debug={self.debug_enabled}",
                f"ip_discovery_timeout={self.ip_discovery_timeout}",
                f"memory={self.memory}MiB",
                f"port={self.port}",
                f"rosetta_enabled={self.rosetta_enabled}",
                f"ssh_ready_timeout={self.ssh_ready_timeout}",
                f"on_demand_enabled={self._on_demand_enabled}",
                f"ttl={self.ttl}",
                f"VM_USER={self.VM_USER}",
                f"working_directory={self.working_directory})",
            ]
        )
