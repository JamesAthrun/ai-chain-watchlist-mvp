"""Stock scoring engine for limit order candidate selection.

Implements the scoring formula from ai_watchlist_limit_system_guide.md:
  score = 0.35 * category_score
        + 0.25 * relative_strength_score
        + 0.25 * support_score
        + 0.15 * open_strength_score
        - concentration_penalty

Score meanings:
  >= 80: preferred_buy_candidate
  65-79: buy_candidate_if_limit_reached
  50-64: watch_only
  < 50:  do_not_buy
"""

import logging
from typing import Optional

from app.core.models import TickerSnapshot, PortfolioSummary
from app.core.technical_analysis import TechnicalIndicators

logger = logging.getLogger(__name__)

# Category score mapping (from guide section 6.1)
CATEGORY_SCORES = {
    "core": 100,
    "semi_core": 80,
    "cyclical": 60,
    "high_beta": 40,
    "beta": 60,  # Map existing 'beta' role to semi-core/cyclical level
    "leveraged": 20,
}

# Stock-to-category mapping (from guide section 3)
# This overrides the watchlist.yaml role for more granular classification
TICKER_CATEGORY = {
    # Core
    "NVDA": "core", "AVGO": "core", "TSM": "core", "ASML": "core",
    "AMAT": "core", "KLAC": "core", "LRCX": "core", "MU": "cyclical",
    # Semi-Core
    "AMD": "semi_core", "MRVL": "semi_core", "COHR": "semi_core",
    "LITE": "semi_core", "TER": "semi_core", "FORM": "semi_core",
    "KLIC": "semi_core", "DELL": "semi_core", "HPE": "semi_core",
    "CLS": "semi_core",
    # Cyclical
    "SNDK": "cyclical", "AAOI": "cyclical",
    # High-Beta
    "ALAB": "high_beta", "CRDO": "high_beta", "SMCI": "high_beta",
    "IREN": "high_beta", "CRWV": "high_beta", "NBIS": "high_beta",
    "CORZ": "high_beta",
    # Core (power/datacenter)
    "VRT": "semi_core", "ETN": "semi_core", "PWR": "semi_core",
    "CEG": "semi_core", "GEV": "semi_core",
    # Others default to their watchlist role
}

# Chain classification (from guide section 10.2)
CHAIN_MAP = {
    "equipment": ["AMAT", "KLAC", "LRCX", "ASML"],
    "memory": ["MU", "SNDK"],
    "ai_network": ["AVGO", "MRVL", "CRDO", "ALAB"],
    "optical": ["COHR", "LITE", "AAOI"],
    "ai_compute": ["NVDA", "AMD"],
    "server_oem": ["SMCI", "DELL", "HPE", "CLS"],
    "power_dc": ["VRT", "ETN", "PWR", "CEG", "GEV", "IREN"],
    "cloud_high_beta": ["CRWV", "NBIS", "CORZ"],
}


def get_category(ticker: str, watchlist_role: str = "beta") -> str:
    """Get category for a ticker."""
    return TICKER_CATEGORY.get(ticker, watchlist_role)


def get_chain(ticker: str) -> Optional[str]:
    """Get which chain a ticker belongs to."""
    for chain, tickers in CHAIN_MAP.items():
        if ticker in tickers:
            return chain
    return None


