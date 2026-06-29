"""Global market snapshot fetcher.

Fetches major global indices, commodities, and crypto via yfinance.
Designed for twice-daily sampling (morning: US/EU close, evening: Asia close).
Also supports on-demand refresh.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# Ticker definitions grouped by category
GLOBAL_TICKERS = [
    # US Indices
    {"ticker": "^GSPC", "name": "S&P 500", "category": "🇺🇸 美股", "currency": "USD"},
    {"ticker": "^IXIC", "name": "纳斯达克", "category": "🇺🇸 美股", "currency": "USD"},
    {"ticker": "^DJI", "name": "道琼斯", "category": "🇺🇸 美股", "currency": "USD"},
    # Europe
    {"ticker": "^GDAXI", "name": "德国DAX", "category": "🇪🇺 欧洲", "currency": "EUR"},
    {"ticker": "^FTSE", "name": "英国FTSE", "category": "🇪🇺 欧洲", "currency": "GBP"},
    # Asia-Pacific
    {"ticker": "^HSI", "name": "恒生指数", "category": "🌏 亚太", "currency": "HKD"},
    {"ticker": "^N225", "name": "日经225", "category": "🌏 亚太", "currency": "JPY"},
    {"ticker": "000001.SS", "name": "上证综指", "category": "🌏 亚太", "currency": "CNY"},
    # China Concept / ADR
    {"ticker": "KWEB", "name": "中概互联ETF", "category": "🇨🇳 中概股", "currency": "USD"},
    {"ticker": "FXI", "name": "中国大盘ETF", "category": "🇨🇳 中概股", "currency": "USD"},
    # Precious Metals
    {"ticker": "GC=F", "name": "黄金", "category": "🥇 贵金属", "currency": "USD"},
    {"ticker": "SI=F", "name": "白银", "category": "🥇 贵金属", "currency": "USD"},
    {"ticker": "PL=F", "name": "铂金", "category": "🥇 贵金属", "currency": "USD"},
    # Industrial Metals
    {"ticker": "HG=F", "name": "铜", "category": "🔧 工业金属", "currency": "USD"},
    {"ticker": "ALI=F", "name": "铝", "category": "🔧 工业金属", "currency": "USD"},
    # Lithium (no direct futures; LIT ETF as proxy)
    {"ticker": "LIT", "name": "锂电池ETF", "category": "🔋 锂/新能源", "currency": "USD"},
    # Energy
    {"ticker": "CL=F", "name": "原油", "category": "⛽ 能源", "currency": "USD"},
    # Crypto
    {"ticker": "BTC-USD", "name": "比特币", "category": "₿ 加密货币", "currency": "USD"},
]

# Data directory for persistence
DATA_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent / "data"
SNAPSHOT_FILE = DATA_DIR / "global_market_latest.json"

# In-memory cache
_cache: dict = {"data": None, "timestamp": None}
CACHE_TTL_SECONDS = 300  # 5 minutes


def fetch_global_market_snapshot() -> dict:
    """Fetch current global market snapshot from yfinance.

    Returns dict with timestamp and list of market entries.
    """
    tickers_str = " ".join(t["ticker"] for t in GLOBAL_TICKERS)
    logger.info(f"[global_market] Fetching {len(GLOBAL_TICKERS)} tickers from yfinance")

    try:
        # Download last 5 days to handle weekends/holidays
        df = yf.download(tickers_str, period="5d", progress=False, threads=True)
    except Exception as e:
        logger.error(f"[global_market] yfinance download failed: {e}")
        return _build_error_response(str(e))

    markets = []
    for entry in GLOBAL_TICKERS:
        ticker = entry["ticker"]
        try:
            # Handle both multi-ticker (MultiIndex) and single-ticker DataFrame
            if isinstance(df.columns, __import__("pandas").MultiIndex):
                closes = df["Close"][ticker].dropna()
            else:
                closes = df["Close"].dropna()

            if len(closes) < 2:
                logger.warning(f"[global_market] {ticker}: insufficient data ({len(closes)} rows)")
                markets.append({
                    **entry,
                    "price": None,
                    "change_pct": None,
                    "error": "insufficient data",
                })
                continue

            current_price = float(closes.iloc[-1])
            prev_close = float(closes.iloc[-2])
            change_pct = round((current_price - prev_close) / prev_close * 100, 2)

            markets.append({
                **entry,
                "price": round(current_price, 2),
                "prev_close": round(prev_close, 2),
                "change_pct": change_pct,
            })
        except Exception as e:
            logger.warning(f"[global_market] {ticker} parse error: {e}")
            markets.append({
                **entry,
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

    If refresh=True, fetch fresh data from yfinance and save.
    Otherwise, return cached data (memory -> disk -> fresh fetch).
    """
    # If refresh requested, fetch fresh
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
