"""
CLI entry point for Hive Automation Bot.

Usage:
    python -m src.main [OPTIONS]

Options:
    --dry-run          Run without actual automation
    --config FILE      Custom config file path
    --headless         Run browser in headless mode
    --help             Show help message
"""

import asyncio
import argparse
import sys
from pathlib import Path

from src.utils import (
    setup_logging,
    get_logger,
    ConfigManager,
    HiveBotError,
    LogContext,
)
from src.bot import HiveBot

logger = None


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Hive Automation Bot - Phase 1 Workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main                        # Run with default config
  python -m src.main --config config.yaml  # Use custom config
  python -m src.main --headless             # Run in headless mode
  python -m src.main --dry-run              # Test run only
        """,
    )

    parser.add_argument(
        "--config",
        type=str,
        help="Path to custom config file",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without actual automation (for testing)",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    return parser.parse_args()


async def main():
    """Main entry point"""
    global logger

    args = parse_args()

    # Setup logging
    setup_logging(level=args.log_level)
    logger = get_logger(__name__)

    logger.info("Hive Automation Bot - Phase 1")
    logger.info(f"Starting with arguments: {args}")

    try:
        with LogContext("Main"):
            # Load configuration
            logger.info("Loading configuration...")
            config_manager = ConfigManager(config_file=args.config)

            # Override headless setting if provided
            if args.headless:
                if "browser" not in config_manager.config:
                    config_manager.config["browser"] = {}
                config_manager.config["browser"]["headless"] = True
                logger.info("Headless mode enabled")

            # Create and run bot
            logger.info("Initializing bot...")
            async with HiveBot(config_manager) as bot:
                logger.info("Running Phase 1 workflow...")
                success = await bot.run(dry_run=args.dry_run)

                if success:
                    logger.info("✓ Phase 1 completed successfully!")
                    return 0
                else:
                    logger.error("Phase 1 failed")
                    return 1

    except KeyboardInterrupt:
        logger.warning("Bot interrupted by user")
        return 130

    except HiveBotError as e:
        logger.error(f"Bot error: {e}")
        return 1

    except Exception as e:
        logger.critical(f"Unexpected error: {e}", exc_info=True)
        return 1


def cli_main():
    """CLI entry point that handles event loop"""
    exit_code = asyncio.run(main())
    sys.exit(exit_code)


if __name__ == "__main__":
    cli_main()
