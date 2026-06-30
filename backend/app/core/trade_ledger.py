"""Trade ledger service — source of truth for all trades and position reconstruction."""

import logging
import uuid
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.models import Trade, RebuiltPosition

logger = logging.getLogger(__name__)


def create_trade(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    fee: float = 0,
    source: str = "MANUAL",
    reason: str = None,
    note: str = None,
    trade_time: str = None,
) -> Trade:
    """Insert a trade into the ledger. Also updates legacy positions/cash tables."""
    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    if not trade_time:
        trade_time = now

    amount = round(quantity * price, 2)

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO trades (id, symbol, side, quantity, price, amount, fee,
               currency, trade_time, source, reason, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?)""",
            (trade_id, symbol.upper(), side, quantity, price, amount, fee,
             trade_time, source, reason, note, now),
        )

        # Update legacy positions table for backward compatibility
        _sync_legacy_position(conn, symbol.upper(), side, quantity, price)

        conn.commit()
        logger.info(f"Trade created: {side} {quantity} {symbol} @ {price} (id={trade_id[:8]})")

        return Trade(
            id=trade_id,
            symbol=symbol.upper(),
            side=side,
            quantity=quantity,
            price=price,
            amount=amount,
            fee=fee,
            trade_time=trade_time,
            source=source,
            reason=reason,
            note=note,
            created_at=now,
        )
    finally:
        conn.close()


def _sync_legacy_position(conn, symbol: str, side: str, quantity: float, price: float):
    """Keep the legacy positions table in sync for backward compat."""
    existing = conn.execute(
        "SELECT shares, avg_cost FROM positions WHERE ticker = ?", (symbol,)
    ).fetchone()

    old_shares = existing["shares"] if existing else 0
    old_cost = existing["avg_cost"] if existing else 0

    if side == "BUY":
        new_shares = old_shares + quantity
        if new_shares > 0:
            new_cost = (old_shares * old_cost + quantity * price) / new_shares
        else:
            new_cost = price

        if existing:
            conn.execute(
                "UPDATE positions SET shares = ?, avg_cost = ? WHERE ticker = ?",
                (new_shares, round(new_cost, 4), symbol),
            )
        else:
            conn.execute(
                "INSERT INTO positions (ticker, shares, avg_cost) VALUES (?, ?, ?)",
                (symbol, new_shares, round(new_cost, 4)),
            )

        # Update cash
        meta = conn.execute("SELECT cash FROM portfolio_meta WHERE id = 1").fetchone()
        if meta:
            new_cash = meta["cash"] - round(quantity * price, 2)
            conn.execute("UPDATE portfolio_meta SET cash = ? WHERE id = 1", (new_cash,))

    elif side == "SELL":
        new_shares = old_shares - quantity
        if new_shares <= 0:
            conn.execute("DELETE FROM positions WHERE ticker = ?", (symbol,))
        else:
            conn.execute(
                "UPDATE positions SET shares = ? WHERE ticker = ?",
                (new_shares, symbol),
            )

        # Update cash
        meta = conn.execute("SELECT cash FROM portfolio_meta WHERE id = 1").fetchone()
        if meta:
            new_cash = meta["cash"] + round(quantity * price, 2)
            conn.execute("UPDATE portfolio_meta SET cash = ? WHERE id = 1", (new_cash,))


def get_trades(
    symbol: str = None,
    since: str = None,
    limit: int = 100,
) -> list[Trade]:
    """Query trades with optional filters."""
    conn = get_db()
    try:
        query = "SELECT * FROM trades WHERE 1=1"
        params = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if since:
            query += " AND trade_time >= ?"
            params.append(since)

        query += " ORDER BY trade_time DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [Trade(**dict(row)) for row in rows]
    finally:
        conn.close()


def update_trade(trade_id: str, reason: str = None, note: str = None) -> Trade | None:
    """Update trade reason/note only."""
    conn = get_db()
    try:
        updates = []
        params = []
        if reason is not None:
            updates.append("reason = ?")
            params.append(reason)
        if note is not None:
            updates.append("note = ?")
            params.append(note)

        if not updates:
            row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            return Trade(**dict(row)) if row else None

        params.append(trade_id)
        conn.execute(
            f"UPDATE trades SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()

        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        return Trade(**dict(row)) if row else None
    finally:
        conn.close()


def delete_trade(trade_id: str) -> bool:
    """Delete a trade by ID."""
    conn = get_db()
    try:
        result = conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        conn.commit()
        return result.rowcount > 0
    finally:
        conn.close()


def rebuild_positions_from_trades(trades: list[Trade] = None) -> dict[str, RebuiltPosition]:
    """Rebuild current positions from the full trade ledger.

    This is the source of truth for portfolio state.
    """
    if trades is None:
        trades = get_trades(limit=100000)

    positions: dict[str, dict] = {}

    for trade in sorted(trades, key=lambda t: t.trade_time):
        symbol = trade.symbol.upper()

        if symbol not in positions:
            positions[symbol] = {
                "symbol": symbol,
                "quantity": 0.0,
                "average_cost": 0.0,
                "realized_pnl": 0.0,
            }

        pos = positions[symbol]

        if trade.side == "BUY":
            old_qty = pos["quantity"]
            old_cost = pos["average_cost"]
            new_qty = old_qty + trade.quantity

            if new_qty > 0:
                pos["average_cost"] = round(
                    (old_qty * old_cost + trade.quantity * trade.price + trade.fee) / new_qty,
                    6,
                )

            pos["quantity"] = new_qty

        elif trade.side == "SELL":
            sell_qty = min(trade.quantity, pos["quantity"])

            pos["realized_pnl"] += round(
                (trade.price - pos["average_cost"]) * sell_qty - trade.fee,
                2,
            )

            pos["quantity"] = pos["quantity"] - sell_qty

            if pos["quantity"] <= 0:
                pos["quantity"] = 0
                pos["average_cost"] = 0

    return {
        symbol: RebuiltPosition(**data)
        for symbol, data in positions.items()
        if data["quantity"] > 0
    }


def get_current_positions() -> dict[str, RebuiltPosition]:
    """Get current positions rebuilt from all trades."""
    return rebuild_positions_from_trades()


def get_peak_quantity(symbol: str) -> float:
    """Get the historical peak quantity held for a symbol (for runner detection)."""
    trades = get_trades(symbol=symbol, limit=100000)
    peak = 0.0
    current = 0.0

    for trade in sorted(trades, key=lambda t: t.trade_time):
        if trade.side == "BUY":
            current += trade.quantity
        elif trade.side == "SELL":
            current = max(0, current - trade.quantity)
        peak = max(peak, current)

    return peak
