"""Exit plan engine — generates hold/trim/exit recommendations for existing positions.

Complements the daily-plan (buy decisions) with sell/risk management decisions.
Each position is evaluated through a priority chain of rules, with thresholds
varying by position type (CORE gets more room, HIGH_BETA/LEVERAGED tighter).
"""

import logging
from typing import Optional

from app.core.models import PortfolioSummary, PositionInfo, TickerSnapshot
from app.core.technical_analysis import TechnicalIndicators
from app.core.stock_scorer import TICKER_CATEGORY

logger = logging.getLogger(__name__)

# --------------- Position type classification ---------------

# Map watchlist role → exit position type
_ROLE_TO_TYPE = {
    "core": "CORE",
    "semi_core": "SEMI_CORE",
    "cyclical": "CYCLICAL",
    "high_beta": "HIGH_BETA",
    "beta": "SEMI_CORE",
    "leveraged": "LEVERAGED_ETF",
}

# Override per ticker (mirrors stock_scorer.TICKER_CATEGORY but mapped to exit types)
_TICKER_TYPE_OVERRIDE = {
    # Explicitly cyclical
    "MU": "CYCLICAL", "SNDK": "CYCLICAL", "AAOI": "CYCLICAL",
    # Leveraged ETFs
    "RAM": "LEVERAGED_ETF",
}


def classify_position_type(ticker: str, watchlist: dict) -> str:
    """Determine exit position type for a ticker.

    Priority: _TICKER_TYPE_OVERRIDE > TICKER_CATEGORY mapping > watchlist role > default.
    """
    if ticker in _TICKER_TYPE_OVERRIDE:
        return _TICKER_TYPE_OVERRIDE[ticker]

    # Map stock_scorer category to exit type
    cat = TICKER_CATEGORY.get(ticker)
    if cat:
        return _ROLE_TO_TYPE.get(cat, "SEMI_CORE")

    # Fall back to watchlist bucket role
    for _bname, bdata in watchlist.get("buckets", {}).items():
        if ticker in bdata.get("tickers", []):
            role = bdata.get("role", "beta")
            return _ROLE_TO_TYPE.get(role, "SEMI_CORE")

    return "SEMI_CORE"


# --------------- Thresholds by position type ---------------

THRESHOLDS = {
    "CORE": {
        "profit_1_pct": 15, "profit_2_pct": 25,
        "max_loss_pct": -12,
        "trailing_stop_pct": -10,
        "ma20_days_trim": 2,
        "rsi_trim": 80, "rsi_gain_min": 15,
    },
    "SEMI_CORE": {
        "profit_1_pct": 10, "profit_2_pct": 18,
        "max_loss_pct": -10,
        "trailing_stop_pct": -8,
        "ma20_days_trim": 2,
        "rsi_trim": 75, "rsi_gain_min": 10,
    },
    "CYCLICAL": {
        "profit_1_pct": 12, "profit_2_pct": 20,
        "max_loss_pct": -10,
        "trailing_stop_pct": -8,
        "ma20_days_trim": 2,
        "rsi_trim": 75, "rsi_gain_min": 0,
    },
    "HIGH_BETA": {
        "profit_1_pct": 8, "profit_2_pct": 15,
        "max_loss_pct": -8,
        "trailing_stop_pct": -6,
        "ma20_days_trim": 1,  # tighter: trim on first close below MA20
        "rsi_trim": 75, "rsi_gain_min": 0,
    },
    "LEVERAGED_ETF": {
        "profit_1_pct": 6, "profit_2_pct": 10,
        "max_loss_pct": -5,
        "trailing_stop_pct": -4,
        "ma20_days_trim": 0,  # exit on any close below MA20
        "rsi_trim": 70, "rsi_gain_min": 0,
    },
}


# --------------- Core evaluation logic ---------------

