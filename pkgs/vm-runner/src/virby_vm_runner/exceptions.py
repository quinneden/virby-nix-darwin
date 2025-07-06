"""Custom exceptions for the Virby VM runner."""


class VirbyVMError(Exception):
    """Base exception for all Virby VM errors."""

    pass


class VMConfigurationError(VirbyVMError):
    """Raised when VM configuration is invalid."""

    pass


class VMStartupError(VirbyVMError):
    """Raised when VM fails to start."""

    pass


class VMRuntimeError(VirbyVMError):
    """Raised when VM encounters runtime errors."""

    pass


class IPDiscoveryError(VirbyVMError):
    """Raised when IP discovery fails."""

    pass


class SSHConnectivityError(VirbyVMError):
    """Raised when SSH connectivity fails."""

    pass