def score_stock(
    ticker: str,
    snapshot: TickerSnapshot,
    ta: Optional[TechnicalIndicators],
    sector_pct_change: float,  # SMH or SOXX pct change today
    portfolio: Optional[PortfolioSummary] = None,
    watchlist_role: str = "beta",
) -> dict:
    """Score a stock for limit order candidacy.

    Returns:
        {
            "ticker": str,
            "score": float (0-100),
            "category": str,
            "chain": str | None,
            "action": "preferred_buy" | "buy_candidate" | "watch_only" | "do_not_buy",
            "reasons": [str],
        }
    """
    category = get_category(ticker, watchlist_role)
    chain = get_chain(ticker)
    reasons = []

    # 1. Category score (0-100, weight 0.35)
    cat_score = CATEGORY_SCORES.get(category, 50)

    # 2. Relative strength vs sector (0-100, weight 0.25)
    stock_pct = snapshot.pct_change_from_prev_close if not snapshot.data_missing else 0.0
    # If snapshot price is 0, use TA data
    if snapshot.last_price <= 0 and ta and ta.data_available and ta.prev_close > 0:
        stock_pct = (ta.current_price - ta.prev_close) / ta.prev_close * 100

    relative_strength = stock_pct - sector_pct_change

    if relative_strength > 2.0:
        rs_score = 100
        reasons.append("强于板块")
    elif relative_strength > 0:
        rs_score = 70
    elif relative_strength > -2.0:
        rs_score = 40
    else:
        rs_score = 10
        reasons.append("弱于板块")

    # 3. Support distance score (0-100, weight 0.25)
    support_score = 50  # default
    if ta and ta.data_available and ta.current_price > 0:
        nearest_sup = ta.nearest_support()
        if nearest_sup and nearest_sup > 0:
            distance = (ta.current_price - nearest_sup) / ta.current_price
            if distance <= 0.02:
                support_score = 100
                reasons.append("接近支撑位")
            elif distance <= 0.05:
                support_score = 70
            else:
                support_score = 30
                reasons.append("远离支撑")
        else:
            support_score = 40

    # 4. Open strength score (0-100, weight 0.15)
    open_pct = snapshot.pct_from_open if not snapshot.data_missing else 0.0
    if open_pct > 1.0:
        open_score = 100
    elif open_pct >= 0:
        open_score = 70
    elif open_pct > -1.0:
        open_score = 40
    else:
        open_score = 10

    # 5. Concentration penalty (0-30)
    concentration_penalty = 0.0
    if portfolio:
        # Single stock concentration
        ticker_exposure = portfolio.single_ticker_exposure.get(ticker, 0.0)
        max_single = {"core": 0.15, "semi_core": 0.10, "high_beta": 0.05,
                      "cyclical": 0.10, "beta": 0.08, "leveraged": 0.02}
        max_pct = max_single.get(category, 0.10)
        if ticker_exposure > max_pct * 0.8:  # Already at 80% of max
            concentration_penalty += 20
            reasons.append(f"仓位已重({ticker_exposure*100:.0f}%)")
        elif ticker_exposure > max_pct * 0.5:
            concentration_penalty += 10

        # Chain concentration
        if chain:
            chain_exposure = sum(
                portfolio.single_ticker_exposure.get(t, 0.0)
                for t in CHAIN_MAP.get(chain, [])
            )
            if chain_exposure > 0.35:
                concentration_penalty += 15
                reasons.append(f"产业链过重")

    # Final score
    score = (
        0.35 * cat_score
        + 0.25 * rs_score
        + 0.25 * support_score
        + 0.15 * open_score
        - concentration_penalty
    )
    score = max(0, min(100, score))

    # RSI penalty: overbought stocks should not be bought
    if ta and ta.data_available and ta.rsi_14 > 75:
        score -= 20
        reasons.append("RSI过热")
    # RSI bonus: oversold near support
    if ta and ta.data_available and ta.rsi_14 < 30 and support_score >= 70:
        score += 10
        reasons.append("RSI超卖+近支撑")

    # Trend penalty: downtrend
    if ta and ta.data_available and ta.trend == "down" and ta.current_price < ta.ma20:
        score -= 10
        reasons.append("趋势偏空")

    score = max(0, min(100, score))

    # Action classification
    if score >= 80:
        action = "preferred_buy"
    elif score >= 65:
        action = "buy_candidate"
    elif score >= 50:
        action = "watch_only"
    else:
        action = "do_not_buy"

    return {
        "ticker": ticker,
        "score": round(score, 1),
        "category": category,
        "chain": chain,
        "action": action,
        "reasons": reasons,
    }


def score_all_stocks(
    snapshots: dict[str, TickerSnapshot],
    ta_results: dict[str, TechnicalIndicators],
    sector_pct_change: float,
    portfolio: Optional[PortfolioSummary] = None,
    watchlist: Optional[dict] = None,
) -> list[dict]:
    """Score all stocks and return sorted list (highest score first).

    Excludes NVDA (indicator only) and index tickers.
    """
    results = []

    for ticker, snap in snapshots.items():
        if ticker.startswith("^") or ticker in ("QQQ", "SMH", "SOXX", "NVDA"):
            continue

        # Get watchlist role
        role = "beta"
        if watchlist:
            for bucket_data in watchlist.get("buckets", {}).values():
                if ticker in bucket_data.get("tickers", []):
                    role = bucket_data.get("role", "beta")
                    break

        ta = ta_results.get(ticker)
        scored = score_stock(ticker, snap, ta, sector_pct_change, portfolio, role)
        results.append(scored)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results
