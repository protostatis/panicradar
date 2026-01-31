"""Granger causality tests for sentiment-price relationships."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, grangercausalitytests


@dataclass
class GrangerResult:
    """Result of Granger causality test."""

    source: str
    target: str
    optimal_lag: int
    pvalue: float
    f_statistic: float
    is_causal: bool  # p < 0.05
    all_lags: dict  # lag -> (f_stat, pvalue)


class GrangerAnalyzer:
    """
    Analyze Granger causality between sentiment and price.

    Tests whether past values of sentiment help predict future price
    beyond what past price alone can predict.
    """

    def __init__(self, max_lag: int = 24, significance: float = 0.05):
        """
        Args:
            max_lag: Maximum lag to test (in time units, e.g., hours)
            significance: P-value threshold for causality
        """
        self.max_lag = max_lag
        self.significance = significance

    def test_stationarity(self, series: pd.Series) -> dict:
        """
        Test if series is stationary using Augmented Dickey-Fuller test.

        Returns dict with test statistic, p-value, and whether stationary.
        """
        series = series.dropna()
        if len(series) < 20:
            return {"error": "Insufficient data", "is_stationary": None}

        try:
            result = adfuller(series, autolag="AIC")
            return {
                "adf_statistic": result[0],
                "pvalue": result[1],
                "used_lag": result[2],
                "n_obs": result[3],
                "is_stationary": result[1] < 0.05,
            }
        except Exception as e:
            return {"error": str(e), "is_stationary": None}

    def make_stationary(self, series: pd.Series) -> pd.Series:
        """
        Difference series to make it stationary if needed.
        """
        stat_test = self.test_stationarity(series)

        if stat_test.get("is_stationary"):
            return series

        # First difference
        diff_series = series.diff().dropna()
        stat_test = self.test_stationarity(diff_series)

        if stat_test.get("is_stationary"):
            return diff_series

        # Second difference if needed
        return diff_series.diff().dropna()

    def test_granger_causality(
        self,
        cause: pd.Series,
        effect: pd.Series,
        source_name: str = "cause",
        target_name: str = "effect",
    ) -> GrangerResult:
        """
        Test if 'cause' Granger-causes 'effect'.

        Args:
            cause: Potential causal series (e.g., sentiment)
            effect: Potential effect series (e.g., price returns)
            source_name: Name for the cause variable
            target_name: Name for the effect variable

        Returns:
            GrangerResult with test statistics
        """
        # Align series
        df = pd.DataFrame({
            "cause": cause,
            "effect": effect,
        }).dropna()

        if len(df) < self.max_lag * 2 + 10:
            return GrangerResult(
                source=source_name,
                target=target_name,
                optimal_lag=0,
                pvalue=1.0,
                f_statistic=0.0,
                is_causal=False,
                all_lags={},
            )

        # Make stationary
        df["cause"] = self.make_stationary(df["cause"])
        df["effect"] = self.make_stationary(df["effect"])
        df = df.dropna()

        if len(df) < self.max_lag * 2 + 10:
            return GrangerResult(
                source=source_name,
                target=target_name,
                optimal_lag=0,
                pvalue=1.0,
                f_statistic=0.0,
                is_causal=False,
                all_lags={},
            )

        try:
            # Granger test requires [effect, cause] order
            data = df[["effect", "cause"]]

            # Run test for all lags
            results = grangercausalitytests(
                data,
                maxlag=self.max_lag,
                verbose=False,
            )

            # Extract results for each lag
            all_lags = {}
            best_pvalue = 1.0
            best_lag = 1
            best_f = 0.0

            for lag, result in results.items():
                # Use F-test result
                f_test = result[0]["ssr_ftest"]
                f_stat, pvalue = f_test[0], f_test[1]
                all_lags[lag] = (f_stat, pvalue)

                if pvalue < best_pvalue:
                    best_pvalue = pvalue
                    best_lag = lag
                    best_f = f_stat

            return GrangerResult(
                source=source_name,
                target=target_name,
                optimal_lag=best_lag,
                pvalue=best_pvalue,
                f_statistic=best_f,
                is_causal=best_pvalue < self.significance,
                all_lags=all_lags,
            )

        except Exception as e:
            return GrangerResult(
                source=source_name,
                target=target_name,
                optimal_lag=0,
                pvalue=1.0,
                f_statistic=0.0,
                is_causal=False,
                all_lags={"error": str(e)},
            )

    def analyze_all_sources(
        self,
        source_sentiments: dict[str, pd.Series],
        price_returns: pd.Series,
    ) -> dict[str, GrangerResult]:
        """
        Test Granger causality for all sources against price.

        Args:
            source_sentiments: Dict mapping source name to sentiment series
            price_returns: Price returns series

        Returns:
            Dict mapping source name to GrangerResult
        """
        results = {}

        for source_name, sentiment in source_sentiments.items():
            result = self.test_granger_causality(
                cause=sentiment,
                effect=price_returns,
                source_name=source_name,
                target_name="price",
            )
            results[source_name] = result

        return results

    def rank_sources_by_causality(
        self,
        results: dict[str, GrangerResult],
    ) -> list[tuple[str, float, bool]]:
        """
        Rank sources by causal strength.

        Returns list of (source, pvalue, is_causal) sorted by p-value.
        """
        ranked = [
            (name, result.pvalue, result.is_causal)
            for name, result in results.items()
        ]
        return sorted(ranked, key=lambda x: x[1])


def compute_lead_lag_correlation(
    series1: pd.Series,
    series2: pd.Series,
    max_lag: int = 24,
) -> dict:
    """
    Compute cross-correlation at different lags.

    Positive lag means series1 leads series2.

    Returns dict with correlations at each lag and optimal lag.
    """
    correlations = {}

    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            # series2 leads
            corr = series1.iloc[-lag:].corr(series2.iloc[:lag])
        elif lag > 0:
            # series1 leads
            corr = series1.iloc[:-lag].corr(series2.iloc[lag:])
        else:
            corr = series1.corr(series2)

        if not np.isnan(corr):
            correlations[lag] = corr

    if not correlations:
        return {"error": "Could not compute correlations"}

    # Find optimal lag (highest absolute correlation)
    optimal_lag = max(correlations.keys(), key=lambda k: abs(correlations[k]))

    return {
        "correlations": correlations,
        "optimal_lag": optimal_lag,
        "optimal_correlation": correlations[optimal_lag],
        "series1_leads": optimal_lag > 0,
    }
