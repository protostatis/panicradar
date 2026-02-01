"""Subscription management with Stripe integration."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
import aiohttp
import json

logger = logging.getLogger(__name__)


class SubscriptionTier(Enum):
    """Subscription tiers with pricing."""

    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class TierConfig:
    """Configuration for a subscription tier."""

    name: str
    price_monthly: float  # USD
    signals_per_week: int  # -1 for unlimited
    coins: list[str]  # Empty = all coins
    priority_alerts: bool
    api_access: bool
    stripe_price_id: Optional[str] = None


# Tier definitions
TIERS = {
    SubscriptionTier.FREE: TierConfig(
        name="Free",
        price_monthly=0,
        signals_per_week=3,
        coins=["BTC"],
        priority_alerts=False,
        api_access=False,
    ),
    SubscriptionTier.PRO: TierConfig(
        name="Pro",
        price_monthly=9.99,
        signals_per_week=-1,  # Unlimited
        coins=[],  # All coins
        priority_alerts=True,
        api_access=False,
        stripe_price_id="price_pro_monthly",  # Replace with actual Stripe price ID
    ),
    SubscriptionTier.ENTERPRISE: TierConfig(
        name="Enterprise",
        price_monthly=49.99,
        signals_per_week=-1,
        coins=[],
        priority_alerts=True,
        api_access=True,
        stripe_price_id="price_enterprise_monthly",
    ),
}


@dataclass
class Subscription:
    """A user subscription."""

    user_id: str
    tier: SubscriptionTier
    stripe_customer_id: Optional[str]
    stripe_subscription_id: Optional[str]
    started_at: datetime
    expires_at: Optional[datetime]
    signals_used_this_week: int = 0
    week_start: Optional[datetime] = None

    def is_active(self) -> bool:
        """Check if subscription is active."""
        if self.tier == SubscriptionTier.FREE:
            return True
        if self.expires_at is None:
            return False
        return datetime.now() < self.expires_at

    def can_receive_signal(self) -> bool:
        """Check if user can receive another signal this week."""
        if not self.is_active():
            return False

        tier_config = TIERS[self.tier]
        if tier_config.signals_per_week == -1:
            return True

        # Reset weekly counter if needed
        now = datetime.now()
        if self.week_start is None or (now - self.week_start).days >= 7:
            self.signals_used_this_week = 0
            self.week_start = now

        return self.signals_used_this_week < tier_config.signals_per_week

    def record_signal(self) -> None:
        """Record that a signal was sent."""
        self.signals_used_this_week += 1


class StripeClient:
    """Stripe API client for subscription management."""

    def __init__(self, api_key: str, webhook_secret: Optional[str] = None):
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        self.api_base = "https://api.stripe.com/v1"

    async def _request(
        self, method: str, endpoint: str, data: Optional[dict] = None
    ) -> dict:
        """Make a request to Stripe API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                f"{self.api_base}/{endpoint}",
                headers=headers,
                data=data,
            ) as resp:
                result = await resp.json()
                if resp.status >= 400:
                    logger.error(f"Stripe error: {result}")
                    raise Exception(f"Stripe API error: {result.get('error', {}).get('message', 'Unknown error')}")
                return result

    async def create_customer(self, email: str, name: Optional[str] = None) -> str:
        """Create a Stripe customer."""
        data = {"email": email}
        if name:
            data["name"] = name

        result = await self._request("POST", "customers", data)
        return result["id"]

    async def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """Create a Stripe checkout session."""
        data = {
            "customer": customer_id,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
        }

        result = await self._request("POST", "checkout/sessions", data)
        return result["url"]

    async def cancel_subscription(self, subscription_id: str) -> bool:
        """Cancel a subscription."""
        try:
            await self._request("DELETE", f"subscriptions/{subscription_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel subscription: {e}")
            return False

    async def get_subscription(self, subscription_id: str) -> dict:
        """Get subscription details."""
        return await self._request("GET", f"subscriptions/{subscription_id}")


