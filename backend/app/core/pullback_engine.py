"""Pullback add-on engine — evaluates whether existing holdings on pullback should be added to.

Distinguishes buyable pullbacks from breakdowns. Only evaluates existing positions.
Different from daily-plan which finds new buy opportunities.
"""

import logging
import statistics
from datetime import datetime, timezone
from typing import Optional

from app.core.models import PortfolioSummary, PositionInfo, TickerSnapshot
from app.core.technical_analysis import TechnicalIndicators
from app.core.exit_engine import classify_position_type
from app.core.trend_context import build_trend_context, classify_trend_status, classify_sector_trend

logger = logging.getLogger(__name__)

# --------------- Constants ---------------

PULLBACK_STATUSES = (
    "BUYABLE_PULLBACK",
    "NORMAL_PULLBACK",
    "WATCH_ONLY",
    "BREAKDOWN_DO_NOT_ADD",
    "REDUCE_INSTEAD",
)

PULLBACK_ACTIONS = (
    "DO_NOT_ADD",
    "WATCH_ONLY",
    "ADD_SMALL",
    "ADD_NORMAL",
    "ADD_DEEP_ONLY",
    "REDUCE_INSTEAD",
)

_BASE_AMOUNT = {
    "CORE": 400,
    "SEMI_CORE": 250,
    "CYCLICAL": 250,
    "HIGH_BETA": 100,
    "LEVERAGED_ETF": 0,
}

_MAX_SINGLE_POSITION_PCT = {
    "CORE": 15,
    "SEMI_CORE": 10,
    "CYCLICAL": 12,
    "HIGH_BETA": 5,
    "LEVERAGED_ETF": 3,
}

_SECTOR_EXPOSURE_LIMIT = 40  # percent


def _median3(a: Optional[float], b: Optional[float], c: Optional[float]) -> Optional[float]:
    """Compute median of up to three values, skipping None."""
    vals = [v for v in (a, b, c) if v is not None and v > 0]
    if not vals:
        return None
    return statistics.median(vals)


# --------------- Pullback Status Classifier ---------------

def classify_pullback_status(
    trend_status: str,
    current_price: float,
    ma50: float,
    ma50_slope_pct: float,
    rs_20d: float,
    breaks_swing_low: bool,
    sector_trend: str,
) -> str:
    """Classify pullback status based on trend context.

    Returns: BUYABLE_PULLBACK / NORMAL_PULLBACK / WATCH_ONLY / BREAKDOWN_DO_NOT_ADD / REDUCE_INSTEAD
    """
    # Buyable: pullback in uptrend with all conditions met
    if (trend_status == "PULLBACK_IN_UPTREND"
            and ma50 > 0 and current_price > ma50
            and ma50_slope_pct > 0
            and rs_20d >= -1
            and not breaks_swing_low
            and sector_trend != "WEAK"):
        return "BUYABLE_PULLBACK"

    # Normal: short-term break, still above MA50, no swing low break
    if (trend_status == "SHORT_TERM_BREAK_ONLY"
            and ma50 > 0 and current_price > ma50
            and not breaks_swing_low):
        return "NORMAL_PULLBACK"

    # Breakdown: below MA50, swing low broken, or very weak RS
    if (ma50 > 0 and current_price < ma50
            or breaks_swing_low
            or rs_20d < -2):
        return "BREAKDOWN_DO_NOT_ADD"

    # Reduce: medium or long trend break
    if trend_status in ("MEDIUM_TREND_BREAK", "LONG_TREND_BREAK"):
        return "REDUCE_INSTEAD"

    return "WATCH_ONLY"


# --------------- Add Limit Calculator ---------------

