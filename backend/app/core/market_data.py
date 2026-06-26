"""Market data fetcher with multi-provider fallback.

Priority chain: polygon_proxy → polygon_native → yfinance
Configured via MARKET_DATA_PROVIDERS env var (comma-separated).
"""

import logging
import os
from typing import Optional

import requests
import yfinance as yf

from app.core.models import TickerSnapshot

logger = logging.getLogger(__name__)

# Provider config loaded once at import time
_POLYGON_PROXY_URL = os.getenv("POLYGON_PROXY_URL", "").rstrip("/")
_POLYGON_PROXY_KEY = os.getenv("POLYGON_PROXY_KEY", "")
_POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
_PROVIDERS = [
    p.strip()
    for p in os.getenv("MARKET_DATA_PROVIDERS", "polygon_proxy,yfinance").split(",")
    if p.strip()
]


def _ticker_to_polygon(ticker: str) -> str:
    """Convert Yahoo-style ticker to Polygon format. e.g. ^SOX -> I:SOX"""
    if ticker.startswith("^"):
        return f"I:{ticker[1:]}"
    return ticker


def _calc_pct(price: float, base: float) -> float:
    if base > 0:
        return round((price - base) / base * 100, 3)
    return 0.0


def _build_snapshot(
    ticker: str,
    last_price: float,
    prev_close: float,
    open_price: float,
    day_high: float,
    day_low: float,
    volume: float,
) -> TickerSnapshot:
    """Build a TickerSnapshot with calculated percentages."""
    return TickerSnapshot(
        ticker=ticker,
        last_price=last_price,
        prev_close=prev_close,
        open_price=open_price,
        day_high=day_high,
        day_low=day_low,
        pct_change_from_prev_close=_calc_pct(last_price, prev_close),
        pct_from_open=_calc_pct(last_price, open_price),
        pct_from_day_high=_calc_pct(last_price, day_high),
        pct_from_day_low=_calc_pct(last_price, day_low),
        volume=volume,
        data_missing=False,
        error=None,
    )


# --------------- Polygon providers ---------------


def _parse_polygon_snapshot(data: dict, ticker: str) -> TickerSnapshot:
    """Parse Polygon snapshot API response into TickerSnapshot."""
    # Response structure: {"ticker": {...}, "status": "OK"}
    # or {"ticker": {"day": {...}, "prevDay": {...}, "lastTrade": {...}, ...}}
    t = data.get("ticker", data)

    day = t.get("day", {})
    prev_day = t.get("prevDay", {})
    last_trade = t.get("lastTrade", {})

    last_price = last_trade.get("p", 0.0) or day.get("c", 0.0)
    open_price = day.get("o", 0.0)
    day_high = day.get("h", 0.0)
    day_low = day.get("l", 0.0)
    volume = day.get("v", 0.0)
    prev_close = prev_day.get("c", 0.0)

    if last_price == 0.0 and day.get("c", 0.0) > 0:
        last_price = day["c"]

    return _build_snapshot(ticker, last_price, prev_close, open_price, day_high, day_low, volume)


def _fetch_single_polygon_proxy(ticker: str) -> Optional[TickerSnapshot]:
    """Fetch from Polygon proxy service."""
    if not _POLYGON_PROXY_URL or not _POLYGON_PROXY_KEY:
        return None

    poly_ticker = _ticker_to_polygon(ticker)
    url = f"{_POLYGON_PROXY_URL}/v2/snapshot/locale/us/markets/stocks/tickers/{poly_ticker}"
    headers = {"X-Proxy-Key": _POLYGON_PROXY_KEY}

    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if data.get("status") == "ERROR" or data.get("status") == "NOT_FOUND":
        raise Exception(f"Polygon error: {data.get('message', data.get('error', 'unknown'))}")

    return _parse_polygon_snapshot(data, ticker)


