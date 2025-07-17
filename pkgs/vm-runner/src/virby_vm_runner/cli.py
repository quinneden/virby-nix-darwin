"""CLI entry point for the Virby VM runner."""

import asyncio
import logging
import os
import stat
import sys

from .config import VMConfig
from .runner import VirbyVMRunner


def setup_logging(debug: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def debug_startup_environment():
    """Debug environment and file descriptors at startup."""
    logger = logging.getLogger(__name__)
    logger.debug("=== STARTUP DEBUG ===")

    # Log key environment variables
    env_vars = [
        "VIRBY_ON_DEMAND",
        "VIRBY_VM_CONFIG_FILE",
        "VIRBY_WORKING_DIRECTORY",
        "LISTEN_FDS",
        "LISTEN_PID",
        "LAUNCH_DAEMON_SOCKET_NAME",
    ]
    for var in env_vars:
        value = os.environ.get(var, "null")
        logger.debug(f"ENV {var}={value}")

    # Debug file descriptors
    logger.debug("File descriptors:")
    for fd in range(10):
        try:
            fd_stat = os.fstat(fd)
            if stat.S_ISSOCK(fd_stat.st_mode):
                logger.debug(f"FD {fd}: SOCKET")
            elif stat.S_ISREG(fd_stat.st_mode):
                logger.debug(f"FD {fd}: FILE")
            elif stat.S_ISFIFO(fd_stat.st_mode):
                logger.debug(f"FD {fd}: PIPE")
            elif stat.S_ISCHR(fd_stat.st_mode):
                logger.debug(f"FD {fd}: CHAR_DEV")
            else:
                logger.debug(f"FD {fd}: OTHER")
        except OSError as e:
            if e.errno != 9:  # Not "Bad file descriptor"
                logger.debug(f"FD {fd}: ERROR {e}")
    logger.debug("=== END STARTUP DEBUG ===")


async def main() -> int:
    """Main CLI entry point."""
    try:
        debug_startup_environment()

        config_file_env = os.getenv("VIRBY_VM_CONFIG_FILE")
        config = VMConfig(config_path=config_file_env)

        # Setup logging based on config
        setup_logging(config.debug_enabled)

        # Create and run VM
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
