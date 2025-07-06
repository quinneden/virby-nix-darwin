"""Virby VM runner package."""

from .exceptions import (
    IPDiscoveryError,
    SSHConnectivityError,
    VirbyVMError,
    VMConfigurationError,
    VMRuntimeError,
    VMStartupError,
)

__version__ = "0.1.0"


# Lazy import to avoid dependency issues when importing submodules
def _get_vm_runner():
    from .runner import VirbyVMRunner

    return VirbyVMRunner


# Make VirbyVMRunner available at package level
def __getattr__(name):
    if name == "VirbyVMRunner":
        return _get_vm_runner()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "VirbyVMRunner",
    "VirbyVMError",
    "VMConfigurationError",
    "VMStartupError",
    "VMRuntimeError",
    "IPDiscoveryError",
    "SSHConnectivityError",
]
