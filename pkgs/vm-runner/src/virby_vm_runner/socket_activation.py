"""Launchd socket activation logic for Virby VM."""

import ctypes
import ctypes.util
import logging
import os
import socket
import stat

from .exceptions import VMStartupError

logger = logging.getLogger(__name__)


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
            libsystem_path = ctypes.util.find_library("System")
            if not libsystem_path:
                logger.debug("System library not found")
                return []

            libsystem = ctypes.CDLL(libsystem_path)

            if not hasattr(libsystem, "launch_activate_socket"):
                logger.debug("launch_activate_socket not available")
                return []

            launch_activate_socket = libsystem.launch_activate_socket
            launch_activate_socket.argtypes = [
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
                ctypes.POINTER(ctypes.c_size_t),
            ]
            launch_activate_socket.restype = ctypes.c_int

            name_bytes = socket_name.encode("utf-8")
            fds_ptr = ctypes.POINTER(ctypes.c_int)()
            count = ctypes.c_size_t()

            result = launch_activate_socket(name_bytes, ctypes.byref(fds_ptr), ctypes.byref(count))

            if result != 0:
                logger.debug(f"launch_activate_socket returned error: {result}")
                return []

            if count.value == 0:
                logger.debug("launch_activate_socket returned 0 file descriptors")
                return []

            fds = [fds_ptr[i] for i in range(count.value)]
            logger.debug(f"launch_activate_socket returned {count.value} file descriptors: {fds}")
            return fds

        except (OSError, AttributeError) as e:
            logger.debug(f"Failed to load launch_activate_socket: {e}")
            return []

    def get_activation_socket(self) -> socket.socket:
        """Get the socket passed by launchd for activation."""
        logger.debug("Attempting to find activation socket...")

        socket_fds = self._call_launch_activate_socket("Listener")

        if socket_fds:
            return self._process_launchd_sockets(socket_fds)

        return self._fallback_socket_scan()

    def _socket_matches_port(self, sock: socket.socket, sock_name: object) -> bool:
        """Check whether a socket is an INET listener on the configured port."""
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return False

        if not isinstance(sock_name, tuple) or len(sock_name) < 2:
            return False

        return sock_name[1] == self.port

    def _inspect_socket_fd(self, fd: int) -> tuple[socket.socket, object]:
        """Duplicate and inspect an inherited socket descriptor."""
        sock = socket.socket(fileno=os.dup(fd))
        return sock, sock.getsockname()

    def _process_launchd_sockets(self, socket_fds: list[int]) -> socket.socket:
        """Process sockets returned directly from launchd."""
        for fd in socket_fds:
            test_sock = None
            try:
                test_sock, sock_name = self._inspect_socket_fd(fd)
                logger.info(
                    f"Found launchd socket on FD {fd}, family={test_sock.family}, bound to {sock_name}"
                )

                if self._socket_matches_port(test_sock, sock_name):
                    logger.info(f"Using launchd socket on FD {fd} for port {self.port}")
                    final_sock = test_sock
                    test_sock = None
                    return final_sock

            except Exception as e:
                logger.debug(f"Failed to process FD {fd}: {e}")
            finally:
                if test_sock is not None:
                    try:
                        test_sock.close()
                    except Exception:
                        pass

        raise VMStartupError("No matching socket found in launchd file descriptors")

    def _fallback_socket_scan(self) -> socket.socket:
        """Limited fallback file descriptor scanning."""
        logger.debug("Falling back to manual file descriptor scanning...")

        for env_var in ["LISTEN_FDS", "LISTEN_PID", "LAUNCH_DAEMON_SOCKET_NAME"]:
            value = os.environ.get(env_var)
            if value:
                logger.debug(f"Found env var {env_var}={value}")

        for fd in range(3, 11):
            test_sock = None
            try:
                fd_stat = os.fstat(fd)
                if not stat.S_ISSOCK(fd_stat.st_mode):
                    continue

                test_sock, sock_name = self._inspect_socket_fd(fd)
                logger.debug(
                    f"FD {fd}: family={test_sock.family} type={test_sock.type} bound to {sock_name}"
                )

                if self._socket_matches_port(test_sock, sock_name):
                    logger.info(f"Found matching socket on FD {fd}, bound to {sock_name}")
                    final_sock = test_sock
                    test_sock = None
                    return final_sock

            except Exception as e:
                logger.debug(f"Failed to get socket info for FD {fd}: {e}")
            finally:
                if test_sock is not None:
                    try:
                        test_sock.close()
                    except Exception:
                        pass

        raise VMStartupError(f"No activation socket found on port {self.port}")
