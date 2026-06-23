"""Configuration loader for watchlist, rules, and portfolio."""

import json
import os
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load_yaml(filename: str) -> dict:
    filepath = CONFIG_DIR / filename
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_json(filename: str) -> dict:
    filepath = CONFIG_DIR / filename
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def load_watchlist() -> dict:
    return _load_yaml("watchlist.yaml")


def load_rules() -> dict:
    return _load_yaml("rules.yaml")


def load_portfolio() -> dict:
    return _load_json("portfolio.json")


def get_all_tickers() -> list[str]:
    """Get all tickers from watchlist, deduplicated and order-preserving."""
    watchlist = load_watchlist()
    seen: set[str] = set()
    tickers: list[str] = []

    # benchmarks
    for t in watchlist.get("benchmarks", {}).get("core_indices", []):
        if t not in seen:
            seen.add(t)
            tickers.append(t)

    # bucket tickers
    for bucket_name, bucket_data in watchlist.get("buckets", {}).items():
        for t in bucket_data.get("tickers", []):
            if t not in seen:
                seen.add(t)
                tickers.append(t)

    # indicators
    for ind_name, ind_data in watchlist.get("indicators", {}).items():
        t = ind_data.get("ticker")
        if t and t not in seen:
            seen.add(t)
            tickers.append(t)

    return tickers


def get_bucket_for_ticker(ticker: str) -> list[str]:
    """Return list of bucket names that contain the ticker."""
    watchlist = load_watchlist()
    buckets = []
    for bucket_name, bucket_data in watchlist.get("buckets", {}).items():
        if ticker in bucket_data.get("tickers", []):
            buckets.append(bucket_name)
    return buckets


def get_bucket_role(bucket_name: str) -> str:
    """Return the role of a bucket."""
    watchlist = load_watchlist()
    bucket_data = watchlist.get("buckets", {}).get(bucket_name, {})
    return bucket_data.get("role", "unknown")


def get_bucket_label(bucket_name: str) -> str:
    """Return the label of a bucket."""
    watchlist = load_watchlist()
    bucket_data = watchlist.get("buckets", {}).get(bucket_name, {})
    return bucket_data.get("label", bucket_name)