def _compute_add_limits(
    pos_type: str,
    current_price: float,
    ma20: float,
    ma50: float,
    atr: float,
    nearest_support: Optional[float],
    next_support: Optional[float],
    amount: float,
) -> list[dict]:
    """Compute add limit prices and amounts for a position type."""
    if amount <= 0 or pos_type == "LEVERAGED_ETF":
        return []

    limits = []

    if pos_type == "CORE":
        limit1 = _median3(
            nearest_support,
            ma20 * 0.995 if ma20 > 0 else None,
            current_price - 0.5 * atr if atr > 0 else None,
        )
        limit2 = _median3(
            next_support,
            ma50 * 1.005 if ma50 > 0 else None,
            current_price - 1.0 * atr if atr > 0 else None,
        )
    elif pos_type == "SEMI_CORE":
        limit1 = _median3(
            nearest_support,
            ma20 * 0.99 if ma20 > 0 else None,
            current_price - 0.6 * atr if atr > 0 else None,
        )
        limit2 = _median3(
            next_support,
            ma50 if ma50 > 0 else None,
            current_price - 1.2 * atr if atr > 0 else None,
        )
    elif pos_type == "CYCLICAL":
        limit1 = _median3(
            nearest_support,
            ma20 * 0.99 if ma20 > 0 else None,
            current_price - 0.7 * atr if atr > 0 else None,
        )
        limit2 = _median3(
            next_support,
            ma50 * 0.995 if ma50 > 0 else None,
            current_price - 1.3 * atr if atr > 0 else None,
        )
    elif pos_type == "HIGH_BETA":
        # Only one level for high beta, extreme small
        limit1 = _median3(
            nearest_support,
            current_price - 1.0 * atr if atr > 0 else None,
            current_price * 0.92,
        )
        limit2 = None
    else:
        return []

    if limit1 and limit1 > 0:
        limits.append({
            "level": 1,
            "price": round(limit1, 2),
            "amount": round(amount * 0.6, 0),
            "reason": "第一档加仓: 接近短期支撑",
        })
    if limit2 and limit2 > 0 and pos_type != "HIGH_BETA":
        limits.append({
            "level": 2,
            "price": round(limit2, 2),
            "amount": round(amount * 0.4, 0),
            "reason": "第二档加仓: 接近中期支撑",
        })

    return limits


# --------------- Invalidation Triggers ---------------

def _build_invalidation_triggers(pos_type: str, ma20: float, ma50: float) -> list[dict]:
    """Build invalidation triggers per position type."""
    triggers = []

    if pos_type == "CORE":
        if ma50 > 0:
            triggers.append({
                "trigger": f"收盘跌破MA50(${ma50:.2f})且相对强度转负",
                "action": "取消加仓计划，转入风险观察",
            })
    elif pos_type == "SEMI_CORE":
        if ma50 > 0:
            triggers.append({
                "trigger": f"收盘跌破MA50(${ma50:.2f})",
                "action": "取消加仓计划",
            })
    elif pos_type == "CYCLICAL":
        if ma50 > 0:
            triggers.append({
                "trigger": f"收盘跌破MA50(${ma50:.2f})",
                "action": "取消加仓计划",
            })
    elif pos_type == "HIGH_BETA":
        if ma20 > 0:
            triggers.append({
                "trigger": f"收盘跌破MA20(${ma20:.2f})",
                "action": "取消加仓计划",
            })

    triggers.append({
        "trigger": "跌破近期波段低点",
        "action": "不加仓",
    })
    triggers.append({
        "trigger": "板块趋势转弱",
        "action": "减少加仓金额或取消",
    })

    return triggers


# --------------- Per-Position Evaluation ---------------