def _evaluate_position(
    position: PositionInfo,
    snapshot: TickerSnapshot,
    ta: Optional[TechnicalIndicators],
    smh_snapshot: Optional[TickerSnapshot],
    pos_type: str,
    portfolio: PortfolioSummary,
) -> dict:
    """Evaluate a single position and return exit plan dict."""
    ticker = position.ticker
    avg_cost = position.avg_cost
    shares = position.shares
    current_price = snapshot.last_price if not snapshot.data_missing else 0.0

    # Use TA price as fallback (weekends/after-hours)
    if current_price <= 0 and ta and ta.data_available and ta.current_price > 0:
        current_price = ta.current_price

    market_value = shares * current_price if current_price > 0 else position.current_value
    gain_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 and current_price > 0 else 0.0

    th = THRESHOLDS.get(pos_type, THRESHOLDS["SEMI_CORE"])

    # Technical data
    ma20 = ta.ma20 if ta and ta.data_available else 0.0
    ma50 = ta.ma50 if ta and ta.data_available else 0.0
    rsi = ta.rsi_14 if ta and ta.data_available else 50.0
    atr = ta.atr_14 if ta and ta.data_available else 0.0
    days_below_ma20 = ta.days_below_ma20 if ta and ta.data_available else 0
    days_below_ma50 = ta.days_below_ma50 if ta and ta.data_available else 0
    nearest_support = ta.nearest_support() if ta and ta.data_available else None
    nearest_resistance = ta.nearest_resistance() if ta and ta.data_available else None
    second_resistance = ta.second_resistance() if ta and ta.data_available else None
    swing_high = ta.swing_high if ta and ta.data_available else 0.0
    macd_hist = ta.macd_hist if ta and ta.data_available else 0.0

    # Relative strength vs SMH
    rs_vs_smh = 0.0
    if smh_snapshot and not smh_snapshot.data_missing and smh_snapshot.prev_close > 0:
        smh_return = smh_snapshot.pct_change_from_prev_close
        stock_return = snapshot.pct_change_from_prev_close if not snapshot.data_missing else 0.0
        rs_vs_smh = round(stock_return - smh_return, 2)

    # Drawdown from swing high (proxy for highest close since entry)
    drawdown_from_high_pct = 0.0
    if swing_high > 0 and current_price > 0:
        drawdown_from_high_pct = (current_price - swing_high) / swing_high * 100

    # Distance to support/resistance
    dist_to_support_pct = ((current_price - nearest_support) / current_price * 100) if nearest_support and current_price > 0 else None
    dist_to_resistance_pct = ((nearest_resistance - current_price) / current_price * 100) if nearest_resistance and current_price > 0 else None

    # --- Priority-based action evaluation ---
    action = "HOLD"
    confidence = "MEDIUM"
    reasoning = []
    trim_plan = []
    risk_plan = []

    # ① Hard stop-loss
    if gain_pct <= th["max_loss_pct"]:
        if pos_type in ("HIGH_BETA", "LEVERAGED_ETF"):
            action = "EXIT"
            confidence = "HIGH"
            reasoning.append(f"亏损{gain_pct:.1f}%已超过止损线{th['max_loss_pct']}%")
        elif pos_type == "CORE" and ma50 > 0 and current_price < ma50:
            action = "EXIT"
            confidence = "HIGH"
            reasoning.append(f"亏损{gain_pct:.1f}%超止损线且跌破MA50")
        else:
            action = "TRIM_1_2"
            confidence = "HIGH"
            reasoning.append(f"亏损{gain_pct:.1f}%接近止损线{th['max_loss_pct']}%")

    # ② MA50 breakdown
    elif ma50 > 0 and current_price > 0 and current_price < ma50:
        if pos_type in ("CORE", "SEMI_CORE"):
            action = "TRIM_1_2"
            confidence = "HIGH"
            reasoning.append(f"价格${current_price:.2f}跌破MA50(${ma50:.2f})")
        else:
            action = "EXIT"
            confidence = "HIGH"
            reasoning.append(f"价格${current_price:.2f}跌破MA50(${ma50:.2f})")

    # ③ Consecutive MA20 breakdown
    elif days_below_ma20 >= max(1, th["ma20_days_trim"]):
        if pos_type == "LEVERAGED_ETF":
            action = "EXIT"
            confidence = "HIGH"
            reasoning.append(f"收盘价连续{days_below_ma20}天低于MA20")
        elif pos_type == "HIGH_BETA":
            if days_below_ma20 >= 2:
                action = "EXIT"
                confidence = "HIGH"
            else:
                action = "TRIM_1_2"
                confidence = "MEDIUM"
            reasoning.append(f"收盘价连续{days_below_ma20}天低于MA20")
        elif pos_type == "CORE":
            action = "TRIM_1_3"
            confidence = "MEDIUM"
            reasoning.append(f"收盘价连续{days_below_ma20}天低于MA20，核心仓位先减1/3")
        else:
            # SEMI_CORE, CYCLICAL
            if rs_vs_smh < 0:
                action = "TRIM_1_2"
                reasoning.append(f"连续{days_below_ma20}天低于MA20且弱于SMH")
            else:
                action = "TRIM_1_3"
                reasoning.append(f"连续{days_below_ma20}天低于MA20")
            confidence = "MEDIUM"

    # ④ Trailing profit protection
    elif gain_pct >= 10 and drawdown_from_high_pct <= th["trailing_stop_pct"]:
        if pos_type in ("HIGH_BETA", "LEVERAGED_ETF"):
            action = "TRIM_1_2"
        else:
            action = "TRIM_1_3"
        confidence = "MEDIUM"
        reasoning.append(f"盈利{gain_pct:.1f}%但从高点回撤{drawdown_from_high_pct:.1f}%触发追踪止盈")

    # ⑤ Resistance-based profit taking
    elif dist_to_resistance_pct is not None and dist_to_resistance_pct <= 2:
        should_trim = False
        if pos_type == "CORE":
            should_trim = gain_pct >= 8 or rsi > 70
        elif pos_type in ("HIGH_BETA", "LEVERAGED_ETF"):
            should_trim = True
        else:
            should_trim = gain_pct >= 5

        if should_trim:
            action = "TRIM_1_3" if pos_type not in ("HIGH_BETA", "LEVERAGED_ETF") else "TRIM_1_2"
            confidence = "MEDIUM"
            reasoning.append(f"价格接近阻力位${nearest_resistance:.2f}(距离{dist_to_resistance_pct:.1f}%)")

    # ⑥ Fixed gain profit taking (tier 1)
    elif gain_pct >= th["profit_2_pct"]:
        action = "TRIM_1_3"
        confidence = "MEDIUM"
        reasoning.append(f"盈利{gain_pct:.1f}%达到第二止盈目标{th['profit_2_pct']}%")

    elif gain_pct >= th["profit_1_pct"]:
        action = "TRIM_1_3"
        confidence = "LOW"
        reasoning.append(f"盈利{gain_pct:.1f}%达到第一止盈目标{th['profit_1_pct']}%")

    # ⑦ RSI overbought confirmation
    elif rsi >= th["rsi_trim"] and gain_pct >= th["rsi_gain_min"]:
        action = "TRIM_1_3" if pos_type in ("CORE", "SEMI_CORE") else "TRIM_1_2"
        confidence = "LOW"
        reasoning.append(f"RSI={rsi:.0f}过热" + (f"且盈利{gain_pct:.1f}%" if gain_pct > 0 else ""))

    # ⑧ Default: HOLD or WATCH
    else:
        # Check if close to any trigger
        if gain_pct > 0 and dist_to_resistance_pct is not None and dist_to_resistance_pct <= 5:
            action = "WATCH"
            reasoning.append(f"盈利{gain_pct:.1f}%，接近阻力位(距离{dist_to_resistance_pct:.1f}%)")
        elif gain_pct < 0 and days_below_ma20 >= 1:
            action = "WATCH"
            reasoning.append(f"亏损{gain_pct:.1f}%且收盘低于MA20，需关注")
        elif gain_pct < th["max_loss_pct"] * 0.6:
            action = "WATCH"
            reasoning.append(f"亏损{gain_pct:.1f}%接近止损线")
        else:
            action = "HOLD"
            if gain_pct > 0:
                reasoning.append(f"盈利{gain_pct:.1f}%，趋势完好")
            elif gain_pct > -3:
                reasoning.append("持仓正常，未触发任何信号")
            else:
                reasoning.append(f"亏损{gain_pct:.1f}%但未触发止损")

    # MACD bearish cross as confirmation (increase confidence if aligned)
    if macd_hist < 0 and action in ("TRIM_1_3", "TRIM_1_2", "WATCH"):
        if "MACD" not in " ".join(reasoning):
            reasoning.append("MACD空头排列确认")
        if confidence == "LOW":
            confidence = "MEDIUM"

    # Relative strength note
    if rs_vs_smh < -2 and action in ("TRIM_1_3", "TRIM_1_2", "REDUCE_2_3", "EXIT"):
        reasoning.append(f"弱于SMH({rs_vs_smh:+.1f}%)")

    # --- Build trim plan (future triggers) ---
    if action == "HOLD" or action == "WATCH":
        # Show what would trigger a trim
        if nearest_resistance and current_price > 0:
            trim_price = nearest_resistance * 0.98
            trim_plan.append({
                "trigger": f"价格 >= ${trim_price:.2f} (阻力位98%)" + (f" 且盈利>={th['profit_1_pct']}%" if pos_type == "CORE" else ""),
                "price": round(trim_price, 2),
                "action": "TRIM_1_3",
            })
        if gain_pct < th["profit_1_pct"]:
            profit_target = avg_cost * (1 + th["profit_1_pct"] / 100)
            trim_plan.append({
                "trigger": f"盈利 >= {th['profit_1_pct']}%",
                "price": round(profit_target, 2),
                "action": "TRIM_1_3",
            })

    # --- Build risk plan (stop triggers) ---
    if ma20 > 0:
        risk_plan.append({
            "trigger": f"连续{th['ma20_days_trim']}天收盘低于MA20(${ma20:.2f})",
            "price": round(ma20, 2),
            "action": "TRIM_1_2" if pos_type in ("CORE", "SEMI_CORE") else "EXIT",
        })
    if ma50 > 0:
        risk_plan.append({
            "trigger": f"收盘跌破MA50(${ma50:.2f})",
            "price": round(ma50, 2),
            "action": "TRIM_1_2" if pos_type == "CORE" else "EXIT",
        })
    stop_price = avg_cost * (1 + th["max_loss_pct"] / 100)
    risk_plan.append({
        "trigger": f"亏损超过{th['max_loss_pct']}%",
        "price": round(stop_price, 2),
        "action": "EXIT" if pos_type in ("HIGH_BETA", "LEVERAGED_ETF") else "TRIM_1_2",
    })

    return {
        "ticker": ticker,
        "type": pos_type,
        "shares": shares,
        "averageCost": round(avg_cost, 2),
        "currentPrice": round(current_price, 2),
        "marketValue": round(market_value, 2),
        "gainPct": round(gain_pct, 2),
        "ma20": round(ma20, 2),
        "ma50": round(ma50, 2),
        "daysBelowMA20": days_below_ma20,
        "daysBelowMA50": days_below_ma50,
        "nearestSupport": round(nearest_support, 2) if nearest_support else None,
        "nearestResistance": round(nearest_resistance, 2) if nearest_resistance else None,
        "distanceToResistancePct": round(dist_to_resistance_pct, 2) if dist_to_resistance_pct is not None else None,
        "rsi": round(rsi, 1),
        "atr": round(atr, 2),
        "relativeStrengthVsSMH": rs_vs_smh,
        "swingHigh": round(swing_high, 2),
        "drawdownFromHighPct": round(drawdown_from_high_pct, 2),
        "action": action,
        "confidence": confidence,
        "trimPlan": trim_plan,
        "riskPlan": risk_plan,
        "reasoning": reasoning,
    }


