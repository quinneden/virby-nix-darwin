"""Virby VM runner."""

import asyncio
import logging
import os
import signal
import socket
import sys
import time

from .config import VMConfig
from .exceptions import VMStartupError
from .socket_activation import SocketActivation
from .vm_process import VMProcess

logger = logging.getLogger(__name__)


class VirbyVMRunner:
    """VM runner that integrates with the nix-darwin module."""

    def __init__(self, config: VMConfig):
        self.config = config

        # Initialize components
        self.vm_process = VMProcess(config, config.working_directory)
        self.socket_activation = SocketActivation(config.port, config.debug_enabled)

        # Runner state
        self._shutdown_requested = False
        self._is_on_demand = self._detect_on_demand_lifecycle()
        self._activation_socket: socket.socket | None = None
        self._active_connections: int = 0
        self._last_connection_time: int | float = 0

        # Debug file descriptors if in debug mode
        if config.debug_enabled:
            self.socket_activation.debug_file_descriptors()

    def _detect_on_demand_lifecycle(self) -> bool:
        """Detect if VM should use on-demand lifecycle."""
        is_on_demand = os.environ.get("VIRBY_ON_DEMAND") == "1"
        if is_on_demand:
            logger.debug("On-demand lifecycle detected via VIRBY_ON_DEMAND=1")
        else:
            logger.debug("Standard lifecycle detected via VIRBY_ON_DEMAND=0")
        return is_on_demand

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
        vm_running = self.vm_process.is_running

        if not vm_running:
            if self._is_on_demand:
                logger.info("Starting VM for on-demand connection")
            else:
                logger.info("Starting VM for always-on connection")

            # Start VM and get IP address
            ip = await self.vm_process.start()
            logger.info(f"VM ready at {ip}")
        else:
            logger.debug(f"VM running at {self.vm_process.ip_address}")

    async def _proxy_connection(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        """Proxy a client connection to the VM's SSH port."""
        self._active_connections += 1
        self._last_connection_time = time.time()

        try:
            # Ensure VM is ready
            await self._ensure_vm_ready()

            # Connect to VM's SSH port
            vm_reader, vm_writer = await asyncio.open_connection(self.vm_process.ip_address, 22)

            logger.debug(
                f"Proxying connection to VM at {self.vm_process.ip_address}:22 (active connections: {self._active_connections})"
            )

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
            self._active_connections -= 1
            logger.debug(f"Connection closed (active connections: {self._active_connections})")

            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass

            # In on-demand mode, schedule shutdown check after connection ends
            if self._is_on_demand and self._active_connections == 0:
                asyncio.create_task(self._schedule_shutdown_check())

    async def _schedule_shutdown_check(self) -> None:
        """Schedule a shutdown check after TTL expires in on-demand mode."""
        # Get TTL from config
        ttl_seconds = self.config.ttl

        logger.debug(f"Scheduling shutdown check in {ttl_seconds} seconds")
        await asyncio.sleep(ttl_seconds)

        # Check if we should shutdown
        if self._active_connections == 0:
            time_since_last_connection = time.time() - self._last_connection_time
            if time_since_last_connection >= ttl_seconds:
                logger.info("TTL expired with no active connections, shutting down VM")
                await self.stop()
            else:
                logger.debug("TTL expired but recent connection activity, not shutting down")
        else:
            logger.debug(
                f"TTL expired but {self._active_connections} active connections, not shutting down"
            )

    async def start(self) -> None:
        """Start the VM and wait for it to be ready."""
        await self.vm_process.start()

    async def stop(self, timeout: int = 30) -> None:
        """Stop the VM gracefully."""
        self._shutdown_requested = True
        await self.vm_process.stop(timeout)

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
            self._activation_socket = self.socket_activation.get_activation_socket()

            # Start VM immediately if not on-demand
            if not self._is_on_demand:
                logger.info("Starting VM")
                await self.start()

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
        return self.vm_process.is_running

    @property
    def ip_address(self) -> str | None:
        """Get VM IP address."""
        return self.vm_process.ip_address


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
