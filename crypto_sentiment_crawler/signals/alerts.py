"""Alert delivery system for contrarian signals."""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import aiohttp

from .models import Signal

logger = logging.getLogger(__name__)


@dataclass
class Subscriber:
    """A subscriber to signals."""

    id: str
    channel: str  # "telegram", "discord", "email"
    chat_id: str  # Platform-specific identifier
    tier: str  # "free", "pro", "enterprise"
    coins: list[str]  # Coins to track, empty = all
    created_at: datetime
    is_active: bool = True


class AlertChannel(ABC):
    """Abstract base class for alert delivery channels."""

    @abstractmethod
    async def send(self, subscriber: Subscriber, signal: Signal) -> bool:
        """Send alert to subscriber. Returns True if successful."""
        pass


class TelegramChannel(AlertChannel):
    """Telegram bot for sending alerts."""

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.api_base = f"https://api.telegram.org/bot{bot_token}"

    async def send(self, subscriber: Subscriber, signal: Signal) -> bool:
        """Send signal alert via Telegram."""
        message = signal.format_alert()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_base}/sendMessage",
                    json={
                        "chat_id": subscriber.chat_id,
                        "text": message,
                        "parse_mode": "Markdown",
                    },
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"Sent alert to Telegram user {subscriber.chat_id}")
                        return True
                    else:
                        error = await resp.text()
                        logger.error(f"Telegram API error: {error}")
                        return False
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return False

    async def send_message(self, chat_id: str, text: str) -> bool:
        """Send a plain text message."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_base}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False


class DiscordChannel(AlertChannel):
    """Discord webhook for sending alerts."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, subscriber: Subscriber, signal: Signal) -> bool:
        """Send signal alert via Discord webhook."""
        # Convert markdown to Discord format
        message = signal.format_alert()

        embed = {
            "title": f"{signal.signal_type.value.replace('_', ' ').upper()} - {signal.coin}",
            "description": signal.description,
            "color": 0x00FF00 if "BULLISH" in signal.signal_type.value else 0xFF0000,
            "fields": [
                {"name": "Sentiment", "value": f"{signal.sentiment_score:+.2f}", "inline": True},
                {"name": "Z-Score", "value": f"{signal.sentiment_zscore:+.1f}σ", "inline": True},
                {"name": "Price 24h", "value": f"{signal.price_change_24h:+.1f}%", "inline": True},
                {"name": "Confidence", "value": f"{signal.confidence:.0%}", "inline": True},
            ],
            "timestamp": signal.timestamp.isoformat(),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json={"embeds": [embed]},
                ) as resp:
                    if resp.status in (200, 204):
                        logger.info("Sent alert to Discord")
                        return True
                    else:
                        error = await resp.text()
                        logger.error(f"Discord webhook error: {error}")
                        return False
        except Exception as e:
            logger.error(f"Failed to send Discord alert: {e}")
            return False


class AlertManager:
    """Manages alert delivery to all subscribers."""

    def __init__(self):
        self.channels: dict[str, AlertChannel] = {}
        self.subscribers: list[Subscriber] = []
        self._signal_history: list[Signal] = []

    def add_channel(self, name: str, channel: AlertChannel) -> None:
        """Register an alert channel."""
        self.channels[name] = channel

    def add_subscriber(self, subscriber: Subscriber) -> None:
        """Add a subscriber."""
        self.subscribers.append(subscriber)

    def load_subscribers_from_db(self, db_path: str) -> None:
        """Load subscribers from database."""
        # TODO: Implement database loading
        pass

    async def broadcast_signal(self, signal: Signal) -> dict:
        """Broadcast a signal to all relevant subscribers."""
        self._signal_history.append(signal)

        results = {"sent": 0, "failed": 0, "skipped": 0}

        for subscriber in self.subscribers:
            if not subscriber.is_active:
                results["skipped"] += 1
                continue

            # Check if subscriber wants this coin
            if subscriber.coins and signal.coin not in subscriber.coins:
                results["skipped"] += 1
                continue

            # Get the appropriate channel
            channel = self.channels.get(subscriber.channel)
            if not channel:
                logger.warning(f"No channel configured for {subscriber.channel}")
                results["failed"] += 1
                continue

            # Send the alert
            success = await channel.send(subscriber, signal)
            if success:
                results["sent"] += 1
            else:
                results["failed"] += 1

        logger.info(
            f"Broadcast complete: {results['sent']} sent, "
            f"{results['failed']} failed, {results['skipped']} skipped"
        )
        return results

    def get_signal_history(self, limit: int = 100) -> list[Signal]:
        """Get recent signal history."""
        return self._signal_history[-limit:]


