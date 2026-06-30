"""Trade history context service — provides decision-aware context per symbol.

Used by daily-plan, pullback-add-plan, exit-plan, and conflict detector
to understand recent trading activity and enforce cooldown rules.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.core.models import Trade, TradeHistoryContext, TradeReason
from app.core.trade_ledger import get_trades, rebuild_positions_from_trades

logger = logging.getLogger(__name__)

# Cooldown durations
RISK_SELL_COOLDOWN_DAYS = 5
TRIM_COOLDOWN_DAYS = 2
RECENT_WINDOW_DAYS = 10


def build_context(symbol: str, trades: list[Trade]) -> TradeHistoryContext:
    """Build trade history context for a single symbol."""
    symbol = symbol.upper()
    symbol_trades = [t for t in trades if t.symbol == symbol]

    if not symbol_trades:
        return TradeHistoryContext(symbol=symbol)

    now = datetime.now(timezone.utc)
    five_days_ago = (now - timedelta(days=5)).isoformat()
    ten_days_ago = (now - timedelta(days=10)).isoformat()

    # Last buy/sell info
    buys = [t for t in symbol_trades if t.side == "BUY"]
    sells = [t for t in symbol_trades if t.side == "SELL"]

    last_buy = buys[-1] if buys else None
    last_sell = sells[-1] if sells else None

    # Counts in recent windows
    buys_last_5 = sum(1 for t in buys if t.trade_time >= five_days_ago)
    sells_last_5 = sum(1 for t in sells if t.trade_time >= five_days_ago)
    adds_last_10 = sum(1 for t in buys if t.trade_time >= ten_days_ago)
    trims_last_10 = sum(1 for t in sells if t.trade_time >= ten_days_ago)

    # Recent activity flags
    recently_sold = last_sell is not None and last_sell.trade_time >= five_days_ago
    recently_trimmed = last_sell is not None and last_sell.trade_time >= (now - timedelta(days=TRIM_COOLDOWN_DAYS)).isoformat()
    recently_added = last_buy is not None and last_buy.trade_time >= ten_days_ago

    # Cooldown calculation
    cooldown_until = _calculate_cooldown(last_sell, now)

    # Entry price stats
    buy_prices = [t.price for t in buys]
    avg_entry = sum(buy_prices) / len(buy_prices) if buy_prices else None
    highest_entry = max(buy_prices) if buy_prices else None
    lowest_entry = min(buy_prices) if buy_prices else None

    # P&L from rebuilt positions
    positions = rebuild_positions_from_trades(trades)
    pos = positions.get(symbol)
    realized_pnl = pos.realized_pnl if pos else _calc_realized_pnl(symbol_trades)

    return TradeHistoryContext(
        symbol=symbol,
        last_buy_date=last_buy.trade_time if last_buy else None,
        last_buy_price=last_buy.price if last_buy else None,
        last_buy_amount=last_buy.amount if last_buy else None,
        last_sell_date=last_sell.trade_time if last_sell else None,
        last_sell_price=last_sell.price if last_sell else None,
        last_sell_amount=last_sell.amount if last_sell else None,
        last_sell_reason=last_sell.reason if last_sell else None,
        buys_last_5_days=buys_last_5,
        sells_last_5_days=sells_last_5,
        adds_last_10_days=adds_last_10,
        trims_last_10_days=trims_last_10,
        recently_sold=recently_sold,
        recently_trimmed=recently_trimmed,
        recently_added=recently_added,
        cooldown_until=cooldown_until,
        average_entry_price=round(avg_entry, 4) if avg_entry else None,
        highest_entry_price=highest_entry,
        lowest_entry_price=lowest_entry,
        realized_pnl=realized_pnl,
    )


def build_all_contexts(trades: list[Trade] = None) -> dict[str, TradeHistoryContext]:
    """Build trade history context for all symbols with trade activity."""
    if trades is None:
        trades = get_trades(limit=100000)

    symbols = set(t.symbol for t in trades)
    return {symbol: build_context(symbol, trades) for symbol in symbols}


def is_in_cooldown(ctx: TradeHistoryContext) -> tuple[bool, str]:
    """Check if a symbol is in cooldown period.

    Returns (is_cooldown, reason).
    """
    if not ctx.cooldown_until:
        return False, ""

    now = datetime.now(timezone.utc).isoformat()
    if now < ctx.cooldown_until:
        if ctx.last_sell_reason in (
            TradeReason.TRIM_RISK.value,
            TradeReason.EXIT_SIGNAL.value,
            TradeReason.STOP_LOSS.value,
        ):
            return True, f"Risk sell cooldown until {ctx.cooldown_until[:10]} (reason: {ctx.last_sell_reason})"
        elif ctx.recently_trimmed:
            return True, f"Trim cooldown until {ctx.cooldown_until[:10]}"

    return False, ""


def _calculate_cooldown(last_sell: Trade | None, now: datetime) -> str | None:
    """Calculate cooldown end date based on sell reason."""
    if not last_sell:
        return None

    sell_time = datetime.fromisoformat(last_sell.trade_time.replace("Z", "+00:00"))
    if sell_time.tzinfo is None:
        sell_time = sell_time.replace(tzinfo=timezone.utc)

    # Risk sells get longer cooldown
    risk_reasons = {
        TradeReason.TRIM_RISK.value,
        TradeReason.EXIT_SIGNAL.value,
        TradeReason.STOP_LOSS.value,
    }

    if last_sell.reason in risk_reasons:
        cooldown_end = sell_time + timedelta(days=RISK_SELL_COOLDOWN_DAYS)
    elif last_sell.reason in (TradeReason.TRIM_PROFIT.value, TradeReason.MANUAL_SELL.value):
        cooldown_end = sell_time + timedelta(days=TRIM_COOLDOWN_DAYS)
    else:
        return None

    if cooldown_end > now:
        return cooldown_end.isoformat()

    return None


def _calc_realized_pnl(trades: list[Trade]) -> float:
    """Calculate realized P&L from a symbol's trades."""
    qty = 0.0
    avg_cost = 0.0
    realized = 0.0

    for t in sorted(trades, key=lambda x: x.trade_time):
        if t.side == "BUY":
            new_qty = qty + t.quantity
            if new_qty > 0:
                avg_cost = (qty * avg_cost + t.quantity * t.price + t.fee) / new_qty
            qty = new_qty
        elif t.side == "SELL":
            sell_qty = min(t.quantity, qty)
            realized += (t.price - avg_cost) * sell_qty - t.fee
            qty -= sell_qty
            if qty <= 0:
                qty = 0
                avg_cost = 0

    return round(realized, 2)
