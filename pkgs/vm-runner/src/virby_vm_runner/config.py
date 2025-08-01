"""Configuration management for the Virby VM runner."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from .constants import WORKING_DIRECTORY
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
        on_demand_ttl = self._config.get("ttl", 10800)
        if not isinstance(on_demand_ttl, int) or on_demand_ttl < 0:
            raise VMConfigurationError(
                f"Invalid ttl: {on_demand_ttl}. Expected: non-negative integer"
            )
        self._on_demand_ttl = on_demand_ttl

        # Validate and store shared-dirs
        self._shared_dirs: dict[str, Path] = {}
        shared_dirs = self._config.get("shared-dirs", {})
        if not isinstance(shared_dirs, dict):
            raise VMConfigurationError(f"Invalid shared-dirs: {shared_dirs}. Expected: dictionary")
        for tag, path in shared_dirs.items():
            host_path = Path(path)
            if not host_path.exists():
                raise VMConfigurationError(f"Shared directory does not exist on host: {host_path}")
            self._shared_dirs[tag] = host_path.resolve()

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
    def on_demand_ttl(self) -> int:
        """Get TTL (time to live) in seconds for on-demand VM shutdown."""
        return int(self._on_demand_ttl)

    @property
    def shared_dirs(self) -> Dict[str, Path]:
        """Get shared directories mapping."""
        return self._shared_dirs

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
                f"on_demand_enabled={self._on_demand_enabled}",
                f"on_demand_ttl={self.on_demand_ttl}",
                f"port={self.port}",
                f"rosetta_enabled={self.rosetta_enabled}",
                f"shared_dirs={self.shared_dirs}",
                f"ssh_ready_timeout={self.ssh_ready_timeout}",
                f"vm_pause_timeout={self.vm_pause_timeout}",
                f"vm_resume_timeout={self.vm_resume_timeout}",
                f"vm_stop_timeout={self.vm_stop_timeout}",
                f"working_directory={self.working_directory})",
            ]
        )
