"""Virby VM runner."""

import asyncio
import logging
import socket
import sys
import time

from .config import VMConfig
from .exceptions import VMStartupError
from .signal_manager import SignalManager
from .socket_activation import SocketActivation
from .vm_process import VMProcess

logger = logging.getLogger(__name__)


class VirbyVMRunner:
    """VM runner that integrates with the Virby Nix-darwin module."""

    def __init__(self, config: VMConfig, signal_manager: SignalManager):
        self.config = config
        self.signal_manager = signal_manager

        # Initialize components
        self.vm_process = VMProcess(config, config.working_directory)
        self.socket_activation = SocketActivation(config.port, config.debug_enabled)

        # Runner state
        self._shutdown_requested = False
        self._activation_socket: socket.socket | None = None
        self._active_connections: int = 0
        self._last_connection_time: int | float = 0
        self._shutdown_timer: asyncio.Task | None = None

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
        # Check for shutdown signal
        if self.signal_manager.is_shutdown_requested():
            raise VMStartupError("Shutdown requested, not starting VM")

        # Also check VM process shutdown flag if it exists
        if hasattr(self, "vm_process") and self.vm_process._shutdown_requested:
            raise VMStartupError("VM shutdown already requested")

        vm_running = self.vm_process.is_running
        if self.config.on_demand_enabled:
            can_resume = self.vm_process.can_resume()
            if can_resume or not vm_running:
                ip = await self.vm_process.safe_resume_or_start()
                logger.info(f"VM ready (ip: {ip})")
        else:
            if not vm_running:
                ip = await self.vm_process.start()
                logger.info(f"VM ready (ip: {ip})")

    async def _proxy_connection(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        """Proxy a client connection to the VM's SSH port."""
        self._active_connections += 1
        self._last_connection_time = time.time()

        # Reset shutdown timer if it exists
        if self._shutdown_timer and not self._shutdown_timer.done():
            self._shutdown_timer.cancel()
            self._shutdown_timer = None

        try:
            # Check for shutdown signal
            if self.signal_manager.is_shutdown_requested():
                logger.info("Shutdown requested, rejecting connection")
                return

            # Check VM process shutdown state
            if hasattr(self, "vm_process") and self.vm_process._shutdown_requested:
                logger.info("VM shutdown requested, rejecting connection")
                return

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

            # In on-demand mode, start shutdown timer after connection ends
            if self.config.on_demand_enabled and self._active_connections == 0:
                self._shutdown_timer = asyncio.create_task(self._schedule_shutdown_check())

    async def _schedule_shutdown_check(self) -> None:
        """Schedule a shutdown check after TTL expires in on-demand mode."""
        # Get TTL from config
        try:
            ttl_seconds = self.config.ttl

            logger.debug(f"Scheduling shutdown check in {ttl_seconds} seconds")
            await asyncio.sleep(ttl_seconds)

            # Check if we should shutdown
            if self._active_connections == 0:
                logger.info("TTL expired with no active connections, shutting down VM")
                # In on-demand mode, try pause before stop
                if self.config.on_demand_enabled:
                    was_paused = await self.vm_process.safe_pause_or_stop()
                    if was_paused:
                        logger.info("VM paused")
                    else:
                        logger.info("VM stopped")
                else:
                    await self.stop()
            else:
                logger.debug(
                    f"TTL expired but there are {self._active_connections} active connections, not shutting down"
                )
        except asyncio.CancelledError:
            logger.debug("Shutdown timer cancelled due to new connection")
            raise

    async def start(self) -> None:
        """Start the VM and wait for it to be ready."""
        await self.vm_process.start()

    async def stop(self, timeout: int = 30) -> None:
        """Stop the VM gracefully."""
        self._shutdown_requested = True

        if self._shutdown_timer and not self._shutdown_timer.done():
            self._shutdown_timer.cancel()
            self._shutdown_timer = None

        await self.vm_process.stop(timeout)

    async def resume(self) -> None:
        """Resume the VM if it was paused."""
        await self.vm_process.resume()

    async def pause(self, timeout: int = 30) -> None:
        """Pause the VM."""
        await self.vm_process.pause(timeout)

    async def run(self) -> None:
        """Main run loop."""
        # Check if shutdown was already requested
        if self.signal_manager.is_shutdown_requested():
            logger.info("Shutdown already requested, exiting immediately")
            return

        try:
            self._activation_socket = self.socket_activation.get_activation_socket()

            # Start VM immediately if not on-demand
            if not self.config.on_demand_enabled:
                logger.info("Starting VM")
                await self.start()

            # Start connection handling
            proxy_task = asyncio.create_task(self._handle_activation_connections())

            # Add periodic check for VM shutdown requests
            async def monitor_shutdown_signals():
                while not self.signal_manager.is_shutdown_requested():
                    # Check if VM process has requested shutdown
                    if hasattr(self, "vm_process") and self.vm_process._shutdown_requested:
                        logger.info("VM process requested shutdown")
                        self.signal_manager.request_shutdown()
                        break

                    await asyncio.sleep(1)  # Check every second

            monitor_task = asyncio.create_task(monitor_shutdown_signals())

            # Wait for shutdown signal or tasks to complete
            await asyncio.wait(
                [
                    asyncio.create_task(self.signal_manager.shutdown_event.wait()),
                    proxy_task,
                    monitor_task,
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel remaining tasks
            for task in [proxy_task, monitor_task]:
                if not task.done():
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
