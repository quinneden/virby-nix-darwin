"""Configuration management for the Virby VM runner."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from .constants import (
    DEFAULT_IP_DISCOVERY_TIMEOUT,
    DEFAULT_SHUTDOWN_TIMEOUT,
    DEFAULT_SSH_PORT,
    DEFAULT_SSH_READY_TIMEOUT,
    DEFAULT_STARTUP_TIMEOUT,
    DEFAULT_WORKING_DIRECTORY,
    VM_SSH_USER,
)

logger = logging.getLogger(__name__)


class VMConfig:
    """VM configuration management."""

    def __init__(self, config_path: str | None = None):
        """
        Initialize VM configuration.

        Args:
            config_path: Path to JSON configuration file. If None, uses VIRBY_VM_CONFIG_FILE env var.
        """
        if config_path is None:
            config_path = os.getenv("VIRBY_VM_CONFIG_FILE")

        if not config_path:
            raise ValueError(
                "Configuration file path must be provided via argument or VIRBY_VM_CONFIG_FILE environment variable"
            )

        self.config_path = Path(config_path)
        self._config = self._load_config()
        self._validate_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path) as f:
                config = json.load(f)
            logger.debug(f"Loaded configuration from {self.config_path}")
            return config
        except FileNotFoundError:
            raise RuntimeError(f"Configuration file not found: {self.config_path}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in configuration file: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to load configuration: {e}")

    def _validate_config(self) -> None:
        """Validate configuration parameters."""
        required_fields = ["cores", "memory"]

        for field in required_fields:
            if field not in self._config:
                raise ValueError(f"Required configuration field missing: {field}")

        # Validate types and ranges
        if not isinstance(self._config["cores"], int) or self._config["cores"] < 1:
            raise ValueError("cores must be a positive integer")

        if not isinstance(self._config["memory"], int) or self._config["memory"] < 1024:
            raise ValueError("memory must be at least 1024 MiB")

        # Validate optional fields
        if "debug" in self._config and not isinstance(self._config["debug"], bool):
            raise ValueError("debug must be a boolean")

        if "port" in self._config:
            port = self._config["port"]
            if not isinstance(port, int) or port < 1 or port > 65535:
                raise ValueError("port must be an integer between 1 and 65535")

        if "rosetta" in self._config:
            rosetta = self._config["rosetta"]
            if not isinstance(rosetta, dict) or "enable" not in rosetta:
                raise ValueError("rosetta must be a dictionary with 'enable' key")

    @property
    def cores(self) -> int:
        """Get number of CPU cores."""
        return self._config["cores"]

    @property
    def memory(self) -> int:
        """Get memory size in MiB."""
        return self._config["memory"]

    @property
    def debug_enabled(self) -> bool:
        """Check if debug mode is enabled."""
        return self._config.get("debug", False)

    @property
    def port(self) -> int:
        """Get SSH port."""
        return self._config.get("port", DEFAULT_SSH_PORT)

    @property
    def rosetta_enabled(self) -> bool:
        """Check if Rosetta is enabled."""
        return self._config.get("rosetta", {}).get("enable", False)

    @property
    def working_directory(self) -> Path:
        """Get working directory."""
        return Path(os.getenv("WORKING_DIRECTORY", DEFAULT_WORKING_DIRECTORY))

    @property
    def vm_ssh_user(self) -> str:
        """Get VM SSH user."""
        return VM_SSH_USER

    @property
    def ip_discovery_timeout(self) -> int:
        """Get IP discovery timeout in seconds."""
        return self._config.get("ip_discovery_timeout", DEFAULT_IP_DISCOVERY_TIMEOUT)

    @property
    def ssh_ready_timeout(self) -> int:
        """Get SSH ready timeout in seconds."""
        return self._config.get("ssh_ready_timeout", DEFAULT_SSH_READY_TIMEOUT)

    @property
    def shutdown_timeout(self) -> int:
        """Get shutdown timeout in seconds."""
        return self._config.get("shutdown_timeout", DEFAULT_SHUTDOWN_TIMEOUT)

    @property
    def startup_timeout(self) -> int:
        """Get startup timeout in seconds."""
        return self._config.get("startup_timeout", DEFAULT_STARTUP_TIMEOUT)

    def to_dict(self) -> Dict[str, Any]:
        """Get configuration as dictionary."""
        return self._config.copy()

    def __repr__(self) -> str:
        """String representation of configuration."""
        return f"VMConfig(cores={self.cores}, memory={self.memory}MiB, debug={self.debug_enabled}, port={self.port})"
