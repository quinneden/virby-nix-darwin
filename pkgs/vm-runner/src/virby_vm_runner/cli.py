"""CLI entry point for the Virby VM runner."""

import asyncio
import logging
import os
import signal
import stat
import sys

from .config import VMConfig
from .runner import VirbyVMRunner
from .vm_process import cleanup_orphaned_vfkit_processes


def setup_logging(debug: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def setup_early_signal_handling() -> None:
    """Setup early signal handling before main application logic."""

    def early_signal_handler(signum, frame):
        logging.info(f"Early signal handler: received signal {signum}")
        # Set a global flag that can be checked by other parts of the application
        os.environ["VIRBY_SHUTDOWN_REQUESTED"] = "1"

    # Install early handlers for critical signals
    signal.signal(signal.SIGTERM, early_signal_handler)
    signal.signal(signal.SIGINT, early_signal_handler)


def debug_startup_environment():
    """Debug environment and file descriptors at startup."""
    logger = logging.getLogger(__name__)

    # Only do expensive debugging if explicitly requested
    if not logger.isEnabledFor(logging.DEBUG):
        return

    logger.debug("=== STARTUP DEBUG ===")

    # Log key environment variables efficiently
    env_vars = [
        "VIRBY_VM_CONFIG_FILE",
        "VIRBY_WORKING_DIRECTORY",
        "LISTEN_FDS",
        "LISTEN_PID",
        "LAUNCH_DAEMON_SOCKET_NAME",
    ]

    env_info = []
    for var in env_vars:
        value = os.environ.get(var, "null")
        env_info.append(f"{var}={value}")
    logger.debug(f"ENV: {', '.join(env_info)}")

    # Only check file descriptors if really needed and limit to first 5 FDs
    socket_fds = []
    for fd in range(5):  # Reduced from 10 to 5
        try:
            fd_stat = os.fstat(fd)
            if stat.S_ISSOCK(fd_stat.st_mode):
                socket_fds.append(str(fd))
        except OSError:
            continue

    if socket_fds:
        logger.debug(f"Socket FDs: {', '.join(socket_fds)}")

    logger.debug("=== END STARTUP DEBUG ===")


async def main() -> int:
    """Main CLI entry point."""
    try:
        # Setup early signal handling before anything else
        setup_early_signal_handling()

        debug_startup_environment()

        config_file_env = os.getenv("VIRBY_VM_CONFIG_FILE")
        config = VMConfig(config_path=config_file_env)

        setup_logging(config.debug_enabled)

        # Clean up any orphaned processes from previous runs
        try:
            cleanup_orphaned_vfkit_processes(config.working_directory)
        except Exception as e:
            logging.warning(f"Error during orphan cleanup: {e}")

        runner = VirbyVMRunner(config)
        await runner.run()

        return 0

    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        return 0
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        return 1


def cli_main() -> None:
    """Entry point for CLI."""
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    cli_main()
