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
    from datetime import datetime
    from .service import SignalService
    from .alerts import NtfyChannel, Subscriber

    db_path = os.environ.get("DB_PATH", "data/sentiment.db")
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    ntfy_topic = os.environ.get("NTFY_TOPIC")
    interval = int(os.environ.get("SIGNAL_CHECK_INTERVAL", "1"))  # Default: 1 minute

    service = SignalService(
        db_path=db_path,
        check_interval_minutes=interval,
        telegram_token=telegram_token,
    )

    # Set up Ntfy notifications if configured
    if ntfy_topic:
        ntfy_channel = NtfyChannel(ntfy_topic)
        service.alert_manager.add_channel("ntfy", ntfy_channel)
        # Add a default subscriber for Ntfy
        service.alert_manager.add_subscriber(Subscriber(
            id="ntfy_default",
            channel="ntfy",
            chat_id=ntfy_topic,
            tier="pro",
            coins=[],  # All coins
            created_at=datetime.now(),
        ))

    print("\n" + "=" * 60)
    print("🔍 CONTRARIAN SIGNAL SERVICE")
    print("=" * 60)
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Database: {db_path}")
    print(f"  Check interval: {interval} minute(s)")
    print(f"  Telegram: {'✅ configured' if telegram_token else '❌ not configured'}")
    print(f"  Ntfy: {'✅ ' + ntfy_topic if ntfy_topic else '❌ not configured'}")
    print("=" * 60)
    print("\n  Watching for contrarian signals...")
    print("  Press Ctrl+C to stop\n")

    try:
        asyncio.run(service.run_forever(verbose=True))
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("Signal service stopped.")
        print("=" * 60)
        service.stop()


def cmd_bot():
    """Run the Telegram bot + signal detector concurrently."""
    from datetime import datetime
    from .alerts import AlertManager, TelegramBot, TelegramChannel, Subscriber
    from .service import SignalService

    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set")
        sys.exit(1)

    db_path = os.environ.get("DB_PATH", "data/sentiment.db")
    interval = int(os.environ.get("SIGNAL_CHECK_INTERVAL", "30"))
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "@PanicRadarAlerts")

    # Shared AlertManager with Telegram channel pre-registered
    alert_manager = AlertManager()
    telegram_channel = TelegramChannel(telegram_token)
    alert_manager.add_channel("telegram", telegram_channel)

    # Auto-register the alerts channel as a subscriber
    alert_manager.add_subscriber(Subscriber(
        id=f"channel_{channel_id}",
        channel="telegram",
        chat_id=channel_id,
        tier="pro",
        coins=[],  # All coins
        created_at=datetime.now(),
    ))

    # Bot shares the same AlertManager (so /subscribe users get alerts too)
    bot = TelegramBot(telegram_token, alert_manager, db_path=db_path)

    # Signal service shares the same AlertManager
    service = SignalService(
        db_path=db_path,
        check_interval_minutes=interval,
        telegram_token=telegram_token,
    )
    service.alert_manager = alert_manager

    print(f"Starting PanicRadar bot + signal detector...")
    print(f"  Database: {db_path}")
    print(f"  Signal check interval: {interval} min")
    print(f"  Alert channel: {channel_id}")
    print(f"  Commands: /panic /btc /sources /subscribe /signals /help")
    print(f"  Press Ctrl+C to stop\n")

    async def run_both():
        await asyncio.gather(
            bot.start(),
            service.run_forever(verbose=False),
        )

    try:
        asyncio.run(run_both())
    except KeyboardInterrupt:
        print("\nStopping bot + signal detector...")
        service.stop()


def cmd_test_notification():
    """Send a test notification to verify setup."""
    from datetime import datetime
    from .alerts import NtfyChannel
    from .models import Signal, SignalType, SignalStrength

    ntfy_topic = os.environ.get("NTFY_TOPIC")

    if not ntfy_topic:
        print("❌ Error: NTFY_TOPIC environment variable not set")
        print("\nTo set up Ntfy notifications:")
        print("  1. Install Ntfy app on your phone (iOS/Android)")
        print("  2. Subscribe to a unique topic (e.g., 'crypto-signals-abc123')")
        print("  3. Run: NTFY_TOPIC=your-topic-name uv run signals test")
        sys.exit(1)

    print(f"📤 Sending test notification to topic: {ntfy_topic}")

    # Create a test signal
    test_signal = Signal(
        timestamp=datetime.now(),
        signal_type=SignalType.BULLISH_DIVERGENCE,
        strength=SignalStrength.MODERATE,
        coin="BTC",
        sentiment_score=-0.35,
        sentiment_zscore=-1.8,
        price_change_24h=-2.5,
        price_change_7d=-8.0,
        divergence_score=0.4,
        description="TEST: This is a test notification. Extreme fear detected while price stabilizes.",
        confidence=0.65,
    )

    async def send_test():
        from .alerts import Subscriber
        channel = NtfyChannel(ntfy_topic)
        subscriber = Subscriber(
            id="test",
            channel="ntfy",
            chat_id=ntfy_topic,
            tier="pro",
            coins=[],
            created_at=datetime.now(),
        )
        return await channel.send(subscriber, test_signal)

    success = asyncio.run(send_test())

    if success:
        print("✅ Test notification sent! Check your phone.")
    else:
        print("❌ Failed to send notification. Check the topic name.")


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
  %(prog)s test                    # Send test notification
  %(prog)s bot                     # Start Telegram bot

Environment variables:
  DB_PATH                          Path to sentiment database
  NTFY_TOPIC                       Ntfy.sh topic for push notifications
  TELEGRAM_BOT_TOKEN               Telegram bot token for alerts
  SIGNAL_CHECK_INTERVAL            Check interval in minutes (default: 1)

Ntfy Setup:
  1. Install Ntfy app on your phone (free, no account needed)
  2. Subscribe to a unique topic name in the app
  3. Set NTFY_TOPIC=your-topic-name when running
""",
    )

    parser.add_argument(
        "command",
        choices=["check", "run", "test", "bot"],
        help="Command to run",
    )

    args = parser.parse_args()

    if args.command == "check":
        cmd_check()
    elif args.command == "run":
        cmd_run()
    elif args.command == "test":
        cmd_test_notification()
    elif args.command == "bot":
        cmd_bot()


if __name__ == "__main__":
    main()