def _evaluate_pullback_position(
    position: PositionInfo,
    snapshot: TickerSnapshot,
    ta: Optional[TechnicalIndicators],
    smh_ta: Optional[TechnicalIndicators],
    pos_type: str,
    portfolio: PortfolioSummary,
    global_brief: Optional[dict] = None,
) -> Optional[dict]:
    """Evaluate a single position for pullback add opportunity."""
    ticker = position.ticker
    avg_cost = position.avg_cost
    current_price = snapshot.last_price if not snapshot.data_missing else 0.0

    if current_price <= 0 and ta and ta.data_available and ta.current_price > 0:
        current_price = ta.current_price

    if current_price <= 0:
        return None

    market_value = position.shares * current_price

    # Technical data
    if not ta or not ta.data_available:
        return None

    ma20 = ta.ma20
    ma50 = ta.ma50
    ma100 = ta.ma100
    ma200 = ta.ma200
    atr = ta.atr_14
    ma50_slope = ta.ma50_slope_pct
    rs_5d = ta.rs_5d_vs_smh
    rs_20d = ta.rs_20d_vs_smh
    rs_60d = ta.rs_60d_vs_smh
    nearest_support = ta.nearest_support()
    next_support = ta.next_support()
    recent_swing_low = ta.recent_swing_low

    # Trend context
    trend_ctx = build_trend_context(ta, smh_ta)
    trend_status = trend_ctx["trendStatus"]
    breaks_swing_low = trend_ctx["breaksRecentSwingLow"]
    sector_trend = trend_ctx["sectorTrend"]

    # Exposure calculations
    account_value = portfolio.account_value if portfolio.account_value > 0 else 1
    single_exposure_pct = portfolio.single_ticker_exposure.get(ticker, 0.0)

    # Sector exposure: sum all positions in same bucket
    sector_exposure_pct = 0.0
    bucket = position.bucket or ""
    if bucket:
        sector_exposure_pct = portfolio.bucket_exposure.get(bucket, 0.0)

    # Classify pullback
    pullback_status = classify_pullback_status(
        trend_status, current_price, ma50, ma50_slope, rs_20d, breaks_swing_low, sector_trend,
    )

    # Determine action
    action = _determine_action(
        pos_type, pullback_status, trend_status, current_price, ma50,
        rs_20d, rs_5d, rs_60d, single_exposure_pct, sector_exposure_pct,
        global_brief,
    )

    # Calculate amount
    amount = _calculate_amount(
        pos_type, action, portfolio.position_pct, single_exposure_pct,
        sector_exposure_pct, global_brief,
    )

    # If amount zeroed out, force DO_NOT_ADD
    if amount <= 0 and action in ("ADD_SMALL", "ADD_NORMAL", "ADD_DEEP_ONLY"):
        action = "DO_NOT_ADD"

    # Compute add limits
    add_limits = _compute_add_limits(
        pos_type, current_price, ma20, ma50, atr, nearest_support, next_support, amount,
    ) if action in ("ADD_SMALL", "ADD_NORMAL", "ADD_DEEP_ONLY") else []

    # Invalidation triggers
    invalidation_triggers = _build_invalidation_triggers(pos_type, ma20, ma50) if add_limits else []

    # Reasoning
    reasoning = _build_reasoning(
        ticker, pos_type, action, pullback_status, trend_status,
        current_price, ma20, ma50, ma50_slope, rs_20d, rs_60d,
        breaks_swing_low, sector_trend, single_exposure_pct,
    )

    price_vs_ma50_pct = ((current_price - ma50) / ma50 * 100) if ma50 > 0 else 0.0

    return {
        "symbol": ticker,
        "type": pos_type,
        "currentPrice": round(current_price, 2),
        "averageCost": round(avg_cost, 2),
        "marketValue": round(market_value, 2),
        "singlePositionExposurePct": round(single_exposure_pct, 1),
        "sectorExposurePct": round(sector_exposure_pct, 1),
        "trendStatus": trend_status,
        "pullbackStatus": pullback_status,
        "action": action,
        "addLimits": add_limits,
        "invalidationTriggers": invalidation_triggers,
        "reasoning": reasoning,
        # Extra context for AI
        "priceVsMA50Pct": round(price_vs_ma50_pct, 2),
        "ma50SlopePct": round(ma50_slope, 3),
        "relativeStrength20dVsSMH": round(rs_20d, 2),
        "relativeStrength60dVsSMH": round(rs_60d, 2),
        "breaksRecentSwingLow": breaks_swing_low,
        "sectorTrend": sector_trend,
    }


# --------------- Action Determination ---------------

def _determine_action(
    pos_type: str,
    pullback_status: str,
    trend_status: str,
    current_price: float,
    ma50: float,
    rs_20d: float,
    rs_5d: float,
    rs_60d: float,
    single_exposure_pct: float,
    sector_exposure_pct: float,
    global_brief: Optional[dict],
) -> str:
    """Determine pullback add action per position type and pullback status."""

    # Exposure hard limits
    max_single = _MAX_SINGLE_POSITION_PCT.get(pos_type, 10)
    if single_exposure_pct >= max_single:
        return "DO_NOT_ADD"
    if sector_exposure_pct >= _SECTOR_EXPOSURE_LIMIT:
        return "DO_NOT_ADD"

    # LEVERAGED_ETF: never add
    if pos_type == "LEVERAGED_ETF":
        return "DO_NOT_ADD"

    # Reduce instead
    if pullback_status == "REDUCE_INSTEAD":
        return "REDUCE_INSTEAD"

    # Breakdown
    if pullback_status == "BREAKDOWN_DO_NOT_ADD":
        return "DO_NOT_ADD"

    # CORE
    if pos_type == "CORE":
        if pullback_status == "BUYABLE_PULLBACK":
            price_vs_ma50_pct = ((current_price - ma50) / ma50 * 100) if ma50 > 0 else 999
            if abs(price_vs_ma50_pct) <= 2 and rs_20d >= 0:
                return "ADD_NORMAL"
            return "ADD_SMALL"
        if pullback_status == "NORMAL_PULLBACK":
            return "WATCH_ONLY"
        return "WATCH_ONLY"

    # SEMI_CORE
    if pos_type == "SEMI_CORE":
        if pullback_status == "BUYABLE_PULLBACK" and rs_20d >= 0:
            return "ADD_SMALL"
        if pullback_status == "NORMAL_PULLBACK":
            return "WATCH_ONLY"
        return "WATCH_ONLY"

    # CYCLICAL
    if pos_type == "CYCLICAL":
        if pullback_status == "BUYABLE_PULLBACK" and rs_20d >= 0:
            return "ADD_SMALL"
        if pullback_status == "NORMAL_PULLBACK":
            return "WATCH_ONLY"
        return "WATCH_ONLY"

    # HIGH_BETA
    if pos_type == "HIGH_BETA":
        allow_high_beta = True
        if global_brief:
            adjustment = global_brief.get("dailyPlanAdjustment", {})
            allow_high_beta = adjustment.get("allowHighBeta", True)

        if (pullback_status == "BUYABLE_PULLBACK"
                and allow_high_beta
                and single_exposure_pct < 3):
            return "ADD_DEEP_ONLY"
        return "DO_NOT_ADD"

    return "WATCH_ONLY"


