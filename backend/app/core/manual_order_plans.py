"""Manual order plans service — suggested plans that users execute manually.

These are NOT broker orders. The system suggests, the user manually executes
outside the system, then records the result here.
"""

import logging
import uuid
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.models import ManualOrderPlan, ManualOrderPlanStatus
from app.core.trade_ledger import create_trade

logger = logging.getLogger(__name__)


def create_plan(
    symbol: str,
    source: str,
    action: str,
    limit_price: float = None,
    amount: float = None,
    quantity: float = None,
    reason: str = None,
    note: str = None,
    expires_at: str = None,
) -> ManualOrderPlan:
    """Create a suggested manual order plan."""
    plan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO manual_order_plans
               (id, symbol, source, action, limit_price, amount, quantity,
                status, filled_quantity, filled_amount, reason, note, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'SUGGESTED', 0, 0, ?, ?, ?, ?)""",
            (plan_id, symbol.upper(), source, action, limit_price, amount, quantity,
             reason, note, now, expires_at),
        )
        conn.commit()
        logger.info(f"Manual plan created: {action} {symbol} (id={plan_id[:8]})")

        return ManualOrderPlan(
            id=plan_id,
            symbol=symbol.upper(),
            source=source,
            action=action,
            limit_price=limit_price,
            amount=amount,
            quantity=quantity,
            status=ManualOrderPlanStatus.SUGGESTED,
            reason=reason,
            note=note,
            created_at=now,
            expires_at=expires_at,
        )
    finally:
        conn.close()


def get_plans(
    symbol: str = None,
    status: str = None,
    source: str = None,
    limit: int = 100,
) -> list[ManualOrderPlan]:
    """Query manual order plans with optional filters."""
    conn = get_db()
    try:
        query = "SELECT * FROM manual_order_plans WHERE 1=1"
        params = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if status:
            query += " AND status = ?"
            params.append(status)
        if source:
            query += " AND source = ?"
            params.append(source)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [ManualOrderPlan(**dict(row)) for row in rows]
    finally:
        conn.close()


def get_plan_by_id(plan_id: str) -> ManualOrderPlan | None:
    """Get a single plan by ID."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM manual_order_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        return ManualOrderPlan(**dict(row)) if row else None
    finally:
        conn.close()


def accept_plan(plan_id: str) -> ManualOrderPlan | None:
    """Mark plan as accepted by user (does NOT place any broker order)."""
    return _update_status(plan_id, ManualOrderPlanStatus.USER_ACCEPTED)


def reject_plan(plan_id: str) -> ManualOrderPlan | None:
    """Mark plan as rejected by user."""
    return _update_status(plan_id, ManualOrderPlanStatus.USER_REJECTED)


def mark_plan_filled(
    plan_id: str,
    filled_quantity: float,
    filled_price: float,
    filled_time: str = None,
) -> ManualOrderPlan | None:
    """Mark plan as manually filled. Auto-creates a trade record.

    This only records a trade after the user says it was manually filled.
    It does NOT send broker orders.
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM manual_order_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        if not row:
            return None

        plan = ManualOrderPlan(**dict(row))
        filled_amount = round(filled_quantity * filled_price, 2)

        conn.execute(
            """UPDATE manual_order_plans
               SET status = 'MANUALLY_FILLED',
                   filled_quantity = ?,
                   filled_amount = ?
               WHERE id = ?""",
            (filled_quantity, filled_amount, plan_id),
        )
        conn.commit()

        # Infer trade side from action
        side = _infer_trade_side(plan.action)

        # Auto-create trade from filled plan
        create_trade(
            symbol=plan.symbol,
            side=side,
            quantity=filled_quantity,
            price=filled_price,
            source="MANUAL_PLAN",
            reason=plan.reason,
            trade_time=filled_time,
        )

        logger.info(f"Plan {plan_id[:8]} manually filled: {side} {filled_quantity} {plan.symbol} @ {filled_price}")

        return get_plan_by_id(plan_id)
    finally:
        conn.close()


def mark_plan_cancelled(plan_id: str, note: str = None) -> ManualOrderPlan | None:
    """Mark plan as manually cancelled. Does NOT cancel any broker order."""
    conn = get_db()
    try:
        updates = "status = 'MANUALLY_CANCELLED'"
        params = []
        if note:
            updates += ", note = ?"
            params.append(note)
        params.append(plan_id)

        conn.execute(f"UPDATE manual_order_plans SET {updates} WHERE id = ?", params)
        conn.commit()
        return get_plan_by_id(plan_id)
    finally:
        conn.close()


def expire_plan(plan_id: str) -> ManualOrderPlan | None:
    """Mark a single plan as expired."""
    return _update_status(plan_id, ManualOrderPlanStatus.EXPIRED)


def expire_stale_plans():
    """Expire all plans past their expires_at date."""
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        result = conn.execute(
            """UPDATE manual_order_plans
               SET status = 'EXPIRED'
               WHERE status IN ('SUGGESTED', 'USER_ACCEPTED')
               AND expires_at IS NOT NULL
               AND expires_at < ?""",
            (now,),
        )
        conn.commit()
        if result.rowcount > 0:
            logger.info(f"Expired {result.rowcount} stale manual plan(s)")
        return result.rowcount
    finally:
        conn.close()


def has_active_plan(symbol: str) -> bool:
    """Check if a symbol has an active (SUGGESTED or USER_ACCEPTED) plan."""
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT COUNT(*) as cnt FROM manual_order_plans
               WHERE symbol = ? AND status IN ('SUGGESTED', 'USER_ACCEPTED')""",
            (symbol.upper(),),
        ).fetchone()
        return row["cnt"] > 0
    finally:
        conn.close()


def _update_status(plan_id: str, status: ManualOrderPlanStatus) -> ManualOrderPlan | None:
    """Update plan status."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE manual_order_plans SET status = ? WHERE id = ?",
            (status.value, plan_id),
        )
        conn.commit()
        return get_plan_by_id(plan_id)
    finally:
        conn.close()


def _infer_trade_side(action: str) -> str:
    """Infer BUY/SELL from plan action."""
    sell_actions = {"SELL_LIMIT", "TRIM", "EXIT", "REDUCE", "CANCEL_SUGGESTION"}
    return "SELL" if action.upper() in sell_actions else "BUY"
