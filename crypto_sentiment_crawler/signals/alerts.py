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


class NtfyChannel(AlertChannel):
    """Ntfy.sh push notifications - free, no account needed."""

    def __init__(self, topic: str, server: str = "https://ntfy.sh"):
        self.topic = topic
        self.server = server
        self.url = f"{server}/{topic}"

    async def send(self, subscriber: Subscriber, signal: Signal) -> bool:
        """Send signal alert via Ntfy."""
        # Determine priority and emoji based on signal type
        if "BULLISH" in signal.signal_type.value:
            emoji = "📈"
            priority = "high"
            tags = "chart_with_upwards_trend,money_with_wings"
        elif "BEARISH" in signal.signal_type.value:
            emoji = "📉"
            priority = "high"
            tags = "chart_with_downwards_trend,warning"
        elif signal.signal_type.value == "CAPITULATION":
            emoji = "💀"
            priority = "urgent"
            tags = "skull,rotating_light"
        elif signal.signal_type.value == "EUPHORIA":
            emoji = "🚀"
            priority = "urgent"
            tags = "rocket,warning"
        else:
            emoji = "🔔"
            priority = "default"
            tags = "bell"

        title = f"{emoji} {signal.signal_type.value.replace('_', ' ')} - {signal.coin}"
        message = (
            f"Strength: {signal.strength.value}\n"
            f"Confidence: {signal.confidence:.0%}\n"
            f"Sentiment: {signal.sentiment_score:+.2f} ({signal.sentiment_zscore:+.1f}σ)\n"
            f"Price 24h: {signal.price_change_24h:+.1f}%\n\n"
            f"{signal.description}"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    data=message.encode('utf-8'),
                    headers={
                        "Title": title,
                        "Priority": priority,
                        "Tags": tags,
                    },
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"Sent alert to Ntfy topic: {self.topic}")
                        return True
                    else:
                        error = await resp.text()
                        logger.error(f"Ntfy error: {error}")
                        return False
        except Exception as e:
            logger.error(f"Failed to send Ntfy alert: {e}")
            return False

    async def send_message(self, title: str, message: str, priority: str = "default") -> bool:
        """Send a plain message to the topic."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    data=message.encode('utf-8'),
                    headers={
                        "Title": title,
                        "Priority": priority,
                    },
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"Failed to send Ntfy message: {e}")
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
    """Interactive Telegram bot for PanicRadar signal service."""

    def __init__(
        self,
        token: str,
        alert_manager: AlertManager,
        db_path: str = "data/sentiment.db",
    ):
        self.token = token
        self.channel = TelegramChannel(token)
        self.alert_manager = alert_manager
        self.api_base = f"https://api.telegram.org/bot{token}"
        self.db_path = db_path
        self._offset = 0

    async def _get_signal_service(self):
        """Lazy-load SignalService to avoid circular imports."""
        from .service import SignalService

        return SignalService(db_path=self.db_path)

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
        elif text.startswith("/panic"):
            await self._handle_panic(chat_id)
        elif text.startswith("/btc"):
            await self._handle_btc(chat_id)
        elif text.startswith("/sources"):
            await self._handle_sources(chat_id)
        elif text.startswith("/subscribe"):
            await self._handle_subscribe(chat_id, text)
        elif text.startswith("/signals"):
            await self._handle_signals(chat_id)
        elif text.startswith("/help"):
            await self._handle_help(chat_id)

    async def _handle_start(self, chat_id: str) -> None:
        """Handle /start command."""
        welcome = (
            "*PanicRadar* — See the panic before the crowd.\n\n"
            "Real-time contrarian signals from 30+ crypto communities. "
            "Bayesian intelligence learns which sources to trust.\n\n"
            "*Commands:*\n"
            "/panic — Live panic score\n"
            "/btc — BTC sentiment breakdown\n"
            "/sources — Most accurate sources right now\n"
            "/subscribe — Get push alerts for signals\n"
            "/signals — Recent signals\n"
            "/help — Signal types explained\n\n"
            "Dashboard: panicradar.ai"
        )
        await self.channel.send_message(chat_id, welcome)

    async def _handle_panic(self, chat_id: str) -> None:
        """Handle /panic command — live panic score and interpretation."""
        try:
            service = await self._get_signal_service()
            summary = await service.get_market_summary()

            if "error" in summary:
                await self.channel.send_message(
                    chat_id, f"Could not load data: {summary['error']}"
                )
                return

            sentiment = summary.get("sentiment_score", 0)
            zscore = summary.get("sentiment_zscore", 0)
            state = summary.get("sentiment_state", "Unknown")
            fear = summary.get("fear_index", 0)
            euphoria = summary.get("euphoria_index", 0)
            activity = summary.get("activity_level", 0)
            price = summary.get("current_price", 0)
            change_24h = summary.get("price_change_24h", 0)

            # Build panic bar
            # Map sentiment from [-1, 1] to panic [0, 100]
            panic_pct = max(0, min(100, int((1 - sentiment) * 50)))
            filled = panic_pct // 10
            bar = "█" * filled + "░" * (10 - filled)

            # Interpretation
            if zscore < -2:
                interpretation = "Extreme fear — historically marks bottoms."
            elif zscore < -1.5:
                interpretation = "Elevated fear — crowd is anxious."
            elif zscore > 2:
                interpretation = "Extreme greed — historically marks tops."
            elif zscore > 1.5:
                interpretation = "Elevated greed — crowd is euphoric."
            else:
                interpretation = "Conditions within normal ranges."

            text = (
                f"*PanicRadar — Live Reading*\n\n"
                f"State: *{state}*\n"
                f"Sentiment: `{sentiment:+.3f}` (z-score: {zscore:+.2f}σ)\n"
                f"`[{bar}]` {panic_pct}%\n\n"
                f"Fear: {fear:.1%}  |  Euphoria: {euphoria:.1%}  |  Activity: {activity:.1%}\n\n"
                f"BTC: ${price:,.0f} ({change_24h:+.1f}% 24h)\n\n"
                f"_{interpretation}_\n\n"
                f"Dashboard: panicradar.ai"
            )
            await self.channel.send_message(chat_id, text)

        except Exception as e:
            logger.error(f"Error handling /panic: {e}")
            await self.channel.send_message(
                chat_id, "Could not fetch panic score. Try again shortly."
            )

    async def _handle_btc(self, chat_id: str) -> None:
        """Handle /btc command — BTC sentiment breakdown."""
        try:
            service = await self._get_signal_service()
            summary = await service.get_market_summary()

            if "error" in summary:
                await self.channel.send_message(
                    chat_id, f"Could not load data: {summary['error']}"
                )
                return

            price = summary.get("current_price", 0)
            change_24h = summary.get("price_change_24h", 0)
            change_7d = summary.get("price_change_7d", 0)
            sentiment = summary.get("sentiment_score", 0)
            zscore = summary.get("sentiment_zscore", 0)
            state = summary.get("sentiment_state", "Unknown")
            divergence = summary.get("divergence_score", 0)
            fear = summary.get("fear_index", 0)
            euphoria = summary.get("euphoria_index", 0)
            activity = summary.get("activity_level", 0)
            baseline = summary.get("baseline_stats", {})

            text = (
                f"*BTC Sentiment Breakdown*\n\n"
                f"*Price*\n"
                f"  ${price:,.0f}  ({change_24h:+.1f}% 24h / {change_7d:+.1f}% 7d)\n\n"
                f"*Sentiment*\n"
                f"  Score: `{sentiment:+.3f}`  Z-Score: `{zscore:+.2f}σ`\n"
                f"  State: {state}\n"
                f"  Divergence: `{divergence:+.3f}`\n\n"
                f"*Crowd Psychology*\n"
                f"  Fear: {fear:.1%}\n"
                f"  Euphoria: {euphoria:.1%}\n"
                f"  Activity: {activity:.1%}\n\n"
                f"*30d Baseline*\n"
                f"  Mean: `{baseline.get('sentiment_mean', 0):+.3f}`  "
                f"Std: `{baseline.get('sentiment_std', 0):.3f}`\n\n"
                f"Dashboard: panicradar.ai"
            )
            await self.channel.send_message(chat_id, text)

        except Exception as e:
            logger.error(f"Error handling /btc: {e}")
            await self.channel.send_message(
                chat_id, "Could not fetch BTC data. Try again shortly."
            )

    async def _handle_sources(self, chat_id: str) -> None:
        """Handle /sources command — top sources by accuracy."""
        try:
            from ..analysis.source_weights import load_weights_from_db_sync

            weight_data = await asyncio.to_thread(
                load_weights_from_db_sync,
                self.db_path,
            )
            weights = weight_data.get("weights", {})

            if not weights:
                await self.channel.send_message(
                    chat_id, "No source data available yet."
                )
                return

            # Load accuracy from database
            import sqlite3

            from ..sqlite_utils import connect_sqlite

            belief_version = weight_data.get("belief_version")

            def load_rows():
                conn = connect_sqlite(self.db_path)
                conn.row_factory = sqlite3.Row
                try:
                    snapshot_columns = {
                        row[1]
                        for row in conn.execute(
                            "PRAGMA table_info(source_weight_snapshots)"
                        )
                    }
                    if belief_version is None or "belief_version" not in snapshot_columns:
                        return conn.execute(
                            "SELECT source, weight, accuracy, is_contrarian, sample_size "
                            "FROM source_weights ORDER BY weight DESC LIMIT 10"
                        ).fetchall()
                    return conn.execute(
                        "SELECT source, weight, accuracy, is_contrarian, sample_size "
                        "FROM source_weight_snapshots WHERE belief_version = ? "
                        "ORDER BY weight DESC LIMIT 10",
                        (belief_version,),
                    ).fetchall()
                finally:
                    conn.close()

            rows = await asyncio.to_thread(load_rows)

            if not rows:
                await self.channel.send_message(
                    chat_id, "No source weight data available yet."
                )
                return

            momentum = []
            contrarian_list = []
            for row in rows:
                name = row["source"].replace("_", " ").title()
                acc = row["accuracy"] * 100 if row["accuracy"] else 0
                n = row["sample_size"] or 0
                entry = f"  `{name[:18]:<18}` {acc:.0f}% (n={n})"
                if row["is_contrarian"]:
                    contrarian_list.append(entry)
                else:
                    momentum.append(entry)

            text = "*Top Sources by Weight*\n\n"

            if momentum:
                text += "*Momentum* (sentiment aligns with price)\n"
                text += "\n".join(momentum[:5]) + "\n\n"

            if contrarian_list:
                text += "*Contrarian* (inverted signal)\n"
                text += "\n".join(contrarian_list[:5]) + "\n\n"

            text += (
                "_Contrarian sources have <45% accuracy — "
                "when they're bearish, price tends to rise._\n\n"
                "Full rankings: panicradar.ai/sources"
            )
            await self.channel.send_message(chat_id, text)

        except Exception as e:
            logger.error(f"Error handling /sources: {e}")
            await self.channel.send_message(
                chat_id, "Could not fetch source data. Try again shortly."
            )

    async def _handle_subscribe(self, chat_id: str, text: str) -> None:
        """Handle /subscribe command."""
        # Check if already subscribed
        existing = next(
            (s for s in self.alert_manager.subscribers if s.chat_id == chat_id), None
        )
        if existing:
            await self.channel.send_message(
                chat_id,
                "You're already subscribed. Use /panic to check the market.",
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
            "*Subscribed to PanicRadar alerts!*\n\n"
            "You'll receive contrarian signal alerts for BTC.\n\n"
            "Try /panic to see the current reading.",
        )

    async def _handle_signals(self, chat_id: str) -> None:
        """Handle /signals command."""
        signals = self.alert_manager.get_signal_history(5)
        if not signals:
            await self.channel.send_message(
                chat_id,
                "No signals detected recently. "
                "Use /panic to check current conditions.",
            )
            return

        text = "*Recent Signals:*\n\n"
        for sig in signals[-5:]:
            emoji = {"BULLISH_DIVERGENCE": "🟢", "BEARISH_DIVERGENCE": "🔴",
                     "CAPITULATION": "💀", "EUPHORIA": "🚀"}.get(sig.signal_type.value, "🔔")
            text += (
                f"{emoji} {sig.timestamp.strftime('%m/%d %H:%M')} — "
                f"{sig.signal_type.value.replace('_', ' ')}\n"
            )

        await self.channel.send_message(chat_id, text)

    async def _handle_help(self, chat_id: str) -> None:
        """Handle /help command."""
        help_text = (
            "*PanicRadar — Help*\n\n"
            "*Signal Types:*\n"
            "🟢 BULLISH DIVERGENCE — Extreme fear + stable price\n"
            "🔴 BEARISH DIVERGENCE — Extreme greed + stable price\n"
            "💀 CAPITULATION — Panic selling spike\n"
            "🚀 EUPHORIA — Irrational greed spike\n\n"
            "*Key insight:* Price leads sentiment by ~15 hours. "
            "The crowd reacts to price — they don't predict it. "
            "Extreme fear after a drop is usually overdone.\n\n"
            "*Commands:*\n"
            "/panic — Live panic score\n"
            "/btc — BTC sentiment breakdown\n"
            "/sources — Most accurate sources\n"
            "/subscribe — Get push alerts\n"
            "/signals — Recent signals\n\n"
            "Dashboard: panicradar.ai"
        )
        await self.channel.send_message(chat_id, help_text)
