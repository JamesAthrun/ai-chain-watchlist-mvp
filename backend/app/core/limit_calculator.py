"""Limit price and order amount calculator.

Implements the 3-method median approach from ai_watchlist_limit_system_guide.md:
  Method 1: Support-based limit (near support/fib level)
  Method 2: Percentage-based limit (category-specific discount from close)
  Method 3: ATR-based limit (price - N * ATR by category)

Final limit = median(method1, method2, method3)
Two tiers: limit_1 (shallow, higher fill probability) and limit_2 (deep, better price)

Amount calculation:
  amount = base * market_multiplier * stock_multiplier * position_multiplier
"""

import logging
import statistics
from typing import Optional

from app.core.models import PortfolioSummary, TickerSnapshot
from app.core.technical_analysis import TechnicalIndicators

logger = logging.getLogger(__name__)

# Percentage discounts from close by category [shallow, deep]
PERCENT_DISCOUNT = {
    "core": (0.015, 0.030),        # 1.5%, 3.0%
    "semi_core": (0.025, 0.050),   # 2.5%, 5.0%
    "cyclical": (0.035, 0.065),    # 3.5%, 6.5%
    "high_beta": (0.050, 0.100),   # 5.0%, 10.0%
    "beta": (0.030, 0.060),        # 3.0%, 6.0%
    "leveraged": (0.060, 0.120),   # 6.0%, 12.0%
}

# ATR multiples by category [shallow, deep]
ATR_MULTIPLES = {
    "core": (1.0, 1.8),
    "semi_core": (1.2, 2.2),
    "cyclical": (1.5, 2.5),
    "high_beta": (1.8, 3.0),
    "beta": (1.3, 2.3),
    "leveraged": (2.0, 3.5),
}

# Fibonacci level used as support by category
FIB_PREFERENCE = {
    "core": "fib_382",
    "semi_core": "fib_500",
    "cyclical": "fib_500",
    "high_beta": "fib_618",
    "beta": "fib_500",
    "leveraged": "fib_618",
}

# Market regime multipliers for amount
MARKET_MULTIPLIERS = {
    "strong": 1.2,
    "neutral": 1.0,
    "weak": 0.6,
    "very_weak": 0.3,
}

# Base order amount by category (% of account)
BASE_AMOUNT_PCT = {
    "core": 0.06,        # 6% = $2400 on $40k
    "semi_core": 0.04,   # 4%
    "cyclical": 0.03,    # 3%
    "high_beta": 0.02,   # 2%
    "beta": 0.03,        # 3%
    "leveraged": 0.015,  # 1.5%
}

# Max candidates per day by category
MAX_CANDIDATES = {
    "core": 2,
    "semi_core": 2,
    "cyclical": 1,
    "high_beta": 1,
    "beta": 1,
    "leveraged": 0,
}


