"""Virby VM runner."""

import asyncio
import ctypes
import ctypes.util
import logging
import os
import random
import signal
import socket
import sys

from .config import VMConfig
from .constants import (
    DIFF_DISK_FILE_NAME,
    EFI_VARIABLE_STORE_FILE_NAME,
    SERIAL_LOG_FILE_NAME,
    SSHD_KEYS_SHARED_DIR_NAME,
)
from .exceptions import VMRuntimeError, VMStartupError
from .ip_discovery import IPDiscovery
from .ssh import wait_for_ssh_ready

logger = logging.getLogger(__name__)


class VirbyVMRunner:
    """VM runner that integrates with the nix-darwin module."""

    def __init__(self, config: VMConfig):
        self.config = config
        self.working_dir = config.working_directory

        # Validate working directory
        if not self.working_dir.exists():
            raise VMStartupError(f"Working directory does not exist: {self.working_dir}")
        if not self.working_dir.is_dir():
            raise VMStartupError(f"Working directory is not a directory: {self.working_dir}")

        self.vm_process: asyncio.subprocess.Process | None = None
        self.mac_address = self._generate_mac_address()
        self.ip_discovery = IPDiscovery(self.mac_address)
        self._shutdown_requested = False
        self._vm_ip: str | None = None
        self._output_task: asyncio.Task | None = None
        self._is_socket_activated = self._detect_socket_activation()
        self._activation_socket: socket.socket | None = None

    def _generate_mac_address(self) -> str:
        """Generate a random MAC address for VM usage."""
        prefix = "02:94"  # Locally administered, unicast
        suffix = ":".join(f"{random.randint(0, 255):02x}" for _ in range(4))
        return f"{prefix}:{suffix}"

    def _detect_socket_activation(self) -> bool:
        """Detect if we're running under launchd socket activation."""
        is_activated = os.environ.get("VIRBY_SOCKET_ACTIVATION") == "1"
        if is_activated:
            logger.debug("Socket activation detected via VIRBY_SOCKET_ACTIVATION=1")
            self._debug_file_descriptors()
        return is_activated

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

    def _debug_file_descriptors(self) -> None:
        """Debug available file descriptors to diagnose socket issues."""
        logger.debug("=== File Descriptor Debug Info ===")
        for fd in range(10):  # Check first 10 file descriptors
            try:
                import stat

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

    def _get_activation_socket(self) -> socket.socket:
        """Get the socket passed by launchd for activation."""
        if not self._is_socket_activated:
            raise VMStartupError("Not running under socket activation")

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
                    if sock_name[1] == self.config.port:
                        logger.info(f"Using matching socket on FD {fd}")
                        return test_sock
                    else:
                        logger.warning(
                            f"Socket port {sock_name[1]} doesn't match expected {self.config.port}, using anyway"
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
        import stat

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
                            if sock_name[1] == self.config.port:
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
            f"Failed to find activation socket on expected port {self.config.port}. Found {len(found_sockets)} sockets."
        )

    async def _handle_activation_connections(self) -> None:
        """Handle incoming connections on the activation socket."""
        if not self._activation_socket:
            raise VMStartupError("No activation socket available")

        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            """Handle a single client connection."""
            try:
                await self._proxy_connection(reader, writer)
            except Exception as e:
                logger.error(f"Error handling client connection: {e}")

        # Start server using the inherited socket
        server = await asyncio.start_server(handle_client, sock=self._activation_socket)

        logger.info("Started proxy server for socket activation")

        # Keep serving until shutdown
        async with server:
            try:
                await server.serve_forever()
            except asyncio.CancelledError:
                logger.info("Proxy server cancelled")

    async def _ensure_vm_ready(self) -> None:
        """Ensure VM is started and ready for connections."""
        vm_running = self.is_running
        logger.debug(
            f"VM running check: {vm_running}, vm_process: {self.vm_process is not None}, returncode: {self.vm_process.returncode if self.vm_process else 'None'}"
        )

        if not vm_running:
            logger.info("Starting VM for socket activation")
            await self._start_vm_process()

            # Start monitoring task
            asyncio.create_task(self._monitor_vm())

            # Give VM time to boot
            await asyncio.sleep(5)

            # Discover IP and wait for SSH
            ip = await self._discover_vm_ip()
            await self._wait_for_ssh(ip)

            logger.info(f"VM ready at {ip}")
        else:
            logger.debug(f"VM already running at {self._vm_ip}")

    async def _proxy_connection(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        """Proxy a client connection to the VM's SSH port."""
        try:
            # Ensure VM is ready
            await self._ensure_vm_ready()

            # Connect to VM's SSH port
            vm_reader, vm_writer = await asyncio.open_connection(self._vm_ip, 22)

            logger.debug(f"Proxying connection to VM at {self._vm_ip}:22")

            async def pipe_data(
                src_reader: asyncio.StreamReader, dst_writer: asyncio.StreamWriter
            ) -> None:
                """Pipe data from source to destination."""
                try:
                    while True:
                        data = await src_reader.read(4096)
                        if not data:
                            break
                        dst_writer.write(data)
                        await dst_writer.drain()
                except (asyncio.CancelledError, ConnectionResetError):
                    pass
                finally:
                    try:
                        dst_writer.close()
                        await dst_writer.wait_closed()
                    except Exception:
                        pass

            # Start bidirectional piping
            await asyncio.gather(
                pipe_data(client_reader, vm_writer),
                pipe_data(vm_reader, client_writer),
                return_exceptions=True,
            )

        except Exception as e:
            logger.error(f"Connection proxy error: {e}")
        finally:
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass

    def _build_vfkit_command(self) -> list[str]:
        """Build vfkit command from configuration."""
        diff_disk = self.working_dir / DIFF_DISK_FILE_NAME
        efi_store = self.working_dir / EFI_VARIABLE_STORE_FILE_NAME
        sshd_keys = self.working_dir / SSHD_KEYS_SHARED_DIR_NAME

        cmd = [
            "vfkit",
            "--cpus",
            str(self.config.cores),
            "--memory",
            str(self.config.memory),
            "--bootloader",
            f"efi,variable-store={efi_store},create",
            "--device",
            f"virtio-blk,path={diff_disk}",
            "--device",
            f"virtio-fs,sharedDir={sshd_keys},mountTag=sshd-keys",
            "--device",
            f"virtio-net,nat,mac={self.mac_address}",
            # "--restful-uri",
            # "tcp://localhost:31223",
            "--device",
            "virtio-rng",
            "--device",
            "virtio-balloon",
        ]

        if self.config.debug_enabled:
            serial_log = self.working_dir / SERIAL_LOG_FILE_NAME
            cmd.extend(["--device", f"virtio-serial,logFilePath={serial_log}"])

        if self.config.rosetta_enabled:
            cmd.extend(["--device", "rosetta,mountTag=rosetta"])

        return cmd

    async def _start_vm_process(self) -> None:
        """Start the VM process."""
        if self.vm_process is not None:
            raise VMStartupError("VM process is already running")

        cmd = self._build_vfkit_command()
        logger.info(f"Starting VM with command: {' '.join(cmd)}")

        try:
            # Use process groups for better signal handling
            kwargs: dict = {
                "cwd": self.working_dir,
                "preexec_fn": os.setsid if hasattr(os, "setsid") else None,
            }

            if self.config.debug_enabled:
                kwargs.update(
                    {
                        "stdout": asyncio.subprocess.PIPE,
                        "stderr": asyncio.subprocess.PIPE,
                    }
                )
            else:
                kwargs.update(
                    {
                        "stdout": asyncio.subprocess.DEVNULL,
                        "stderr": asyncio.subprocess.DEVNULL,
                    }
                )

            self.vm_process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
            logger.info(f"VM started with PID {self.vm_process.pid}")

            # Start background task to consume output if debug is enabled
            if self.config.debug_enabled and self.vm_process.stdout and self.vm_process.stderr:
                self._output_task = asyncio.create_task(self._consume_vm_output())

        except Exception as e:
            raise VMStartupError(f"Failed to start VM process: {e}")

    async def _discover_vm_ip(self) -> str:
        """Discover the VM's IP address via DHCP."""
        logger.info("Discovering VM IP address...")

        timeout = self.config.ip_discovery_timeout
        start_time = asyncio.get_event_loop().time()
        interval = 1.0  # Start with 1 second
        max_interval = 5.0

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if self._shutdown_requested:
                raise VMRuntimeError("Shutdown requested during IP discovery")

            if self.vm_process and self.vm_process.returncode is not None:
                raise VMRuntimeError("VM process died during IP discovery")

            ip = await self.ip_discovery.discover_ip()
            if ip:
                logger.info(f"Discovered VM IP: {ip}")
                self._vm_ip = ip
                return ip

            await asyncio.sleep(interval)
            interval = min(interval * 1.2, max_interval)  # Exponential backoff

        raise VMRuntimeError(f"Failed to discover VM IP within {timeout} seconds")

    async def _wait_for_ssh(self, ip: str) -> None:
        """Wait for SSH to become ready."""
        if not await wait_for_ssh_ready(ip, self.working_dir, self.config.ssh_ready_timeout):
            raise VMRuntimeError("SSH did not become ready in time")

    async def _consume_vm_output(self) -> None:
        """Consume VM stdout/stderr to prevent buffer overflow."""
        if not self.vm_process or not self.vm_process.stdout or not self.vm_process.stderr:
            return

        async def read_stream(stream, name):
            try:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    logger.debug(f"VM {name}: {line.decode().rstrip()}")
            except Exception as e:
                logger.debug(f"Error reading VM {name}: {e}")

        try:
            await asyncio.gather(
                read_stream(self.vm_process.stdout, "stdout"),
                read_stream(self.vm_process.stderr, "stderr"),
                return_exceptions=True,
            )
        except Exception as e:
            logger.error(f"Error consuming VM output: {e}")

    async def _monitor_vm(self) -> None:
        """Monitor VM process for unexpected death."""
        if self.vm_process:
            await self.vm_process.wait()

            # In on-demand mode, VM shutdown with exit code 0 is expected behavior
            if self._is_socket_activated and self.vm_process.returncode == 0:
                logger.info("VM shut down normally in on-demand mode")
            elif not self._shutdown_requested:
                logger.error(f"VM process died unexpectedly with code {self.vm_process.returncode}")

            # Clean up VM state so it can be restarted
            self._cleanup_vm_state()

    def _cleanup_vm_state(self) -> None:
        """Clean up VM state after shutdown."""
        # Cancel output consumption task
        if self._output_task and not self._output_task.done():
            self._output_task.cancel()

        # Reset VM state
        self.vm_process = None
        self._vm_ip = None
        self._output_task = None

    async def start(self) -> None:
        """Start the VM and wait for it to be ready."""
        logger.info("Starting Virby VM...")

        try:
            # Start VM process
            await self._start_vm_process()

            # Start monitoring task
            asyncio.create_task(self._monitor_vm())

            # Give VM time to boot
            await asyncio.sleep(5)

            # Discover IP
            ip = await self._discover_vm_ip()

            # Wait for SSH
            await self._wait_for_ssh(ip)

            logger.info(f"VM is ready at {ip}")

        except Exception as e:
            logger.error(f"Failed to start VM: {e}")
            await self.stop()
            raise

    # async def stop(self, timeout: int = 30) -> None:
    #     """Stop the VM gracefully."""
    #     logger.info("Stopping VM...")
    #     self._shutdown_requested = True

    #     # Cancel output consumption task
    #     if self._output_task and not self._output_task.done():
    #         self._output_task.cancel()
    #         try:
    #             await self._output_task
    #         except asyncio.CancelledError:
    #             pass

    #     if self.vm_process and self.vm_process.returncode is None:
    #         try:
    #             # Send SIGTERM
    #             self.vm_process.terminate()

    #             # Wait for graceful shutdown
    #             try:
    #                 await asyncio.wait_for(self.vm_process.wait(), timeout=timeout)
    #                 logger.info("VM stopped gracefully")
    #             except asyncio.TimeoutError:
    #                 logger.warning("VM did not stop gracefully, killing...")
    #                 self.vm_process.kill()
    #                 await self.vm_process.wait()
    #                 logger.info("VM killed")
    #         except Exception as e:
    #             logger.error(f"Error stopping VM: {e}")

    #     self.vm_process = None
    #     self._vm_ip = None
    #     self._output_task = None

    async def stop(self, timeout: int = 30) -> None:
        """Stop the VM gracefully."""
        logger.info("Stopping VM...")
        self._shutdown_requested = True

        # Cancel output consumption task
        if self._output_task and not self._output_task.done():
            self._output_task.cancel()
            try:
                await self._output_task
            except asyncio.CancelledError:
                pass

        if self.vm_process and self.vm_process.returncode is None:
            try:
                # Kill the entire process group instead of just the main process
                try:
                    pgid = os.getpgid(self.vm_process.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    logger.info(f"Sent SIGTERM to process group {pgid}")
                except (ProcessLookupError, PermissionError):
                    # Fallback to terminating just the main process
                    self.vm_process.terminate()

                # Wait for graceful shutdown
                try:
                    await asyncio.wait_for(self.vm_process.wait(), timeout=timeout)
                    logger.info("VM stopped gracefully")
                except asyncio.TimeoutError:
                    logger.warning("VM did not stop gracefully, killing...")
                    try:
                        pgid = os.getpgid(self.vm_process.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        self.vm_process.kill()
                    await self.vm_process.wait()
                    logger.info("VM killed")
            except Exception as e:
                logger.error(f"Error stopping VM: {e}")

        self._cleanup_vm_state()

    async def run(self) -> None:
        """Main run loop."""
        shutdown_event = asyncio.Event()

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            shutdown_event.set()

        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            if self._is_socket_activated:
                logger.info("Running in socket activation mode")
                # Get the activation socket
                self._activation_socket = self._get_activation_socket()

                # Start connection handling
                proxy_task = asyncio.create_task(self._handle_activation_connections())

                # Wait for shutdown signal
                await asyncio.wait(
                    [
                        asyncio.create_task(shutdown_event.wait()),
                        proxy_task,
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Cancel proxy task if it's still running
                if not proxy_task.done():
                    proxy_task.cancel()
                    try:
                        await proxy_task
                    except asyncio.CancelledError:
                        pass
            else:
                logger.info("Running in standard mode")
                await self.start()

                # Wait for shutdown signal or VM death
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(shutdown_event.wait()),
                        asyncio.create_task(self._monitor_vm()),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"VM runner error: {e}")
            raise
        finally:
            await self.stop()

    @property
    def is_running(self) -> bool:
        """Check if VM is running."""
        return self.vm_process is not None and self.vm_process.returncode is None

    @property
    def vm_ip(self) -> str | None:
        """Get VM IP address."""
        return self._vm_ip


async def main() -> None:
    """Main entry point."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        # Load configuration
        config = VMConfig()

        # Create and run VM
        runner = VirbyVMRunner(config)
        await runner.run()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
