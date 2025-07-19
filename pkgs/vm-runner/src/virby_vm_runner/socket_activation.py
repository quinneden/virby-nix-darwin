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
        """
        Initialize socket activation manager.

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

        except Exception as e:
            logger.debug(f"Failed to call launch_activate_socket: {e}")
            return []

    def debug_file_descriptors(self) -> None:
        """Debug available file descriptors to diagnose socket issues."""
        if not self.debug:
            return

        logger.debug("=== File Descriptor Debug Info ===")
        for fd in range(10):  # Check first 10 file descriptors
            try:
                fd_stat = os.fstat(fd)
                fd_mode = stat.S_IFMT(fd_stat.st_mode)

                if stat.S_ISSOCK(fd_stat.st_mode):
                    logger.debug(f"FD {fd}: SOCKET")
                    try:
                        # Try to get socket info
                        test_sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
                        sock_name = test_sock.getsockname()
                        try:
                            logger.debug(f"FD {fd}: Socket bound to {sock_name}")
                        except Exception as log_e:
                            logger.debug(f"FD {fd}: Socket (failed to log address: {log_e})")
                        test_sock.close()
                    except Exception as e:
                        logger.debug(f"FD {fd}: Socket but failed to get info: {e}")
                elif stat.S_ISREG(fd_stat.st_mode):
                    logger.debug(f"FD {fd}: Regular file")
                elif stat.S_ISFIFO(fd_stat.st_mode):
                    logger.debug(f"FD {fd}: FIFO/pipe")
                elif stat.S_ISCHR(fd_stat.st_mode):
                    logger.debug(f"FD {fd}: Character device")
                else:
                    logger.debug(f"FD {fd}: Other type (mode: {oct(fd_mode)})")

            except OSError as e:
                if e.errno != 9:  # Not "Bad file descriptor"
                    logger.debug(f"FD {fd}: Error accessing - {e}")
            except Exception as e:
                logger.debug(f"FD {fd}: Unexpected error - {e}")
        logger.debug("=== End FD Debug Info ===")

    def get_activation_socket(self) -> socket.socket:
        """Get the socket passed by launchd for activation."""
        logger.debug("Attempting to find activation socket...")

        # First try the proper launchd API
        socket_fds = self._call_launch_activate_socket("Listener")

        if socket_fds:
            logger.debug(f"Got {len(socket_fds)} file descriptors from launch_activate_socket")
            for fd in socket_fds:
                try:
                    test_sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
                    sock_name = test_sock.getsockname()
                    logger.info(f"Found launchd socket on FD {fd}, bound to {sock_name}")

                    # Check if this matches our expected port
                    if sock_name[1] == self.port:
                        logger.info(f"Using matching socket on FD {fd}")
                        return test_sock
                    else:
                        logger.warning(
                            f"Socket port {sock_name[1]} doesn't match expected {self.port}, using anyway"
                        )
                        return test_sock

                except Exception as e:
                    logger.debug(f"Failed to use FD {fd} from launch_activate_socket: {e}")
                    try:
                        test_sock.close()
                    except Exception:
                        pass

        # Fallback: scan file descriptors manually
        logger.debug("Falling back to manual file descriptor scanning...")

        # Check environment variables for additional clues
        for env_var in ["LISTEN_FDS", "LISTEN_PID", "LAUNCH_DAEMON_SOCKET_NAME"]:
            value = os.environ.get(env_var)
            if value:
                logger.debug(f"Found env var {env_var}={value}")

        # Scan all available file descriptors to find listening sockets
        found_sockets = []

        for fd in range(256):  # Check up to FD 255
            try:
                fd_stat = os.fstat(fd)
                if stat.S_ISSOCK(fd_stat.st_mode):
                    try:
                        # Try to create socket object from FD
                        test_sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
                        try:
                            sock_name = test_sock.getsockname()

                            # Since SO_ACCEPTCONN is not available on macOS, assume all sockets
                            # could be listening sockets and check if they match our port
                            try:
                                logger.debug(f"FD {fd}: Socket bound to {sock_name}")
                            except Exception as log_e:
                                logger.debug(f"FD {fd}: Socket (failed to log address: {log_e})")
                            if sock_name[1] == self.port:
                                logger.info(
                                    f"Found matching socket on FD {fd}, bound to {sock_name}"
                                )
                                return test_sock
                            else:
                                found_sockets.append((fd, sock_name, "available"))
                                test_sock.close()

                        except Exception as e:
                            logger.debug(f"FD {fd} is a socket but failed to get socket name: {e}")
                            try:
                                test_sock.close()
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug(f"FD {fd} is a socket but failed to create socket object: {e}")
            except OSError:
                # FD not available or not accessible
                continue
            except Exception as e:
                logger.debug(f"Unexpected error checking FD {fd}: {e}")
                continue

        if found_sockets:
            logger.debug(f"Found {len(found_sockets)} sockets:")
            for fd, addr, state in found_sockets:
                logger.debug(f"  FD {fd}: {addr} ({state})")

            # If we found exactly one socket, use it (might be the right one)
            if len(found_sockets) == 1:
                fd, addr, state = found_sockets[0]
                logger.warning(f"Using only available socket on FD {fd} bound to {addr} ({state})")
                sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
                return sock

        raise VMStartupError(
            f"Failed to find activation socket on expected port {self.port}. Found {len(found_sockets)} sockets."
        )
