"""
Confounder data collection for causal inference.

Collects observable proxy variables to block backdoor paths in the causal DAG.
"""

from .news import NewsCollector
from .macro import MacroCollector
from .regime import RegimeCollector
from .models import ConfounderSnapshot
from .collector import ConfounderCollector

__all__ = [
    "NewsCollector",
    "MacroCollector",
    "RegimeCollector",
    "ConfounderSnapshot",
    "ConfounderCollector",
]
