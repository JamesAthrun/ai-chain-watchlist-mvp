"""Conflict detector — identifies contradictions between engine signals.

Checks for scenarios like:
- Daily plan suggests buying a symbol that exit-plan flags for trimming
- Pullback-add on a symbol in cooldown or with active exit signal
- Sector overexposure when buying adds to already-heavy sector
- Recently sold/trimmed symbol appearing in buy suggestions
"""

import logging
from typing import Optional

from app.core.models import (
    ConflictSeverity,
    ConflictType,
    DecisionConflict,
)

logger = logging.getLogger(__name__)


def detect_conflicts(
    daily_plan: Optional[dict] = None,
    exit_plan: Optional[dict] = None,
    pullback_plan: Optional[dict] = None,
    trade_contexts: Optional[dict] = None,
    portfolio_summary: Optional[object] = None,
) -> list[DecisionConflict]:
    """Detect conflicts across engine outputs.

    Args:
        daily_plan: Response from /api/daily-plan
        exit_plan: Response from /api/exit-plan
        pullback_plan: Response from /api/pullback-add-plan
        trade_contexts: Dict of symbol -> TradeHistoryContext
        portfolio_summary: PortfolioSummary object

    Returns:
        List of detected conflicts, sorted by severity (HIGH first).
    """
    conflicts = []

    if daily_plan and exit_plan:
        conflicts.extend(_check_buy_vs_exit(daily_plan, exit_plan))

    if pullback_plan and exit_plan:
        conflicts.extend(_check_pullback_vs_exit(pullback_plan, exit_plan))

    if daily_plan and trade_contexts:
        conflicts.extend(_check_recently_sold_rebuy(daily_plan, trade_contexts))

    if pullback_plan and trade_contexts:
        conflicts.extend(_check_pullback_cooldown(pullback_plan, trade_contexts))

    if daily_plan and portfolio_summary:
        conflicts.extend(_check_exposure_limits(daily_plan, portfolio_summary))

    if pullback_plan and trade_contexts:
        conflicts.extend(_check_repeated_averaging(pullback_plan, trade_contexts))

    # Sort by severity: HIGH > MEDIUM > LOW
    severity_order = {ConflictSeverity.HIGH: 0, ConflictSeverity.MEDIUM: 1, ConflictSeverity.LOW: 2}
    conflicts.sort(key=lambda c: severity_order.get(c.severity, 9))

    return conflicts


def _check_buy_vs_exit(daily_plan: dict, exit_plan: dict) -> list[DecisionConflict]:
    """Detect: daily plan suggests buying a symbol that exit-plan flags for exit/trim."""
    conflicts = []

    # Get exit signals per symbol
    exit_actions = {}
    for pos in exit_plan.get("positions", []):
        action = pos.get("action", "HOLD")
        if action in ("TRIM_RISK", "REDUCE_1_3", "REDUCE_1_2", "EXIT", "REDUCE_2_3"):
            exit_actions[pos.get("symbol")] = action

    # Check if any daily plan order targets a symbol with exit signal
    # (This shouldn't happen since held tickers are excluded, but check pullback context)
    for order in daily_plan.get("limit_orders", []):
        ticker = order.get("ticker")
        if ticker in exit_actions:
            conflicts.append(DecisionConflict(
                severity=ConflictSeverity.HIGH,
                type=ConflictType.BUY_WHILE_EXIT_SIGNAL,
                symbol=ticker,
                message=f"{ticker}: Daily plan suggests buying, but exit-plan says {exit_actions[ticker]}",
                recommended_fix=f"Do not buy {ticker} — follow exit signal first",
            ))

    return conflicts


def _check_pullback_vs_exit(pullback_plan: dict, exit_plan: dict) -> list[DecisionConflict]:
    """Detect: pullback-add suggests adding to a symbol with exit/trim signal."""
    conflicts = []

    exit_risk_symbols = set()
    for pos in exit_plan.get("positions", []):
        action = pos.get("action", "HOLD")
        if action in ("TRIM_RISK", "REDUCE_1_3", "REDUCE_1_2", "EXIT", "REDUCE_2_3"):
            exit_risk_symbols.add(pos.get("symbol"))

    for plan in pullback_plan.get("plans", []):
        ticker = plan.get("symbol")
        action = plan.get("action", "")
        if ticker in exit_risk_symbols and action in ("ADD_SMALL", "ADD_NORMAL", "ADD_AGGRESSIVE"):
            conflicts.append(DecisionConflict(
                severity=ConflictSeverity.HIGH,
                type=ConflictType.PULLBACK_ADD_WHILE_EXIT_RISK,
                symbol=ticker,
                message=f"{ticker}: Pullback engine suggests adding, but exit engine says trim/reduce",
                recommended_fix=f"Do not add to {ticker} — prioritize risk management",
            ))

    return conflicts


