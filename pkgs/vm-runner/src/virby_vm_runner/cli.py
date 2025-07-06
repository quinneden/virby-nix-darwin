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
    print("=== STARTUP DEBUG ===", file=sys.stderr)

    # Log key environment variables
    env_vars = [
        "VIRBY_SOCKET_ACTIVATION",
        "VIRBY_VM_CONFIG_FILE",
        "VIRBY_WORKING_DIRECTORY",
        "LISTEN_FDS",
        "LISTEN_PID",
        "LAUNCH_DAEMON_SOCKET_NAME",
    ]
    for var in env_vars:
        value = os.environ.get(var, "NOT_SET")
        print(f"ENV {var}={value}", file=sys.stderr)

    # Debug file descriptors
    print("File descriptors:", file=sys.stderr)
    for fd in range(10):
        try:
            fd_stat = os.fstat(fd)
            if stat.S_ISSOCK(fd_stat.st_mode):
                print(f"FD {fd}: SOCKET", file=sys.stderr)
            elif stat.S_ISREG(fd_stat.st_mode):
                print(f"FD {fd}: FILE", file=sys.stderr)
            elif stat.S_ISFIFO(fd_stat.st_mode):
                print(f"FD {fd}: PIPE", file=sys.stderr)
            elif stat.S_ISCHR(fd_stat.st_mode):
                print(f"FD {fd}: CHAR_DEV", file=sys.stderr)
            else:
                print(f"FD {fd}: OTHER", file=sys.stderr)
        except OSError as e:
            if e.errno != 9:  # Not "Bad file descriptor"
                print(f"FD {fd}: ERROR {e}", file=sys.stderr)
    print("=== END STARTUP DEBUG ===", file=sys.stderr)


async def main() -> int:
    """Main CLI entry point."""
    try:
        # Debug startup environment if socket activation is detected
        if os.getenv("VIRBY_SOCKET_ACTIVATION") == "1":
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