def calculate_limit_prices(
    ticker: str,
    category: str,
    current_price: float,
    ta: Optional[TechnicalIndicators],
) -> dict:
    """Calculate 2-tier limit prices using 3-method median.

    Returns:
        {
            "limit_1": float,  # shallow (higher probability fill)
            "limit_2": float,  # deep (better price)
            "methods": {
                "support": (l1, l2),
                "percent": (l1, l2),
                "atr": (l1, l2),
            },
            "reason": str,
        }
    """
    if current_price <= 0:
        return {"limit_1": 0, "limit_2": 0, "methods": {}, "reason": "无价格数据"}

    # -- Method 1: Support-based --
    support_l1 = 0.0
    support_l2 = 0.0
    if ta and ta.data_available:
        # Shallow: nearest support or preferred fib level
        nearest_sup = ta.nearest_support()
        fib_pref = FIB_PREFERENCE.get(category, "fib_500")
        fib_val = getattr(ta, fib_pref, 0.0)

        if nearest_sup and nearest_sup > 0 and nearest_sup < current_price:
            support_l1 = nearest_sup
        elif fib_val > 0 and fib_val < current_price:
            support_l1 = fib_val
        else:
            support_l1 = current_price * (1 - PERCENT_DISCOUNT.get(category, (0.03, 0.06))[0])

        # Deep: next support or deeper fib level
        next_sup = ta.next_support()
        if next_sup and next_sup > 0 and next_sup < support_l1:
            support_l2 = next_sup
        elif ta.fib_618 > 0 and ta.fib_618 < support_l1:
            support_l2 = ta.fib_618
        else:
            support_l2 = support_l1 * 0.97  # additional 3% below l1
    else:
        # No TA data, skip support method
        support_l1 = current_price * 0.97
        support_l2 = current_price * 0.94

    # -- Method 2: Percentage-based --
    pct = PERCENT_DISCOUNT.get(category, (0.03, 0.06))
    percent_l1 = current_price * (1 - pct[0])
    percent_l2 = current_price * (1 - pct[1])

    # -- Method 3: ATR-based --
    atr_mult = ATR_MULTIPLES.get(category, (1.3, 2.3))
    atr = ta.atr_14 if ta and ta.data_available else current_price * 0.02
    atr_l1 = current_price - atr * atr_mult[0]
    atr_l2 = current_price - atr * atr_mult[1]

    # -- Final: median of 3 methods --
    limit_1 = round(statistics.median([support_l1, percent_l1, atr_l1]), 2)
    limit_2 = round(statistics.median([support_l2, percent_l2, atr_l2]), 2)

    # Sanity: limit_2 should be below limit_1
    if limit_2 > limit_1:
        limit_2 = limit_1 * 0.97

    # Don't place limits too far away (cap at 15% below current)
    floor = current_price * 0.85
    limit_1 = max(limit_1, floor)
    limit_2 = max(limit_2, floor)

    reason_parts = []
    if support_l1 == limit_1:
        reason_parts.append("支撑位挂单")
    elif percent_l1 == limit_1:
        reason_parts.append("百分比折扣")
    elif atr_l1 == limit_1:
        reason_parts.append("ATR波动")
    reason = "三法中位数 (" + ", ".join(reason_parts) + ")" if reason_parts else "三法中位数"

    return {
        "limit_1": limit_1,
        "limit_2": limit_2,
        "methods": {
            "support": (round(support_l1, 2), round(support_l2, 2)),
            "percent": (round(percent_l1, 2), round(percent_l2, 2)),
            "atr": (round(atr_l1, 2), round(atr_l2, 2)),
        },
        "reason": reason,
    }


def calculate_order_amount(
    ticker: str,
    category: str,
    market_regime: str,
    score: float,
    account_value: float,
    portfolio: Optional[PortfolioSummary] = None,
) -> dict:
    """Calculate order dollar amount with all multipliers and constraints.

    Returns:
        {
            "amount_l1": float,  # dollars for limit_1 tier
            "amount_l2": float,  # dollars for limit_2 tier (smaller, speculative)
            "base": float,
            "multipliers": {market, stock, position},
            "capped_reason": str | None,
        }
    """
    base_pct = BASE_AMOUNT_PCT.get(category, 0.03)
    base = account_value * base_pct

    # Market multiplier
    market_mult = MARKET_MULTIPLIERS.get(market_regime, 1.0)

    # Stock multiplier (from score)
    if score >= 80:
        stock_mult = 1.3
    elif score >= 65:
        stock_mult = 1.0
    elif score >= 50:
        stock_mult = 0.6
    else:
        stock_mult = 0.0

    # Position multiplier (reduce if already heavy)
    position_mult = 1.0
    capped_reason = None
    if portfolio:
        # single_ticker_exposure values are percentages (e.g. 12.5 = 12.5%)
        ticker_exp_pct = portfolio.single_ticker_exposure.get(ticker, 0.0)
        # Max single position by category (in percentage points)
        max_single_pct = {"core": 15, "semi_core": 10, "high_beta": 5,
                          "cyclical": 10, "beta": 8, "leveraged": 2}
        max_pct = max_single_pct.get(category, 10)
        remaining_room_pct = max(0, max_pct - ticker_exp_pct)
        max_add = remaining_room_pct / 100 * account_value

        if remaining_room_pct <= 0:
            position_mult = 0.0
            capped_reason = f"已满仓({ticker_exp_pct:.0f}%)"
        elif ticker_exp_pct > max_pct * 0.5:
            position_mult = 0.5
            capped_reason = f"接近上限({ticker_exp_pct:.0f}%/{max_pct:.0f}%)"

    raw_amount = base * market_mult * stock_mult * position_mult

    # Cap: single order <= 5% of account
    max_single_order = account_value * 0.05
    if raw_amount > max_single_order:
        raw_amount = max_single_order
        capped_reason = capped_reason or "单笔上限"

    # l2 tier gets 60% of l1 amount (speculative, smaller size)
    amount_l1 = round(raw_amount, 0)
    amount_l2 = round(raw_amount * 0.6, 0)

    return {
        "amount_l1": amount_l1,
        "amount_l2": amount_l2,
        "base": round(base, 0),
        "multipliers": {
            "market": market_mult,
            "stock": stock_mult,
            "position": position_mult,
        },
        "capped_reason": capped_reason,
    }