class SubscriptionManager:
    """Manages user subscriptions."""

    def __init__(self, stripe_api_key: Optional[str] = None, db_path: str = "data/subscriptions.db"):
        self.stripe = StripeClient(stripe_api_key) if stripe_api_key else None
        self.db_path = db_path
        self._subscriptions: dict[str, Subscription] = {}

    def get_subscription(self, user_id: str) -> Subscription:
        """Get or create subscription for user."""
        if user_id not in self._subscriptions:
            # Create free subscription by default
            self._subscriptions[user_id] = Subscription(
                user_id=user_id,
                tier=SubscriptionTier.FREE,
                stripe_customer_id=None,
                stripe_subscription_id=None,
                started_at=datetime.now(),
                expires_at=None,
            )
        return self._subscriptions[user_id]

    async def upgrade_to_pro(self, user_id: str, email: str) -> Optional[str]:
        """Start upgrade flow to Pro tier. Returns checkout URL."""
        if not self.stripe:
            logger.error("Stripe not configured")
            return None

        sub = self.get_subscription(user_id)

        # Create or get Stripe customer
        if not sub.stripe_customer_id:
            sub.stripe_customer_id = await self.stripe.create_customer(email)

        # Create checkout session
        checkout_url = await self.stripe.create_checkout_session(
            customer_id=sub.stripe_customer_id,
            price_id=TIERS[SubscriptionTier.PRO].stripe_price_id,
            success_url="https://yourapp.com/subscription/success",
            cancel_url="https://yourapp.com/subscription/cancel",
        )

        return checkout_url

    def activate_subscription(
        self, user_id: str, tier: SubscriptionTier, stripe_subscription_id: str
    ) -> None:
        """Activate a subscription after successful payment."""
        sub = self.get_subscription(user_id)
        sub.tier = tier
        sub.stripe_subscription_id = stripe_subscription_id
        sub.started_at = datetime.now()
        sub.expires_at = datetime.now() + timedelta(days=31)
        sub.signals_used_this_week = 0

        logger.info(f"Activated {tier.value} subscription for {user_id}")

    async def cancel_subscription(self, user_id: str) -> bool:
        """Cancel a subscription."""
        sub = self.get_subscription(user_id)

        if sub.tier == SubscriptionTier.FREE:
            return True

        if self.stripe and sub.stripe_subscription_id:
            success = await self.stripe.cancel_subscription(sub.stripe_subscription_id)
            if not success:
                return False

        # Downgrade to free
        sub.tier = SubscriptionTier.FREE
        sub.stripe_subscription_id = None
        sub.expires_at = None

        logger.info(f"Cancelled subscription for {user_id}")
        return True

    def check_signal_quota(self, user_id: str) -> tuple[bool, str]:
        """Check if user can receive a signal. Returns (can_receive, message)."""
        sub = self.get_subscription(user_id)

        if not sub.is_active():
            return False, "Your subscription has expired. Please renew to receive signals."

        if not sub.can_receive_signal():
            tier_config = TIERS[sub.tier]
            return False, (
                f"You've reached your limit of {tier_config.signals_per_week} signals/week. "
                f"Upgrade to Pro for unlimited signals!"
            )

        return True, "OK"

    def record_signal_sent(self, user_id: str) -> None:
        """Record that a signal was sent to user."""
        sub = self.get_subscription(user_id)
        sub.record_signal()

    def get_tier_info(self, tier: SubscriptionTier) -> dict:
        """Get tier information for display."""
        config = TIERS[tier]
        return {
            "name": config.name,
            "price": f"${config.price_monthly:.2f}/mo" if config.price_monthly > 0 else "Free",
            "signals": "Unlimited" if config.signals_per_week == -1 else f"{config.signals_per_week}/week",
            "coins": "All" if not config.coins else ", ".join(config.coins),
            "priority": "Yes" if config.priority_alerts else "No",
            "api": "Yes" if config.api_access else "No",
        }