# Telegram bot command handlers
class TelegramBot:
    """Interactive Telegram bot for the signal service."""

    def __init__(self, token: str, alert_manager: AlertManager):
        self.token = token
        self.channel = TelegramChannel(token)
        self.alert_manager = alert_manager
        self.api_base = f"https://api.telegram.org/bot{token}"
        self._offset = 0

    async def start(self) -> None:
        """Start the bot polling loop."""
        logger.info("Starting Telegram bot...")
        while True:
            try:
                await self._poll_updates()
            except Exception as e:
                logger.error(f"Bot polling error: {e}")
            await asyncio.sleep(1)

    async def _poll_updates(self) -> None:
        """Poll for new messages."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.api_base}/getUpdates",
                params={"offset": self._offset, "timeout": 30},
            ) as resp:
                if resp.status != 200:
                    return

                data = await resp.json()
                if not data.get("ok"):
                    return

                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    await self._handle_update(update)

    async def _handle_update(self, update: dict) -> None:
        """Handle a single update."""
        message = update.get("message", {})
        text = message.get("text", "")
        chat_id = str(message.get("chat", {}).get("id", ""))

        if not chat_id or not text:
            return

        # Command handling
        if text.startswith("/start"):
            await self._handle_start(chat_id)
        elif text.startswith("/subscribe"):
            await self._handle_subscribe(chat_id, text)
        elif text.startswith("/status"):
            await self._handle_status(chat_id)
        elif text.startswith("/signals"):
            await self._handle_signals(chat_id)
        elif text.startswith("/help"):
            await self._handle_help(chat_id)

    async def _handle_start(self, chat_id: str) -> None:
        """Handle /start command."""
        welcome = """
🔮 *Crypto Contrarian Signals*

Welcome! I detect sentiment-price divergences that often precede market reversals.

*How it works:*
• Sentiment LAGS price by ~15 hours
• Extreme fear at stable prices → potential bottom
• Extreme greed at stable prices → potential top

*Commands:*
/subscribe - Start receiving signals
/status - Current market sentiment
/signals - Recent signals
/help - More info

🆓 Free tier: 3 signals/week
💎 Pro ($9.99/mo): Unlimited signals
"""
        await self.channel.send_message(chat_id, welcome)

    async def _handle_subscribe(self, chat_id: str, text: str) -> None:
        """Handle /subscribe command."""
        # Check if already subscribed
        existing = next(
            (s for s in self.alert_manager.subscribers if s.chat_id == chat_id), None
        )
        if existing:
            await self.channel.send_message(
                chat_id, "✅ You're already subscribed! Use /status to check the market."
            )
            return

        # Create new subscriber (free tier)
        subscriber = Subscriber(
            id=f"tg_{chat_id}",
            channel="telegram",
            chat_id=chat_id,
            tier="free",
            coins=["BTC"],  # Free tier = BTC only
            created_at=datetime.now(),
        )
        self.alert_manager.add_subscriber(subscriber)
        self.alert_manager.channels["telegram"] = self.channel

        await self.channel.send_message(
            chat_id,
            "✅ *Subscribed to Free Tier!*\n\n"
            "You'll receive up to 3 BTC signals per week.\n\n"
            "💎 Upgrade to Pro for:\n"
            "• Unlimited signals\n"
            "• All coins (ETH, SOL, etc.)\n"
            "• Priority alerts\n\n"
            "Contact @cryptosignals\\_support to upgrade.",
        )

    async def _handle_status(self, chat_id: str) -> None:
        """Handle /status command."""
        # This would normally fetch from detector
        await self.channel.send_message(
            chat_id,
            "📊 *Market Sentiment Status*\n\n"
            "Use this with live data integration.\n"
            "Run the signal detector to get real-time status.",
        )

    async def _handle_signals(self, chat_id: str) -> None:
        """Handle /signals command."""
        signals = self.alert_manager.get_signal_history(5)
        if not signals:
            await self.channel.send_message(
                chat_id, "No signals detected yet. Stay tuned!"
            )
            return

        text = "*Recent Signals:*\n\n"
        for sig in signals[-5:]:
            text += f"• {sig.timestamp.strftime('%m/%d %H:%M')} - {sig.signal_type.value}\n"

        await self.channel.send_message(chat_id, text)

    async def _handle_help(self, chat_id: str) -> None:
        """Handle /help command."""
        help_text = """
*Crypto Contrarian Signals - Help*

*Signal Types:*
🟢 BULLISH DIVERGENCE - Fear + stable price
🔴 BEARISH DIVERGENCE - Greed + stable price
💀 CAPITULATION - Extreme panic selling
🚀 EUPHORIA - Extreme greed spike

*Signal Strength:*
⚪ Weak - Lower confidence
🟡 Moderate - Average confidence
🔥 Strong - High confidence

*Pricing:*
🆓 Free: 3 signals/week, BTC only
💎 Pro ($9.99/mo): Unlimited, all coins

*Questions?*
Contact @cryptosignals\\_support
"""
        await self.channel.send_message(chat_id, help_text)
