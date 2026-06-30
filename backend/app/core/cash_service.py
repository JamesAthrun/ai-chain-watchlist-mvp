"""Cash service — tracks deposits, withdrawals, dividends, fees, interest."""

import logging
import uuid
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.models import CashTransaction

logger = logging.getLogger(__name__)


def create_cash_transaction(
    tx_type: str,
    amount: float,
    currency: str = "USD",
    transaction_time: str = None,
    note: str = None,
) -> CashTransaction:
    """Record a cash transaction."""
    tx_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    if not transaction_time:
        transaction_time = now

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO cash_transactions (id, type, amount, currency, transaction_time, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tx_id, tx_type, amount, currency, transaction_time, note, now),
        )

        # Also update legacy portfolio_meta.cash
        meta = conn.execute("SELECT cash FROM portfolio_meta WHERE id = 1").fetchone()
        if meta:
            delta = amount if tx_type in ("DEPOSIT", "DIVIDEND", "INTEREST") else -amount
            new_cash = meta["cash"] + delta
            conn.execute("UPDATE portfolio_meta SET cash = ? WHERE id = 1", (round(new_cash, 2),))

        conn.commit()
        logger.info(f"Cash transaction: {tx_type} {amount} {currency}")

        return CashTransaction(
            id=tx_id,
            type=tx_type,
            amount=amount,
            currency=currency,
            transaction_time=transaction_time,
            note=note,
            created_at=now,
        )
    finally:
        conn.close()


def get_cash_transactions(
    since: str = None,
    limit: int = 100,
) -> list[CashTransaction]:
    """Query cash transactions."""
    conn = get_db()
    try:
        query = "SELECT * FROM cash_transactions WHERE 1=1"
        params = []

        if since:
            query += " AND transaction_time >= ?"
            params.append(since)

        query += " ORDER BY transaction_time DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [CashTransaction(**dict(row)) for row in rows]
    finally:
        conn.close()


def update_cash_transaction(tx_id: str, note: str = None) -> CashTransaction | None:
    """Update cash transaction note."""
    conn = get_db()
    try:
        if note is not None:
            conn.execute("UPDATE cash_transactions SET note = ? WHERE id = ?", (note, tx_id))
            conn.commit()

        row = conn.execute("SELECT * FROM cash_transactions WHERE id = ?", (tx_id,)).fetchone()
        return CashTransaction(**dict(row)) if row else None
    finally:
        conn.close()


def delete_cash_transaction(tx_id: str) -> bool:
    """Delete a cash transaction."""
    conn = get_db()
    try:
        result = conn.execute("DELETE FROM cash_transactions WHERE id = ?", (tx_id,))
        conn.commit()
        return result.rowcount > 0
    finally:
        conn.close()


def calculate_current_cash() -> float:
    """Calculate current cash from all cash transactions and trade flows.

    Cash = sum(deposits + dividends + interest + sell proceeds)
         - sum(withdrawals + fees + buy amounts)
    """
    conn = get_db()
    try:
        # Cash from explicit transactions
        rows = conn.execute("SELECT type, amount FROM cash_transactions").fetchall()
        cash = 0.0
        for row in rows:
            if row["type"] in ("DEPOSIT", "DIVIDEND", "INTEREST"):
                cash += row["amount"]
            else:  # WITHDRAW, FEE
                cash -= row["amount"]

        # Cash from trades: buys reduce cash, sells add cash
        trade_rows = conn.execute("SELECT side, amount, fee FROM trades").fetchall()
        for row in trade_rows:
            if row["side"] == "BUY":
                cash -= row["amount"] + (row["fee"] or 0)
            elif row["side"] == "SELL":
                cash += row["amount"] - (row["fee"] or 0)

        return round(cash, 2)
    finally:
        conn.close()
