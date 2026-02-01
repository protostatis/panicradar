"""Contrarian signal detection module."""

from .detector import ContrarianSignalDetector
from .models import Signal, SignalStrength, SignalType
from .subscriptions import SubscriptionManager, SubscriptionTier

__all__ = [
    "ContrarianSignalDetector",
    "Signal",
    "SignalStrength",
    "SignalType",
    "SubscriptionManager",
    "SubscriptionTier",
]
