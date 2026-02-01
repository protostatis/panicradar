"""
Affiliate link configuration.

PLACEHOLDER - Replace with real affiliate partners when ready.
"""

AFFILIATES = {
    "high_volatility": [
        {
            "name": "Exchange Partner",
            "description": "Fee discount for active traders",
            "url": "#exchange-partner",
            "category": "exchange",
        },
        {
            "name": "Wallet Partner",
            "description": "Secure your gains with cold storage",
            "url": "#wallet-partner",
            "category": "wallet",
        },
    ],
    "general": [
        {
            "name": "Charting Partner",
            "description": "Professional charting tools - Free trial",
            "url": "#charting-partner",
            "category": "tools",
        },
        {
            "name": "Tax Partner",
            "description": "Crypto tax filing made simple",
            "url": "#tax-partner",
            "category": "tax",
        },
    ],
}


def get_affiliates_for_context(volatility_state: str) -> tuple[str, list[dict]]:
    """
    Get affiliate recommendations based on current volatility context.

    Args:
        volatility_state: "Low", "Moderate", "High", or "Extreme"

    Returns:
        Tuple of (context_name, affiliate_list)
    """
    if volatility_state in ("High", "Extreme"):
        return "high_volatility", AFFILIATES["high_volatility"]
    return "general", AFFILIATES["general"]