def generate_daily_limits(
    scored_stocks: list[dict],
    ta_results: dict[str, TechnicalIndicators],
    snapshots: dict[str, TickerSnapshot],
    market_regime: str,
    account_value: float,
    portfolio: Optional[PortfolioSummary] = None,
    max_daily_pct: float = 0.30,
) -> list[dict]:
    """Generate daily limit order plan from scored stocks.

    Applies candidate count limits and daily total cap.
    Returns list of limit order recommendations sorted by score.
    """
    candidates = [s for s in scored_stocks if s["action"] in ("preferred_buy", "buy_candidate")]

    # Enforce per-category max candidates
    category_counts = {}
    selected = []
    for c in candidates:
        cat = c["category"]
        count = category_counts.get(cat, 0)
        max_n = MAX_CANDIDATES.get(cat, 1)
        if count < max_n:
            selected.append(c)
            category_counts[cat] = count + 1

    # Max 4 total per day
    selected = selected[:4]

    # Calculate limits and amounts
    max_daily_amount = account_value * max_daily_pct
    total_amount = 0.0
    orders = []

    for stock in selected:
        ticker = stock["ticker"]
        category = stock["category"]
        snap = snapshots.get(ticker)
        ta = ta_results.get(ticker)

        # Get current price
        price = 0.0
        if ta and ta.data_available:
            price = ta.current_price
        elif snap and snap.last_price > 0:
            price = snap.last_price

        if price <= 0:
            continue

        # Calculate limit prices
        limits = calculate_limit_prices(ticker, category, price, ta)

        # Calculate amounts
        amounts = calculate_order_amount(
            ticker, category, market_regime, stock["score"],
            account_value, portfolio
        )

        # Check daily cap
        if total_amount + amounts["amount_l1"] > max_daily_amount:
            remaining = max_daily_amount - total_amount
            if remaining < 200:  # too small to be useful
                break
            amounts["amount_l1"] = remaining
            amounts["amount_l2"] = round(remaining * 0.6, 0)
            amounts["capped_reason"] = (amounts["capped_reason"] or "") + " 日总量上限"

        total_amount += amounts["amount_l1"]

        orders.append({
            "ticker": ticker,
            "score": stock["score"],
            "category": category,
            "chain": stock["chain"],
            "action": stock["action"],
            "reasons": stock["reasons"],
            "current_price": round(price, 2),
            "limit_1": limits["limit_1"],
            "limit_2": limits["limit_2"],
            "limit_methods": limits["methods"],
            "limit_reason": limits["reason"],
            "amount_l1": amounts["amount_l1"],
            "amount_l2": amounts["amount_l2"],
            "amount_multipliers": amounts["multipliers"],
            "capped_reason": amounts["capped_reason"],
        })

    return orders
