"""Centralized signal manager for consistent shutdown handling."""

import asyncio
import logging
import signal
from typing import Callable, Set

logger = logging.getLogger(__name__)


class SignalManager:
    """Centralized signal manager for VM shutdown coordination."""

    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._handlers: Set[Callable] = set()
        self._original_handlers = {}
        self._signals_setup = False

    def add_shutdown_handler(self, handler: Callable):
        """Add a shutdown handler to be called on signal.

        Args:
            handler: Callable to be executed during shutdown
        """
        self._handlers.add(handler)

    def remove_shutdown_handler(self, handler: Callable):
        """Remove a shutdown handler.

        Args:
            handler: Callable to be removed from shutdown handlers
        """
        self._handlers.discard(handler)

    def setup_signal_handlers(self):
        """Setup signal handlers once."""
        if self._signals_setup:
            logger.debug("Signal handlers already setup")
            return

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown")
            self._shutdown_event.set()

            # Call registered handlers
            for handler in self._handlers:
                try:
                    handler()
                except Exception as e:
                    logger.error(f"Error in shutdown handler: {e}")

        # Store original handlers for cleanup
        self._original_handlers[signal.SIGTERM] = signal.signal(signal.SIGTERM, signal_handler)
        self._original_handlers[signal.SIGINT] = signal.signal(signal.SIGINT, signal_handler)

        self._signals_setup = True
        logger.debug("Signal handlers setup complete")

    @property
    def shutdown_event(self) -> asyncio.Event:
        """Get the shutdown event for async coordination."""
        return self._shutdown_event

    def request_shutdown(self):
        """Manually request shutdown."""
        logger.info("Shutdown requested programmatically")
        self._shutdown_event.set()

    def cleanup(self):
        """Restore original signal handlers and cleanup resources."""
        if not self._signals_setup:
            return

        for sig, handler in self._original_handlers.items():
            try:
                signal.signal(sig, handler)
            except Exception as e:
                logger.error(f"Error restoring signal handler for {sig}: {e}")

        self._original_handlers.clear()
        self._handlers.clear()
        self._signals_setup = False
        logger.debug("Signal handlers cleaned up")

    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_event.is_set()
