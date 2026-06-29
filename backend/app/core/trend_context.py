"""Trend context classifier — distinguishes normal pullbacks from real trend breaks.

Prevents premature exit of core positions during routine pullbacks by evaluating
multi-timeframe MAs, relative strength, sector trend, and structural support.
"""

import logging
from typing import Optional

from app.core.technical_analysis import TechnicalIndicators

logger = logging.getLogger(__name__)

# --------------- Trend Status ---------------

TREND_STATUSES = (
    "STRONG_UPTREND",
    "PULLBACK_IN_UPTREND",
    "SHORT_TERM_BREAK_ONLY",
    "MEDIUM_TREND_BREAK",
    "LONG_TREND_BREAK",
    "RELATIVE_UNDERPERFORMER",
)


def classify_trend_status(ta: TechnicalIndicators) -> str:
    """Classify overall trend status from technical indicators.

    Priority order (first match wins):
    1. STRONG_UPTREND — price > MA20 > MA50 > MA100, MA50 rising
    2. PULLBACK_IN_UPTREND — below MA20 but above MA50, MA50 rising, RS ok
    3. MEDIUM_TREND_BREAK — below MA50, weak RS
    4. LONG_TREND_BREAK — below MA100 or MA200
    5. RELATIVE_UNDERPERFORMER — weak RS across all timeframes
    6. SHORT_TERM_BREAK_ONLY — default for below-MA20 situations
    """
    cp = ta.current_price
    ma20 = ta.ma20
    ma50 = ta.ma50
    ma100 = ta.ma100
    ma200 = ta.ma200

    if cp <= 0 or ma20 <= 0:
        return "SHORT_TERM_BREAK_ONLY"

    # 1. Strong uptrend: price above all key MAs, MAs stacked bullishly
    if (cp > ma20 and ma20 > ma50 > 0 and (ma100 <= 0 or ma50 > ma100)
            and ta.ma50_slope_pct > 0):
        return "STRONG_UPTREND"

    # 2. Pullback in uptrend: below MA20 but above MA50, MA50 rising, RS not deeply negative
    if (cp < ma20 and ma50 > 0 and cp > ma50
            and ta.ma50_slope_pct > 0
            and ta.rs_20d_vs_smh >= -1):
        return "PULLBACK_IN_UPTREND"

    # 4. Long trend break: below MA100 with weak 60d RS
    if ma100 > 0 and cp < ma100 and ta.rs_60d_vs_smh < 0:
        return "LONG_TREND_BREAK"

    # Also long trend break if below MA200
    if ma200 > 0 and cp < ma200:
        return "LONG_TREND_BREAK"

    # 3. Medium trend break: below MA50 with weak 20d RS
    if ma50 > 0 and cp < ma50 and ta.rs_20d_vs_smh < 0:
        return "MEDIUM_TREND_BREAK"

    # 5. Relative underperformer: weak across all timeframes
    if (ta.rs_5d_vs_smh < 0 and ta.rs_20d_vs_smh < 0 and ta.rs_60d_vs_smh < 0):
        return "RELATIVE_UNDERPERFORMER"

    # 6. Default: short-term break only
    return "SHORT_TERM_BREAK_ONLY"


# --------------- Short/Medium/Long Trend ---------------

def classify_short_term_trend(ta: TechnicalIndicators) -> str:
    """Classify short-term trend: STRONG / NEUTRAL / WEAK."""
    cp = ta.current_price
    if cp <= 0 or ta.ma20 <= 0:
        return "NEUTRAL"
    if cp > ta.ma20 and ta.ma20_slope_pct > 0:
        return "STRONG"
    if cp < ta.ma20 and ta.ma20_slope_pct < 0:
        return "WEAK"
    return "NEUTRAL"


def classify_medium_term_trend(ta: TechnicalIndicators) -> str:
    """Classify medium-term trend: UPTREND_INTACT / WEAKENING / BROKEN."""
    cp = ta.current_price
    ma50 = ta.ma50
    if cp <= 0 or ma50 <= 0:
        return "UPTREND_INTACT"
    if cp > ma50 and ta.ma50_slope_pct > 0:
        return "UPTREND_INTACT"
    if cp > ma50 and ta.ma50_slope_pct <= 0:
        return "WEAKENING"
    if cp < ma50:
        return "BROKEN"
    return "UPTREND_INTACT"


