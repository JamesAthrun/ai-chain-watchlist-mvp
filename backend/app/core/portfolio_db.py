"""Portfolio database operations (CRUD + trade logging)."""

import logging
from datetime import datetime, timezone

from app.core.database import get_db

logger = logging.getLogger(__name__)


def get_portfolio_data() -> dict:
    """Get portfolio data in the same format as the old load_portfolio().

    Returns dict compatible with analyze_portfolio().
    """
    conn = get_db()
    try:
        meta = conn.execute("SELECT account_value, cash, updated_at FROM portfolio_meta WHERE id = 1").fetchone()
        if not meta:
            return {"account_value": 0, "cash": 0, "positions": []}

        positions = conn.execute("SELECT ticker, shares, avg_cost, bucket, intent FROM positions WHERE shares > 0").fetchall()

        return {
            "account_value": meta["account_value"],
            "cash": meta["cash"],
            "as_of": meta["updated_at"],
            "positions": [
                {
                    "ticker": p["ticker"],
                    "shares": p["shares"],
                    "avg_cost": p["avg_cost"],
                    "bucket": p["bucket"],
                    "intent": p["intent"],
                }
                for p in positions
            ],
        }
    finally:
        conn.close()


def record_trade(action: str, ticker: str, shares: float, price: float,
                 bucket: str = None, intent: str = None, notes: str = None) -> dict:
    """Record a buy/sell trade with full audit trail.

    Returns dict with trade details and updated portfolio state.
    """
    conn = get_db()
    try:
        meta = conn.execute("SELECT account_value, cash FROM portfolio_meta WHERE id = 1").fetchone()
        cash_before = meta["cash"] if meta else 0
        trade_value = shares * price

        # Get existing position
        existing = conn.execute("SELECT shares, avg_cost FROM positions WHERE ticker = ?", (ticker,)).fetchone()
        shares_before = existing["shares"] if existing else 0
        avg_cost_before = existing["avg_cost"] if existing else 0

        if action == "buy":
            cash_after = cash_before - trade_value
            if existing:
                new_shares = shares_before + shares
                new_avg_cost = ((shares_before * avg_cost_before) + trade_value) / new_shares if new_shares > 0 else 0
                conn.execute(
                    "UPDATE positions SET shares = ?, avg_cost = ? WHERE ticker = ?",
                    (new_shares, round(new_avg_cost, 4), ticker),
                )
            else:
                new_shares = shares
                new_avg_cost = price
                conn.execute(
                    "INSERT INTO positions (ticker, shares, avg_cost, bucket, intent) VALUES (?, ?, ?, ?, ?)",
                    (ticker, shares, price, bucket, intent),
                )
        elif action == "sell":
            if not existing or shares_before <= 0:
                return {"status": "error", "message": f"No position found for {ticker}"}
            cash_after = cash_before + trade_value
            new_shares = shares_before - shares
            new_avg_cost = avg_cost_before  # avg_cost doesn't change on sell
            if new_shares <= 0:
                conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
                new_shares = 0
            else:
                conn.execute(
                    "UPDATE positions SET shares = ? WHERE ticker = ?",
                    (new_shares, ticker),
                )
        else:
            return {"status": "error", "message": "action must be 'buy' or 'sell'"}

        # Update cash and account_value
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE portfolio_meta SET cash = ?, updated_at = ? WHERE id = 1",
            (round(cash_after, 2), now_str),
        )
        _recalculate_account_value(conn)

        # Write audit log
        conn.execute(
            """INSERT INTO trade_log
               (action, ticker, shares, price, cash_before, cash_after,
                shares_before, shares_after, avg_cost_before, avg_cost_after, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (action, ticker, shares, price, round(cash_before, 2), round(cash_after, 2),
             shares_before, new_shares, avg_cost_before, round(new_avg_cost, 4), notes),
        )

        conn.commit()
        logger.info(f"Trade recorded: {action} {shares} {ticker} @ {price}")

        return {
            "status": "ok",
            "trade": {
                "action": action,
                "ticker": ticker,
                "shares": shares,
                "price": price,
                "trade_value": round(trade_value, 2),
            },
            "cash_before": round(cash_before, 2),
            "cash_after": round(cash_after, 2),
            "position": {
                "ticker": ticker,
                "shares_before": shares_before,
                "shares_after": new_shares,
                "avg_cost": round(new_avg_cost, 4),
            },
        }
    finally:
        conn.close()


def set_portfolio(account_value: float, cash: float, positions: list[dict]) -> dict:
    """Replace the entire portfolio (with audit log)."""
    conn = get_db()
    try:
        meta = conn.execute("SELECT cash FROM portfolio_meta WHERE id = 1").fetchone()
        cash_before = meta["cash"] if meta else 0

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            "UPDATE portfolio_meta SET account_value = ?, cash = ?, updated_at = ? WHERE id = 1",
            (account_value, cash, now_str),
        )

        # Clear and re-insert positions
        conn.execute("DELETE FROM positions")
        for pos in positions:
            conn.execute(
                "INSERT INTO positions (ticker, shares, avg_cost, bucket, intent) VALUES (?, ?, ?, ?, ?)",
                (pos["ticker"], pos.get("shares", 0), pos.get("avg_cost", 0),
                 pos.get("bucket"), pos.get("intent")),
            )

        # Audit log
        pos_summary = ", ".join(f"{p['ticker']}x{p.get('shares', 0)}" for p in positions)
        conn.execute(
            """INSERT INTO trade_log
               (action, notes, cash_before, cash_after)
               VALUES ('set_portfolio', ?, ?, ?)""",
            (f"Set portfolio: {pos_summary}" if positions else "Set portfolio: all cash",
             cash_before, cash),
        )

        conn.commit()
        logger.info(f"Portfolio replaced: {len(positions)} positions, cash={cash}")

        return {
            "status": "ok",
            "account_value": account_value,
            "cash": cash,
            "positions_count": len(positions),
        }
    finally:
        conn.close()


def get_trade_history(limit: int = 50, ticker: str = None) -> list[dict]:
    """Get trade history, optionally filtered by ticker."""
    conn = get_db()
    try:
        if ticker:
            rows = conn.execute(
                "SELECT * FROM trade_log WHERE ticker = ? ORDER BY id DESC LIMIT ?",
                (ticker.upper(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trade_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def adjust_cash(amount: float, reason: str = "") -> dict:
    """Add or subtract cash (e.g. deposit, withdrawal, dividend).

    Positive amount = add cash, negative = withdraw.
    """
    conn = get_db()
    try:
        meta = conn.execute("SELECT cash FROM portfolio_meta WHERE id = 1").fetchone()
        cash_before = meta["cash"] if meta else 0
        cash_after = cash_before + amount

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE portfolio_meta SET cash = ?, updated_at = ? WHERE id = 1",
            (round(cash_after, 2), now_str),
        )
        _recalculate_account_value(conn)

        action = "deposit" if amount >= 0 else "withdrawal"
        conn.execute(
            """INSERT INTO trade_log
               (action, notes, cash_before, cash_after)
               VALUES (?, ?, ?, ?)""",
            (action, reason or f"Cash adjustment: {amount:+.2f}", cash_before, round(cash_after, 2)),
        )

        conn.commit()
        logger.info(f"Cash adjusted: {amount:+.2f} ({reason}), {cash_before:.2f} -> {cash_after:.2f}")

        return {
            "status": "ok",
            "action": action,
            "amount": amount,
            "cash_before": round(cash_before, 2),
            "cash_after": round(cash_after, 2),
            "reason": reason,
        }
    finally:
        conn.close()


def _recalculate_account_value(conn):
    """Recalculate account_value = cash + sum(shares * avg_cost)."""
    meta = conn.execute("SELECT cash FROM portfolio_meta WHERE id = 1").fetchone()
    cash = meta["cash"] if meta else 0

    result = conn.execute("SELECT COALESCE(SUM(shares * avg_cost), 0) as invested FROM positions WHERE shares > 0").fetchone()
    invested = result["invested"]

    conn.execute(
        "UPDATE portfolio_meta SET account_value = ? WHERE id = 1",
        (round(cash + invested, 2),),
    )