def _fetch_single_polygon_native(ticker: str) -> Optional[TickerSnapshot]:
    """Fetch from Polygon/Massive native API."""
    if not _POLYGON_API_KEY:
        return None

    poly_ticker = _ticker_to_polygon(ticker)
    url = f"https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers/{poly_ticker}"
    params = {"apiKey": _POLYGON_API_KEY}

    resp = requests.get(url, params=params, timeout=15)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if data.get("status") == "ERROR" or data.get("status") == "NOT_FOUND":
        raise Exception(f"Polygon error: {data.get('message', data.get('error', 'unknown'))}")

    return _parse_polygon_snapshot(data, ticker)


# --------------- yfinance provider ---------------


def _fetch_single_yfinance(ticker: str) -> Optional[TickerSnapshot]:
    """Fetch data using yfinance (original logic)."""
    tk = yf.Ticker(ticker)

    last_price = 0.0
    open_price = 0.0
    day_high = 0.0
    day_low = 0.0
    prev_close = 0.0
    volume = 0.0

    # Try intraday first
    intraday = tk.history(period="1d", interval="5m")
    if intraday is not None and not intraday.empty:
        open_price = float(intraday["Open"].iloc[0])
        day_high = float(intraday["High"].max())
        day_low = float(intraday["Low"].min())
        last_price = float(intraday["Close"].iloc[-1])
        volume = float(intraday["Volume"].sum())
    else:
        # Fallback to daily
        daily = tk.history(period="5d", interval="1d")
        if daily is not None and not daily.empty:
            last_row = daily.iloc[-1]
            open_price = float(last_row["Open"])
            day_high = float(last_row["High"])
            day_low = float(last_row["Low"])
            last_price = float(last_row["Close"])
            volume = float(last_row["Volume"])
        else:
            raise Exception("No data from yfinance")

    # Get prev_close
    daily = tk.history(period="5d", interval="1d")
    if daily is not None and len(daily) >= 2:
        prev_close = float(daily["Close"].iloc[-2])
    else:
        prev_close = open_price

    return _build_snapshot(ticker, last_price, prev_close, open_price, day_high, day_low, volume)


# --------------- Main entry point ---------------

_PROVIDER_MAP = {
    "polygon_proxy": _fetch_single_polygon_proxy,
    "polygon_native": _fetch_single_polygon_native,
    "yfinance": _fetch_single_yfinance,
}


def fetch_snapshots(tickers: list[str]) -> dict[str, TickerSnapshot]:
    """Fetch market data with multi-provider fallback."""
    results: dict[str, TickerSnapshot] = {}
    providers = [p for p in _PROVIDERS if p in _PROVIDER_MAP]
    logger.info(f"[market_data] Starting fetch for {len(tickers)} tickers, providers: {providers}")

    provider_stats: dict[str, int] = {}

    for ticker in tickers:
        snap = None
        used_provider = None

        for provider_name in providers:
            fetch_fn = _PROVIDER_MAP[provider_name]
            try:
                snap = fetch_fn(ticker)
                if snap is not None and snap.last_price > 0:
                    used_provider = provider_name
                    break
                elif snap is not None and snap.last_price == 0:
                    logger.debug(f"[market_data] {ticker} -> {provider_name} returned price=0, trying next")
                    snap = None  # treat as failure, try next provider
            except Exception as e:
                logger.debug(f"[market_data] {ticker} -> {provider_name} FAILED: {e}")
                continue

        if snap is not None and not snap.data_missing:
            provider_stats[used_provider] = provider_stats.get(used_provider, 0) + 1
            logger.info(f"[market_data] {ticker} -> {used_provider} OK, price={snap.last_price:.2f}")
            results[ticker] = snap
        else:
            logger.warning(f"[market_data] {ticker} -> ALL providers failed")
            results[ticker] = TickerSnapshot(
                ticker=ticker,
                data_missing=True,
                error="All providers failed",
            )

    missing = [t for t, s in results.items() if s.data_missing]
    logger.info(
        f"[market_data] Done. {len(results)-len(missing)}/{len(results)} success. "
        f"Stats: {provider_stats}. Missing: {missing}"
    )
    return results