def classify_long_term_trend(ta: TechnicalIndicators) -> str:
    """Classify long-term trend: BULLISH / NEUTRAL / BEARISH."""
    cp = ta.current_price
    ma100 = ta.ma100
    ma200 = ta.ma200
    if cp <= 0:
        return "NEUTRAL"
    if ma200 > 0 and cp < ma200:
        return "BEARISH"
    if ma100 > 0 and cp < ma100:
        return "NEUTRAL"
    if ma100 > 0 and cp > ma100 and ta.ma100_slope_pct > 0:
        return "BULLISH"
    return "NEUTRAL"


# --------------- Sector Trend ---------------

def classify_sector_trend(
    smh_ta: Optional[TechnicalIndicators],
    soxx_ta: Optional[TechnicalIndicators] = None,
) -> str:
    """Classify semiconductor sector trend using SMH and optionally SOXX.

    Returns: STRONG / NEUTRAL / PULLBACK / WEAK
    """
    if not smh_ta or not smh_ta.data_available:
        return "NEUTRAL"

    smh_cp = smh_ta.current_price
    smh_ma20 = smh_ta.ma20
    smh_ma50 = smh_ta.ma50

    if smh_cp <= 0 or smh_ma20 <= 0:
        return "NEUTRAL"

    if smh_cp > smh_ma20:
        return "STRONG"
    elif smh_ma50 > 0 and smh_cp > smh_ma50:
        return "PULLBACK"
    elif smh_ma50 > 0 and smh_cp < smh_ma50:
        return "WEAK"
    else:
        return "PULLBACK"


# --------------- Full Trend Context ---------------

def build_trend_context(
    ta: TechnicalIndicators,
    smh_ta: Optional[TechnicalIndicators] = None,
    soxx_ta: Optional[TechnicalIndicators] = None,
) -> dict:
    """Build complete trend context for a position.

    Returns a dict with all trend context fields for use by exit engine and AI analysis.
    """
    cp = ta.current_price
    ma20 = ta.ma20
    ma50 = ta.ma50
    ma100 = ta.ma100
    ma200 = ta.ma200

    price_vs_ma20_pct = ((cp - ma20) / ma20 * 100) if ma20 > 0 and cp > 0 else 0.0
    price_vs_ma50_pct = ((cp - ma50) / ma50 * 100) if ma50 > 0 and cp > 0 else 0.0
    price_vs_ma100_pct = ((cp - ma100) / ma100 * 100) if ma100 > 0 and cp > 0 else 0.0
    price_vs_ma200_pct = ((cp - ma200) / ma200 * 100) if ma200 > 0 and cp > 0 else 0.0

    breaks_swing_low = (cp < ta.recent_swing_low) if ta.recent_swing_low > 0 and cp > 0 else False

    sector_trend = classify_sector_trend(smh_ta, soxx_ta)
    trend_status = classify_trend_status(ta)

    return {
        "shortTermTrend": classify_short_term_trend(ta),
        "mediumTermTrend": classify_medium_term_trend(ta),
        "longTermTrend": classify_long_term_trend(ta),
        "priceVsMA20Pct": round(price_vs_ma20_pct, 2),
        "priceVsMA50Pct": round(price_vs_ma50_pct, 2),
        "priceVsMA100Pct": round(price_vs_ma100_pct, 2),
        "priceVsMA200Pct": round(price_vs_ma200_pct, 2),
        "ma20SlopePct": round(ta.ma20_slope_pct, 3),
        "ma50SlopePct": round(ta.ma50_slope_pct, 3),
        "ma100SlopePct": round(ta.ma100_slope_pct, 3),
        "relativeStrength5dVsSMH": ta.rs_5d_vs_smh,
        "relativeStrength20dVsSMH": ta.rs_20d_vs_smh,
        "relativeStrength60dVsSMH": ta.rs_60d_vs_smh,
        "sectorTrend": sector_trend,
        "recentSwingLow": round(ta.recent_swing_low, 2) if ta.recent_swing_low > 0 else None,
        "breaksRecentSwingLow": breaks_swing_low,
        "trendStatus": trend_status,
    }
