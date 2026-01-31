"""Cold start initialization using price autocorrelation."""

import numpy as np
import pandas as pd
from statsmodels.tsa.ar_model import AutoReg

from .beliefs import SourceBelief


def compute_baseline_informativeness(
    prices: pd.Series,
    max_lag: int = 24,
    min_observations: int = 100,
) -> float:
    """
    Compute baseline informativeness from price autocorrelation.

    The baseline measures how much price is NOT predictable from its own history.
    - If price is a random walk → baseline ≈ 1.0 (any signal is valuable)
    - If price is highly autocorrelated → baseline ≈ 0.0 (easy to predict)

    Args:
        prices: Price time series (e.g., hourly prices)
        max_lag: Maximum lag for AR model
        min_observations: Minimum data points required

    Returns:
        Baseline informativeness score between 0 and 1
    """
    if len(prices) < min_observations:
        # Not enough data, return neutral baseline
        return 0.5

    # Clean data
    prices = prices.dropna()
    if len(prices) < min_observations:
        return 0.5

    # Use returns instead of prices (more stationary)
    returns = prices.pct_change().dropna()
    if len(returns) < min_observations:
        return 0.5

    try:
        # Fit AR model
        # Select optimal lag using AIC
        best_aic = np.inf
        best_model = None

        for lag in range(1, min(max_lag + 1, len(returns) // 10)):
            try:
                model = AutoReg(returns, lags=lag).fit()
                if model.aic < best_aic:
                    best_aic = model.aic
                    best_model = model
            except Exception:
                continue

        if best_model is None:
            return 0.5

        # R² = 1 - (RSS / TSS)
        # For AR model, we can use the model's pseudo R²
        # or compute it from residuals
        residuals = best_model.resid
        tss = np.sum((returns[best_model.model.endog_start:] - returns.mean()) ** 2)
        rss = np.sum(residuals ** 2)

        if tss == 0:
            return 0.5

        r_squared = 1 - (rss / tss)
        r_squared = max(0, min(1, r_squared))  # Clamp to [0, 1]

        # Baseline = unpredictability = 1 - R²
        baseline = 1.0 - r_squared

        return baseline

    except Exception:
        # Fall back to neutral baseline on any error
        return 0.5


def initialize_source_belief(
    source: str,
    baseline: float,
    source_type: str = "unknown",
) -> SourceBelief:
    """
    Initialize a new source belief using the baseline.

    Different source types get different prior adjustments:
    - news: +0.3 (headlines often lead)
    - social: +0.0 (neutral, high volume but mixed quality)
    - forum: +0.2 (OG community, slower but quality)
    - search: -0.2 (usually lagging indicator)

    Args:
        source: Source identifier
        baseline: Baseline from price autocorrelation (0-1)
        source_type: Type of source for prior adjustment

    Returns:
        Initialized SourceBelief
    """
    # Prior adjustments by source type
    type_adjustments = {
        "news": 0.3,
        "social": 0.0,
        "forum": 0.2,
        "search": -0.2,
        "unknown": 0.0,
    }

    adjustment = type_adjustments.get(source_type, 0.0)

    # Scale prior by baseline
    # Higher baseline = more optimistic prior
    alpha = 1.0 + baseline + adjustment
    alpha = max(0.5, alpha)  # Ensure positive

    return SourceBelief(
        source=source,
        alpha=alpha,
        beta=1.0,
    )


def compute_autocorrelation_structure(
    prices: pd.Series,
    max_lag: int = 48,
) -> dict:
    """
    Compute detailed autocorrelation structure for analysis.

    Returns autocorrelation at different lags, useful for
    understanding price dynamics and selecting evaluation lag.

    Args:
        prices: Price time series
        max_lag: Maximum lag to compute

    Returns:
        Dictionary with autocorrelation analysis
    """
    returns = prices.pct_change().dropna()

    if len(returns) < max_lag * 2:
        return {"error": "Insufficient data"}

    # Compute autocorrelation at each lag
    autocorrs = {}
    for lag in range(1, max_lag + 1):
        autocorrs[lag] = returns.autocorr(lag=lag)

    # Find significant lags (above noise threshold)
    noise_threshold = 2 / np.sqrt(len(returns))
    significant_lags = [
        lag for lag, ac in autocorrs.items()
        if abs(ac) > noise_threshold
    ]

    # Find optimal evaluation lag (first significant lag, or 4h default)
    optimal_lag = significant_lags[0] if significant_lags else 4

    return {
        "autocorrelations": autocorrs,
        "noise_threshold": noise_threshold,
        "significant_lags": significant_lags,
        "suggested_eval_lag": optimal_lag,
        "baseline_informativeness": compute_baseline_informativeness(prices, max_lag),
    }