# --------------- Amount Calculation ---------------

def _calculate_amount(
    pos_type: str,
    action: str,
    total_exposure_pct: float,
    single_exposure_pct: float,
    sector_exposure_pct: float,
    global_brief: Optional[dict],
) -> float:
    """Calculate add amount based on type, exposure, and global environment."""
    if action in ("DO_NOT_ADD", "WATCH_ONLY", "REDUCE_INSTEAD"):
        return 0.0

    amount = float(_BASE_AMOUNT.get(pos_type, 0))

    # Exposure adjustment
    if total_exposure_pct > 70:
        amount = 0.0
    elif total_exposure_pct > 65:
        amount *= 0.5
    elif total_exposure_pct > 55:
        amount *= 0.7

    # Global environment adjustment
    if global_brief:
        adjustment = global_brief.get("dailyPlanAdjustment", {})
        multiplier = adjustment.get("dailyBudgetMultiplier")
        if multiplier is not None:
            amount *= multiplier
        if adjustment.get("allowHighBeta") is False and pos_type == "HIGH_BETA":
            amount = 0.0

    # Single position exposure limit
    max_single = _MAX_SINGLE_POSITION_PCT.get(pos_type, 10)
    if single_exposure_pct >= max_single:
        amount = 0.0

    # Sector exposure limit
    if sector_exposure_pct >= _SECTOR_EXPOSURE_LIMIT:
        amount = 0.0

    return amount


# --------------- Reasoning Builder ---------------

def _build_reasoning(
    ticker: str,
    pos_type: str,
    action: str,
    pullback_status: str,
    trend_status: str,
    current_price: float,
    ma20: float,
    ma50: float,
    ma50_slope: float,
    rs_20d: float,
    rs_60d: float,
    breaks_swing_low: bool,
    sector_trend: str,
    single_exposure_pct: float,
) -> list[str]:
    """Build human-readable reasoning list."""
    reasons = []

    # Trend context
    trend_labels = {
        "STRONG_UPTREND": "强势上升趋势",
        "PULLBACK_IN_UPTREND": "上升趋势回调",
        "SHORT_TERM_BREAK_ONLY": "仅短期走弱",
        "MEDIUM_TREND_BREAK": "中期趋势破位",
        "LONG_TREND_BREAK": "长期趋势破位",
        "RELATIVE_UNDERPERFORMER": "持续弱于大盘",
    }
    reasons.append(f"趋势状态: {trend_labels.get(trend_status, trend_status)}")

    # Pullback classification
    pullback_labels = {
        "BUYABLE_PULLBACK": "可买入回调",
        "NORMAL_PULLBACK": "正常回调",
        "WATCH_ONLY": "观察中",
        "BREAKDOWN_DO_NOT_ADD": "破位不加仓",
        "REDUCE_INSTEAD": "应减仓而非加仓",
    }
    reasons.append(f"回调类型: {pullback_labels.get(pullback_status, pullback_status)}")

    # MA context
    if ma50 > 0:
        if current_price > ma50:
            pct = (current_price - ma50) / ma50 * 100
            reasons.append(f"价格在MA50上方{pct:.1f}%")
        else:
            pct = (ma50 - current_price) / ma50 * 100
            reasons.append(f"价格在MA50下方{pct:.1f}%")

    if ma50_slope > 0:
        reasons.append(f"MA50斜率+{ma50_slope:.2f}%(上升)")
    elif ma50_slope < 0:
        reasons.append(f"MA50斜率{ma50_slope:.2f}%(下降)")

    # RS
    if rs_20d >= 0:
        reasons.append(f"20日相对强度{rs_20d:+.1f}%(强于SMH)")
    else:
        reasons.append(f"20日相对强度{rs_20d:+.1f}%(弱于SMH)")

    # Swing low
    if breaks_swing_low:
        reasons.append("已跌破近期波段低点")

    # Sector
    sector_labels = {"STRONG": "强势", "NEUTRAL": "中性", "PULLBACK": "回调", "WEAK": "弱势"}
    reasons.append(f"板块趋势: {sector_labels.get(sector_trend, sector_trend)}")

    # Exposure warnings
    max_single = _MAX_SINGLE_POSITION_PCT.get(pos_type, 10)
    if single_exposure_pct >= max_single:
        reasons.append(f"单仓暴露{single_exposure_pct:.1f}%已达上限{max_single}%")

    # Action-specific
    if action == "DO_NOT_ADD":
        if pullback_status == "BREAKDOWN_DO_NOT_ADD":
            reasons.append("不应在破位时加仓摊平")
        elif single_exposure_pct >= max_single:
            reasons.append("仓位已满，不宜加仓")
    elif action == "REDUCE_INSTEAD":
        reasons.append("趋势已破坏，应考虑减仓而非加仓")
    elif action in ("ADD_SMALL", "ADD_NORMAL"):
        reasons.append("中期趋势完好，回调可加仓")
    elif action == "ADD_DEEP_ONLY":
        reasons.append("仅在深度回调时少量加仓")

    return reasons


