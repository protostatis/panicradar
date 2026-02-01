"""CLI commands for the signal service."""

import asyncio
import os
import sys
from pathlib import Path


def cmd_check():
    """Run a single signal check."""
    from .service import run_signal_check

    db_path = os.environ.get("DB_PATH", "data/sentiment.db")
    asyncio.run(run_signal_check(db_path))


def cmd_run():
    """Run the signal service continuously."""
    from .service import SignalService

    db_path = os.environ.get("DB_PATH", "data/sentiment.db")
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    interval = int(os.environ.get("SIGNAL_CHECK_INTERVAL", "60"))

    service = SignalService(
        db_path=db_path,
        check_interval_minutes=interval,
        telegram_token=telegram_token,
    )

    print(f"Starting signal service...")
    print(f"  Database: {db_path}")
    print(f"  Check interval: {interval} minutes")
    print(f"  Telegram: {'configured' if telegram_token else 'not configured'}")
    print()

    try:
        asyncio.run(service.run_forever())
    except KeyboardInterrupt:
        print("\nStopping signal service...")
        service.stop()


def cmd_bot():
    """Run the Telegram bot for subscriber management."""
    from .alerts import AlertManager, TelegramBot

    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set")
        sys.exit(1)

    alert_manager = AlertManager()
    bot = TelegramBot(telegram_token, alert_manager)

    print("Starting Telegram bot...")
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        print("\nStopping bot...")


def main():
    """Main CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Crypto Contrarian Signal Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s check                   # Run single signal check
  %(prog)s run                     # Start continuous monitoring
  %(prog)s bot                     # Start Telegram bot

Environment variables:
  DB_PATH                          Path to sentiment database
  TELEGRAM_BOT_TOKEN               Telegram bot token for alerts
  SIGNAL_CHECK_INTERVAL            Check interval in minutes (default: 60)
""",
    )

    parser.add_argument(
        "command",
        choices=["check", "run", "bot"],
        help="Command to run",
    )

    args = parser.parse_args()

    if args.command == "check":
        cmd_check()
    elif args.command == "run":
        cmd_run()
    elif args.command == "bot":
        cmd_bot()


if __name__ == "__main__":
    main()
