"""Global market snapshot fetcher.

Fetches major global indices, commodities, and crypto via Twelve Data API.
Designed for twice-daily sampling (morning: US/EU close, evening: Asia close).
Also supports on-demand refresh.

Requires TWELVE_DATA_API_KEY env var.
Free tier: 800 requests/day, supports batch (comma-separated symbols).
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Twelve Data API config
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

# Ticker definitions grouped by category
# Twelve Data symbol format: indices use short names, metals use forex-style
GLOBAL_TICKERS = [
    # US Indices (ETF proxies - free tier doesn't support index symbols)
    {"symbol": "SPY", "name": "S&P 500", "category": "🇺🇸 美股", "currency": "USD"},
    {"symbol": "QQQ", "name": "纳斯达克", "category": "🇺🇸 美股", "currency": "USD"},
    {"symbol": "DIA", "name": "道琼斯", "category": "🇺🇸 美股", "currency": "USD"},
    # Asia-Pacific (ETF proxies)
    {"symbol": "EWH", "name": "香港ETF", "category": "🌏 亚太", "currency": "USD"},
    {"symbol": "EWJ", "name": "日本ETF", "category": "🌏 亚太", "currency": "USD"},
    {"symbol": "FXI", "name": "中国大盘ETF", "category": "🌏 亚太", "currency": "USD"},
    # China Concept / ADR
    {"symbol": "KWEB", "name": "中概互联ETF", "category": "🇨🇳 中概股", "currency": "USD"},
    # Precious Metals
    {"symbol": "XAU/USD", "name": "黄金", "category": "🥇 贵金属", "currency": "USD"},
    {"symbol": "SLV", "name": "白银ETF", "category": "🥇 贵金属", "currency": "USD"},
    {"symbol": "PPLT", "name": "铂金ETF", "category": "🥇 贵金属", "currency": "USD"},
    # Industrial Metals
    {"symbol": "CPER", "name": "铜ETF", "category": "🔧 工业金属", "currency": "USD"},
    # Lithium (no direct futures; LIT ETF as proxy)
    {"symbol": "LIT", "name": "锂电池ETF", "category": "🔋 锂/新能源", "currency": "USD"},
    # Energy
    {"symbol": "USO", "name": "原油ETF", "category": "⛽ 能源", "currency": "USD"},
    # Crypto
    {"symbol": "BTC/USD", "name": "比特币", "category": "₿ 加密货币", "currency": "USD"},
]

# Data directory for persistence
DATA_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent / "data"
SNAPSHOT_FILE = DATA_DIR / "global_market_latest.json"

# In-memory cache
_cache: dict = {"data": None, "timestamp": None}
CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_api_key() -> str:
    """Get Twelve Data API key from environment."""
    key = os.getenv("TWELVE_DATA_API_KEY", "")
    if not key:
        logger.warning("[global_market] TWELVE_DATA_API_KEY not set")
    return key


def _fetch_quotes_batch(symbols: list[str], api_key: str) -> dict:
    """Fetch quotes for multiple symbols in one batch request.

    Twelve Data /quote supports comma-separated symbols.
    Returns dict mapping symbol -> quote data.
    """
    symbols_str = ",".join(symbols)
    url = f"{TWELVE_DATA_BASE_URL}/quote"
    params = {
        "symbol": symbols_str,
        "apikey": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"[global_market] Twelve Data request failed: {e}")
        return {}

    # If single symbol, response is a single object; wrap in dict
    if len(symbols) == 1:
        return {symbols[0]: data}

    # Multi-symbol response: keys are symbol names
    return data


def fetch_global_market_snapshot() -> dict:
    """Fetch current global market snapshot from Twelve Data.

    Returns dict with timestamp and list of market entries.
    """
    api_key = _get_api_key()
    if not api_key:
        return _build_error_response("TWELVE_DATA_API_KEY not configured")

    logger.info(f"[global_market] Fetching {len(GLOBAL_TICKERS)} tickers from Twelve Data")

    # Twelve Data free tier allows batch of up to 8 symbols per request
    all_symbols = [t["symbol"] for t in GLOBAL_TICKERS]
    batch_size = 8
    raw_quotes: dict = {}

    for i in range(0, len(all_symbols), batch_size):
        batch = all_symbols[i:i + batch_size]
        if i > 0:
            # Free tier: 8 credits/minute. Wait between batches.
            logger.info("[global_market] Rate limit pause (61s between batches)")
            time.sleep(61)
        result = _fetch_quotes_batch(batch, api_key)
        raw_quotes.update(result)

    # Build market entries
    markets = []
    for entry in GLOBAL_TICKERS:
        symbol = entry["symbol"]
        quote = raw_quotes.get(symbol, {})

        if not quote or quote.get("status") == "error" or "close" not in quote:
            error_msg = quote.get("message", "no data") if isinstance(quote, dict) else "no data"
            logger.warning(f"[global_market] {symbol}: {error_msg}")
            markets.append({
                "ticker": symbol,
                "name": entry["name"],
                "category": entry["category"],
                "currency": entry["currency"],
                "price": None,
                "change_pct": None,
                "error": error_msg,
            })
            continue

        try:
            price = float(quote.get("close", 0))
            prev_close = float(quote.get("previous_close", 0))
            if prev_close > 0:
                change_pct = round((price - prev_close) / prev_close * 100, 2)
            else:
                # Fallback to percent_change from API
                change_pct = round(float(quote.get("percent_change", 0)), 2)

            markets.append({
                "ticker": symbol,
                "name": entry["name"],
                "category": entry["category"],
                "currency": entry["currency"],
                "price": round(price, 2),
                "prev_close": round(prev_close, 2),
                "change_pct": change_pct,
            })
        except (ValueError, TypeError) as e:
            logger.warning(f"[global_market] {symbol} parse error: {e}")
            markets.append({
                "ticker": symbol,
                "name": entry["name"],
                "category": entry["category"],
                "currency": entry["currency"],
                "price": None,
                "change_pct": None,
                "error": str(e),
            })

    now = datetime.now(timezone(timedelta(hours=8)))  # CST
    result = {
        "timestamp": now.isoformat(),
        "markets": markets,
    }

    # Update in-memory cache
    _cache["data"] = result
    _cache["timestamp"] = time.time()

    return result


def save_snapshot(data: Optional[dict] = None) -> dict:
    """Fetch (if needed) and persist snapshot to disk."""
    if data is None:
        data = fetch_global_market_snapshot()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"[global_market] Snapshot saved to {SNAPSHOT_FILE}")
    return data


def load_latest_snapshot() -> Optional[dict]:
    """Load last saved snapshot from disk."""
    if not SNAPSHOT_FILE.exists():
        return None
    try:
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[global_market] Failed to load snapshot: {e}")
        return None


def get_global_market(refresh: bool = False) -> dict:
    """Get global market data.

    If refresh=True, fetch fresh data from Twelve Data and save.
    Otherwise, return cached data (memory -> disk -> fresh fetch).
    """
    if refresh:
        data = fetch_global_market_snapshot()
        save_snapshot(data)
        return data

    # Check in-memory cache
    if _cache["data"] and _cache["timestamp"]:
        age = time.time() - _cache["timestamp"]
        if age < CACHE_TTL_SECONDS:
            return _cache["data"]

    # Check disk cache
    disk_data = load_latest_snapshot()
    if disk_data:
        _cache["data"] = disk_data
        _cache["timestamp"] = time.time()
        return disk_data

    # Nothing cached, fetch fresh
    data = fetch_global_market_snapshot()
    save_snapshot(data)
    return data


def _build_error_response(error: str) -> dict:
    """Build error response when fetch fails entirely."""
    now = datetime.now(timezone(timedelta(hours=8)))
    return {
        "timestamp": now.isoformat(),
        "markets": [],
        "error": error,
    }
