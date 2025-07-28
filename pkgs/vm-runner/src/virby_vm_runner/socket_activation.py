"""Launchd socket activation logic for Virby VM."""

import ctypes
import ctypes.util
import logging
import os
import socket
import stat
from contextlib import asynccontextmanager

from .exceptions import VMStartupError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def managed_socket(fd: int, family: int, type: int):
    """Context manager for socket file descriptors."""
    sock = None
    try:
        sock = socket.fromfd(fd, family, type)
        yield sock
    except Exception as e:
        logger.debug(f"Error with socket FD {fd}: {e}")
        raise
    finally:
        if sock:
            try:
                sock.close()
            except Exception as e:
                logger.debug(f"Error closing socket FD {fd}: {e}")


class SocketActivation:
    """Handles launchd socket activation and file descriptor management."""

    def __init__(self, port: int, debug: bool = False):
        """Initialize socket activation manager.

        Args:
            port: Expected port number for socket activation
            debug: Enable debug logging
        """
        self.port = port
        self.debug = debug

    def _call_launch_activate_socket(self, socket_name: str) -> list[int]:
        """Use launch_activate_socket to get socket file descriptors."""
        try:
            # Load the System library which contains launch_activate_socket
            libsystem = ctypes.CDLL(ctypes.util.find_library("System"))

            # Verify function exists
            if not hasattr(libsystem, "launch_activate_socket"):
                logger.debug("launch_activate_socket not available")
                return []

            # Define the function signature
            # int launch_activate_socket(const char *name, int **fds, size_t *cnt);
            launch_activate_socket = libsystem.launch_activate_socket
            launch_activate_socket.argtypes = [
                ctypes.c_char_p,  # const char *name
                ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),  # int **fds
                ctypes.POINTER(ctypes.c_size_t),  # size_t *cnt
            ]
            launch_activate_socket.restype = ctypes.c_int

            # Prepare parameters
            name_bytes = socket_name.encode("utf-8")
            fds_ptr = ctypes.POINTER(ctypes.c_int)()
            count = ctypes.c_size_t()

            # Call the function
            result = launch_activate_socket(name_bytes, ctypes.byref(fds_ptr), ctypes.byref(count))

            if result != 0:
                logger.debug(f"launch_activate_socket returned error: {result}")
                return []

            if count.value == 0:
                logger.debug("launch_activate_socket returned 0 file descriptors")
                return []

            # Extract file descriptors from the returned array
            fds = []
            for i in range(count.value):
                fds.append(fds_ptr[i])

            logger.debug(f"launch_activate_socket returned {count.value} file descriptors: {fds}")
            return fds

        except (OSError, AttributeError) as e:
            logger.debug(f"Failed to load launch_activate_socket: {e}")
            return []

    def get_activation_socket(self) -> socket.socket:
        """Get the socket passed by launchd for activation."""
        logger.debug("Attempting to find activation socket...")

        # Try proper launchd API first
        socket_fds = self._call_launch_activate_socket("Listener")

        if socket_fds:
            return self._process_launchd_sockets(socket_fds)

        # Limited fallback scanning
        return self._fallback_socket_scan()

    def _process_launchd_sockets(self, socket_fds: list[int]) -> socket.socket:
        """Process sockets from launchd with proper cleanup."""
        for fd in socket_fds:
            try:
                test_sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
                sock_name = test_sock.getsockname()
                logger.info(f"Found launchd socket on FD {fd}, bound to {sock_name}")

                if sock_name[1] == self.port:
                    # Duplicate the socket before returning it
                    dup_fd = os.dup(fd)
                    final_sock = socket.fromfd(dup_fd, socket.AF_INET, socket.SOCK_STREAM)
                    test_sock.close()
                    return final_sock
                else:
                    test_sock.close()

            except Exception as e:
                logger.debug(f"Failed to process FD {fd}: {e}")
                continue

        raise VMStartupError("No matching socket found in launchd file descriptors")

    def _fallback_socket_scan(self) -> socket.socket:
        """Limited fallback file descriptor scanning."""
        logger.debug("Falling back to manual file descriptor scanning...")

        # Check environment variables for additional clues
        for env_var in ["LISTEN_FDS", "LISTEN_PID", "LAUNCH_DAEMON_SOCKET_NAME"]:
            value = os.environ.get(env_var)
            if value:
                logger.debug(f"Found env var {env_var}={value}")

        # Scan standard range for launchd sockets (typically 3-10)
        for fd in range(3, 11):
            try:
                fd_stat = os.fstat(fd)
                if not stat.S_ISSOCK(fd_stat.st_mode):
                    continue

                test_sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
                try:
                    sock_name = test_sock.getsockname()
                    logger.debug(f"FD {fd}: Socket bound to {sock_name}")

                    if sock_name[1] == self.port:
                        logger.info(f"Found matching socket on FD {fd}, bound to {sock_name}")
                        # Duplicate socket before returning
                        dup_fd = os.dup(fd)
                        final_sock = socket.fromfd(dup_fd, socket.AF_INET, socket.SOCK_STREAM)
                        test_sock.close()
                        return final_sock
                    else:
                        test_sock.close()

                except Exception as e:
                    logger.debug(f"Failed to get socket info for FD {fd}: {e}")
                    try:
                        test_sock.close()
                    except Exception:
                        pass

            except (OSError, Exception):
                continue

        raise VMStartupError(f"No activation socket found on port {self.port}")