# --------------- Main Entry Point ---------------

def generate_pullback_add_plan(
    portfolio: PortfolioSummary,
    snapshots: dict[str, TickerSnapshot],
    ta_results: dict[str, TechnicalIndicators],
    watchlist: dict,
    global_brief: Optional[dict] = None,
) -> dict:
    """Generate pullback add plan for all current positions.

    Returns structured response with portfolio context, summary, and per-position plans.
    """
    smh_ta = ta_results.get("SMH")

    plans = []
    action_counts = {
        "ADD_SMALL": 0, "ADD_NORMAL": 0, "ADD_DEEP_ONLY": 0,
        "WATCH_ONLY": 0, "DO_NOT_ADD": 0, "REDUCE_INSTEAD": 0,
    }
    total_suggested_amount = 0.0

    for pos in portfolio.positions:
        if pos.shares <= 0:
            continue

        snapshot = snapshots.get(pos.ticker)
        if not snapshot:
            continue

        ta = ta_results.get(pos.ticker)
        pos_type = classify_position_type(pos.ticker, watchlist)

        plan = _evaluate_pullback_position(
            pos, snapshot, ta, smh_ta, pos_type, portfolio, global_brief,
        )
        if plan is None:
            continue

        plans.append(plan)
        action = plan["action"]
        action_counts[action] = action_counts.get(action, 0) + 1

        for limit in plan.get("addLimits", []):
            total_suggested_amount += limit.get("amount", 0)

    # Determine portfolio risk level
    exposure_pct = portfolio.position_pct
    if exposure_pct > 75:
        risk_level = "HIGH"
    elif exposure_pct > 65:
        risk_level = "ELEVATED"
    elif exposure_pct > 50:
        risk_level = "MODERATE"
    else:
        risk_level = "LOW"

    # Sort: ADD_NORMAL first, then ADD_SMALL, ADD_DEEP_ONLY, WATCH_ONLY, DO_NOT_ADD, REDUCE_INSTEAD
    action_order = {
        "ADD_NORMAL": 0, "ADD_SMALL": 1, "ADD_DEEP_ONLY": 2,
        "WATCH_ONLY": 3, "DO_NOT_ADD": 4, "REDUCE_INSTEAD": 5,
    }
    plans.sort(key=lambda p: (action_order.get(p["action"], 5), -abs(p.get("priceVsMA50Pct", 0))))

    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "portfolioContext": {
            "accountValue": round(portfolio.account_value, 2),
            "totalExposurePct": round(exposure_pct, 1),
            "cash": round(portfolio.cash, 2),
            "riskLevel": risk_level,
        },
        "summary": {
            "addSmallCount": action_counts.get("ADD_SMALL", 0),
            "addNormalCount": action_counts.get("ADD_NORMAL", 0),
            "addDeepOnlyCount": action_counts.get("ADD_DEEP_ONLY", 0),
            "watchOnlyCount": action_counts.get("WATCH_ONLY", 0),
            "doNotAddCount": action_counts.get("DO_NOT_ADD", 0),
            "reduceInsteadCount": action_counts.get("REDUCE_INSTEAD", 0),
            "totalSuggestedAddAmount": round(total_suggested_amount, 0),
        },
        "plans": plans,
    }
