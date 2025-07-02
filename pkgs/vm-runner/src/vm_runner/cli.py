"""CLI entry point for the Virby VM runner."""

import asyncio
import logging
import os
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


async def main() -> int:
    """Main CLI entry point."""
    try:
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