def _check_recently_sold_rebuy(daily_plan: dict, trade_contexts: dict) -> list[DecisionConflict]:
    """Detect: daily plan suggests buying a recently-sold symbol."""
    conflicts = []

    for order in daily_plan.get("limit_orders", []):
        ticker = order.get("ticker")
        ctx = trade_contexts.get(ticker)
        if not ctx:
            continue

        if ctx.recently_sold and ctx.last_sell_reason in ("TRIM_RISK", "EXIT_SIGNAL", "STOP_LOSS"):
            conflicts.append(DecisionConflict(
                severity=ConflictSeverity.HIGH,
                type=ConflictType.RECENTLY_SOLD_REBUY,
                symbol=ticker,
                message=f"{ticker}: Was risk-sold recently (reason: {ctx.last_sell_reason}), now appearing in buy plan",
                recommended_fix=f"Skip {ticker} — wait for cooldown to expire ({ctx.cooldown_until[:10] if ctx.cooldown_until else 'N/A'})",
            ))
        elif ctx.recently_trimmed:
            conflicts.append(DecisionConflict(
                severity=ConflictSeverity.MEDIUM,
                type=ConflictType.RECENTLY_TRIMMED_REBUY,
                symbol=ticker,
                message=f"{ticker}: Was trimmed recently, now appearing in buy plan",
                recommended_fix=f"Consider waiting — trim cooldown until {ctx.cooldown_until[:10] if ctx.cooldown_until else 'N/A'}",
            ))

    return conflicts


def _check_pullback_cooldown(pullback_plan: dict, trade_contexts: dict) -> list[DecisionConflict]:
    """Detect: pullback-add on a symbol in cooldown."""
    conflicts = []

    for plan in pullback_plan.get("plans", []):
        ticker = plan.get("symbol")
        action = plan.get("action", "")
        if action not in ("ADD_SMALL", "ADD_NORMAL", "ADD_AGGRESSIVE"):
            continue

        ctx = trade_contexts.get(ticker)
        if not ctx:
            continue

        if plan.get("in_cooldown"):
            conflicts.append(DecisionConflict(
                severity=ConflictSeverity.MEDIUM,
                type=ConflictType.PULLBACK_ADD_WHILE_EXIT_RISK,
                symbol=ticker,
                message=f"{ticker}: Pullback-add suggested but symbol is in cooldown ({plan.get('cooldown_reason', '')})",
                recommended_fix=f"Wait for cooldown to expire before adding",
            ))

    return conflicts


def _check_exposure_limits(daily_plan: dict, portfolio) -> list[DecisionConflict]:
    """Detect: buying would exceed exposure limits."""
    conflicts = []

    total_order_amount = daily_plan.get("total_order_amount", 0)
    max_daily = daily_plan.get("max_daily_amount", 0)

    if max_daily > 0 and total_order_amount > max_daily * 1.1:
        conflicts.append(DecisionConflict(
            severity=ConflictSeverity.MEDIUM,
            type=ConflictType.DAILY_BUDGET_EXCEEDED,
            message=f"Total daily plan amount ${total_order_amount:.0f} exceeds 30% budget ${max_daily:.0f}",
            recommended_fix="Reduce order sizes or remove lowest-scored candidates",
        ))

    # Check single position exposure
    if hasattr(portfolio, 'positions'):
        for pos in portfolio.positions:
            exposure_pct = getattr(pos, 'weight', None) or getattr(pos, 'exposure_pct', None)
            if exposure_pct and exposure_pct > 20:
                conflicts.append(DecisionConflict(
                    severity=ConflictSeverity.MEDIUM,
                    type=ConflictType.SINGLE_POSITION_OVEREXPOSURE,
                    symbol=pos.ticker,
                    message=f"{pos.ticker}: Position is {exposure_pct:.1f}% of portfolio (>20%)",
                    recommended_fix=f"Consider trimming {pos.ticker} or not adding more",
                ))

    return conflicts


def _check_repeated_averaging(pullback_plan: dict, trade_contexts: dict) -> list[DecisionConflict]:
    """Detect: repeated averaging down (>2 adds in 10 days)."""
    conflicts = []

    for plan in pullback_plan.get("plans", []):
        ticker = plan.get("symbol")
        action = plan.get("action", "")
        if action not in ("ADD_SMALL", "ADD_NORMAL", "ADD_AGGRESSIVE"):
            continue

        ctx = trade_contexts.get(ticker)
        if not ctx:
            continue

        if ctx.adds_last_10_days >= 3:
            conflicts.append(DecisionConflict(
                severity=ConflictSeverity.MEDIUM,
                type=ConflictType.REPEATED_AVERAGING_DOWN,
                symbol=ticker,
                message=f"{ticker}: Already added {ctx.adds_last_10_days} times in last 10 days",
                recommended_fix=f"Pause adding to {ticker} — too many recent entries may indicate averaging into a losing position",
            ))

    return conflicts
