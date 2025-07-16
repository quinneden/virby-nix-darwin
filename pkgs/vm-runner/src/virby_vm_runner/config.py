"""Configuration management for the Virby VM runner."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from .constants import (
    WORKING_DIRECTORY,
    VM_USER,
)
from .exceptions import VMConfigurationError

logger = logging.getLogger(__name__)


class VMConfig:
    """VM configuration management."""

    def __init__(self, config_path: str | None = None):
        """
        Initialize VM configuration.

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
            raise VMConfigurationError(f"Invalid cores: {cores}. Expected: positive integer")
        self._cores = cores

        # Validate and store memory
        memory = self._config["memory"]
        if not isinstance(memory, int) or memory < 1024:
            raise VMConfigurationError(f"Invalid memory: {memory}. Expected: at least 1024 MiB")
        self._memory = memory

        # Validate and store debug
        debug = self._config.get("debug", False)
        if not isinstance(debug, bool):
            raise VMConfigurationError(f"Invalid debug: {debug}. Expected: boolean")
        self._debug = debug

        # Validate and store port
        port = self._config.get("port", None)
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise VMConfigurationError(
                f"Invalid port: {port}. Expected: integer between 1 and 65535"
            )
        self._port = port

        # Validate and store rosetta
        rosetta = self._config.get("rosetta", {})
        if not isinstance(rosetta, dict):
            raise VMConfigurationError(f"Invalid rosetta: {rosetta}. Expected: dictionary")
        if "enable" in rosetta and not isinstance(rosetta["enable"], bool):
            raise VMConfigurationError(
                f"Invalid rosetta.enable: {rosetta['enable']}. Expected: boolean"
            )
        self._rosetta_enabled = rosetta.get("enable", False)

        # Store other config values
        self._ip_discovery_timeout = self._config.get("ip_discovery_timeout", 60)
        self._ssh_ready_timeout = self._config.get("ssh_ready_timeout", 60)
        self._ttl = self._config.get("ttl", 10800)

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
        return self._debug

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
    def ttl(self) -> int:
        """Get TTL (time to live) in seconds for on-demand VM shutdown."""
        return int(self._ttl)

    def __repr__(self) -> str:
        """String representation of configuration."""
        return f"VMConfig(cores={self.cores}, memory={self.memory}MiB, debug={self.debug_enabled}, port={self.port}, rosetta_enabled={self.rosetta_enabled}, working_directory={self.working_directory}, ip_discovery_timeout={self.ip_discovery_timeout}, ssh_ready_timeout={self.ssh_ready_timeout}, ttl={self.ttl}, VM_USER={self.VM_USER})"