# --------------- Portfolio-level risk ---------------

def _portfolio_risk(portfolio: PortfolioSummary) -> dict:
    """Evaluate portfolio-level risk metrics."""
    account_value = portfolio.account_value or 1
    total_pos = portfolio.invested_value
    cash = portfolio.cash
    equity_pct = portfolio.position_pct

    if equity_pct > 75:
        risk_level = "HIGH"
    elif equity_pct > 65:
        risk_level = "ELEVATED"
    elif equity_pct > 50:
        risk_level = "MODERATE"
    else:
        risk_level = "NORMAL"

    return {
        "accountValue": round(account_value, 2),
        "totalPositionValue": round(total_pos, 2),
        "cash": round(cash, 2),
        "equityExposurePct": round(equity_pct, 1),
        "riskLevel": risk_level,
    }


# --------------- Main entry point ---------------

def generate_exit_plan(
    portfolio: PortfolioSummary,
    snapshots: dict[str, TickerSnapshot],
    ta_results: dict[str, TechnicalIndicators],
    watchlist: dict,
    market_regime: str = "neutral",
) -> dict:
    """Generate exit plan for all current positions.

    Returns structured dict with portfolio risk summary and per-position exit plans.
    """
    smh_snapshot = snapshots.get("SMH")

    exit_plans = []
    action_counts = {"HOLD": 0, "WATCH": 0, "TRIM": 0, "EXIT": 0}

    for pos in portfolio.positions:
        ticker = pos.ticker
        if pos.shares <= 0:
            continue

        snapshot = snapshots.get(ticker)
        if not snapshot:
            # No market data, skip
            continue

        ta = ta_results.get(ticker)
        pos_type = classify_position_type(ticker, watchlist)

        plan = _evaluate_position(pos, snapshot, ta, smh_snapshot, pos_type, portfolio)

        # Adjust for high portfolio exposure: be more aggressive with trimming
        port_risk = portfolio.position_pct
        if port_risk > 70 and plan["action"] == "HOLD" and plan["gainPct"] > 5:
            plan["action"] = "WATCH"
            plan["reasoning"].append(f"总仓位{port_risk:.0f}%偏高，建议关注止盈机会")

        exit_plans.append(plan)

        # Count actions
        act = plan["action"]
        if act == "HOLD":
            action_counts["HOLD"] += 1
        elif act == "WATCH":
            action_counts["WATCH"] += 1
        elif act == "EXIT":
            action_counts["EXIT"] += 1
        else:
            action_counts["TRIM"] += 1

    # Sort: EXIT first, then TRIM, WATCH, HOLD
    action_order = {"EXIT": 0, "REDUCE_2_3": 1, "TRIM_1_2": 2, "TRIM_1_3": 3, "WATCH": 4, "HOLD": 5}
    exit_plans.sort(key=lambda p: (action_order.get(p["action"], 5), -abs(p["gainPct"])))

    return {
        "marketRegime": market_regime,
        "portfolioRisk": _portfolio_risk(portfolio),
        "summary": {
            "holdCount": action_counts["HOLD"],
            "watchCount": action_counts["WATCH"],
            "trimCount": action_counts["TRIM"],
            "exitCount": action_counts["EXIT"],
            "totalPositions": len(exit_plans),
        },
        "exitPlans": exit_plans,
    }
