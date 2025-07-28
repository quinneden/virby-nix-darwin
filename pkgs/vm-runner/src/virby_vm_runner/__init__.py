"""Virby VM runner package."""

from importlib.metadata import version

from .exceptions import (
    IPDiscoveryError,
    SSHConnectivityError,
    VirbyVMError,
    VMConfigurationError,
    VMRuntimeError,
    VMStartupError,
)

__version__ = version("virby_vm_runner")


# Lazy imports to avoid dependency issues when importing submodules
def _get_vm_runner():
    from .runner import VirbyVMRunner

    return VirbyVMRunner


def _get_vm_config():
    from .config import VMConfig

    return VMConfig


def _get_api_client():
    from .api import VfkitAPIClient

    return VfkitAPIClient


def _get_vm_state():
    from .api import VirtualMachineState

    return VirtualMachineState


def __getattr__(name):
    if name == "VirbyVMRunner":
        return _get_vm_runner()
    elif name == "VMConfig":
        return _get_vm_config()
    elif name == "VfkitAPIClient":
        return _get_api_client()
    elif name == "VirtualMachineState":
        return _get_vm_state()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "__version__",
    "VirbyVMRunner",
    "VMConfig",
    "VfkitAPIClient",
    "VirtualMachineState",
    "VirbyVMError",
    "VMConfigurationError",
    "VMStartupError",
    "VMRuntimeError",
    "IPDiscoveryError",
    "SSHConnectivityError",
]
