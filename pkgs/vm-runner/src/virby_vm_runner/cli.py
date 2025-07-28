"""CLI entry point for the Virby VM runner."""

import asyncio
import logging
import os
import stat
import sys

from .config import VMConfig
from .runner import VirbyVMRunner
from .signal_manager import SignalManager
from .vm_process import cleanup_orphaned_vfkit_processes


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

    if not logger.isEnabledFor(logging.DEBUG):
        return

    logger.debug("=== STARTUP DEBUG ===")

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
    for fd in range(5):
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
    signal_manager = SignalManager()

    try:
        debug_startup_environment()

        config_file_env = os.getenv("VIRBY_VM_CONFIG_FILE")
        config = VMConfig(config_path=config_file_env)

        setup_logging(config.debug_enabled)

        # Setup signal handling once
        signal_manager.setup_signal_handlers()

        # Clean up any orphaned processes from previous runs
        try:
            await cleanup_orphaned_vfkit_processes(config.working_directory)
        except Exception as e:
            logging.warning(f"Error during orphan cleanup: {e}")

        runner = VirbyVMRunner(config, signal_manager)
        await runner.run()

        return 0

    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        return 0
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        return 1
    finally:
        signal_manager.cleanup()


def cli_main() -> None:
    """Entry point for CLI."""
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    cli_main()
