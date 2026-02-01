#!/usr/bin/env python3
"""
Live belief monitor - displays Bayesian beliefs table with auto-refresh.

Usage:
    uv run python -m crypto_sentiment_crawler.live_beliefs
    uv run python -m crypto_sentiment_crawler.live_beliefs --interval 10
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path


def clear_screen():
    """Clear terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def load_beliefs(state_path: str = "data/orchestrator_state.json") -> dict:
    """Load beliefs from state file."""
    path = Path(state_path)
    if not path.exists():
        return {}

    with open(path) as f:
        data = json.load(f)

    return data


def format_bar(value: float, width: int = 10) -> str:
    """Create a visual bar for a value between 0 and 1."""
    filled = int(value * width)
    empty = width - filled
    return "█" * filled + "░" * empty


def print_beliefs_table(data: dict):
    """Print formatted beliefs table."""
    beliefs = data.get("beliefs", {})
    last_update = data.get("last_belief_update", "never")
    total_crawls = data.get("total_crawls", 0)

    # Filter and sort beliefs
    sorted_beliefs = sorted(
        [(s, b) for s, b in beliefs.items() if b.get("accuracy") is not None],
        key=lambda x: x[1].get("accuracy", 0),
        reverse=True
    )

    # Header
    print("\033[1;36m" + "=" * 85 + "\033[0m")
    print("\033[1;36m" + "                    BAYESIAN BELIEF MONITOR" + "\033[0m")
    print("\033[1;36m" + "=" * 85 + "\033[0m")
    print()

    # Stats
    print(f"  Last Update: {last_update}")
    print(f"  Total Crawls: {total_crawls:,}")
    print(f"  Sources Tracked: {len(sorted_beliefs)}")
    print()

    # Table header
    print("\033[1m" + f"{'Source':<26} {'Accuracy':<12} {'Bar':<12} {'α':<8} {'β':<8} {'Mean':<8} {'Type':<12}" + "\033[0m")
    print("-" * 85)

    # Table rows
    for source, belief in sorted_beliefs:
        accuracy = belief.get("accuracy", 0)
        alpha = belief.get("alpha", 1)
        beta = belief.get("beta", 1)
        mean = alpha / (alpha + beta)
        is_contrarian = belief.get("is_contrarian", False)
        correlation = belief.get("correlation", 0)

        # Color coding
        if accuracy >= 0.50:
            color = "\033[32m"  # Green
            type_str = "MOMENTUM ↑"
        elif accuracy >= 0.45:
            color = "\033[33m"  # Yellow
            type_str = "NEUTRAL  →"
        else:
            color = "\033[31m"  # Red
            type_str = "CONTRARIAN ↓"

        bar = format_bar(accuracy)

        print(f"{color}{source:<26} {accuracy:>6.1%}       {bar}   {alpha:>6.1f}   {beta:>6.1f}   {mean:>6.3f}   {type_str}\033[0m")

    # Footer
    print("-" * 85)
    print()

    # Legend
    print("  \033[32m██ MOMENTUM\033[0m: Accuracy > 50% - follow sentiment direction")
    print("  \033[33m██ NEUTRAL\033[0m:  Accuracy 45-50% - weak signal")
    print("  \033[31m██ CONTRARIAN\033[0m: Accuracy < 45% - inverse sentiment")
    print()

    # Recommendations
    print("\033[1m  TOP SOURCES TO FOLLOW:\033[0m")
    for source, belief in sorted_beliefs[:3]:
        acc = belief.get("accuracy", 0)
        corr = belief.get("correlation", 0)
        print(f"    • {source}: {acc:.1%} accuracy, r={corr:+.3f}")

    print()
    print("\033[1m  CONTRARIAN SIGNALS (inverse these):\033[0m")
    contrarian = [(s, b) for s, b in sorted_beliefs if b.get("is_contrarian")]
    for source, belief in contrarian[:3]:
        acc = belief.get("accuracy", 0)
        print(f"    • {source}: {acc:.1%} accuracy (when bullish → expect drop)")

    print()
    print("\033[2m  Press Ctrl+C to exit\033[0m")


def run_live_monitor(state_path: str = "data/orchestrator_state.json", interval: int = 5):
    """Run live monitor with auto-refresh."""
    last_mtime = 0

    print("Starting live belief monitor...")
    print(f"Watching: {state_path}")
    print(f"Refresh interval: {interval}s")
    print()

    try:
        while True:
            # Check if file was modified
            path = Path(state_path)
            current_mtime = path.stat().st_mtime if path.exists() else 0

            # Always refresh on interval, highlight if changed
            clear_screen()

            data = load_beliefs(state_path)

            if current_mtime != last_mtime and last_mtime != 0:
                print("\033[1;33m  *** BELIEFS UPDATED ***\033[0m")
                print()

            print_beliefs_table(data)

            # Timestamp
            print(f"\n  \033[2mRefreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\033[0m")

            last_mtime = current_mtime
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\nMonitor stopped.")


def main():
    parser = argparse.ArgumentParser(description="Live Bayesian belief monitor")
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=5,
        help="Refresh interval in seconds (default: 5)"
    )
    parser.add_argument(
        "--state-file", "-f",
        type=str,
        default="data/orchestrator_state.json",
        help="Path to orchestrator state file"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print once and exit (no live monitoring)"
    )

    args = parser.parse_args()

    if args.once:
        data = load_beliefs(args.state_file)
        print_beliefs_table(data)
    else:
        run_live_monitor(args.state_file, args.interval)


if __name__ == "__main__":
    main()
