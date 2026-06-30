"""API routes for manual order plans.

These are suggestions only. The system never places broker orders.
Users must execute trades manually in their brokerage account.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.manual_order_plans import (
    accept_plan,
    create_plan,
    expire_plan,
    get_plan_by_id,
    get_plans,
    mark_plan_cancelled,
    mark_plan_filled,
    reject_plan,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["manual-plans"])


class CreatePlanRequest(BaseModel):
    symbol: str
    source: str  # DAILY_PLAN, PULLBACK_ADD_PLAN, EXIT_PLAN, MANUAL
    action: str  # BUY_LIMIT, SELL_LIMIT, TRIM, EXIT, WATCH
    limit_price: Optional[float] = None
    amount: Optional[float] = None
    quantity: Optional[float] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    expires_at: Optional[str] = None


class UpdatePlanRequest(BaseModel):
    note: Optional[str] = None
    reason: Optional[str] = None


class FillPlanRequest(BaseModel):
    filled_quantity: float
    filled_price: float
    filled_time: Optional[str] = None


class CancelPlanRequest(BaseModel):
    note: Optional[str] = None


@router.get("/manual-order-plans")
async def list_plans(
    symbol: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
):
    """List manual order plans."""
    plans = get_plans(symbol=symbol, status=status, source=source, limit=limit)
    return {"plans": [p.model_dump() for p in plans], "count": len(plans)}


@router.post("/manual-order-plans")
async def add_plan(req: CreatePlanRequest):
    """Create a suggested manual order plan."""
    plan = create_plan(
        symbol=req.symbol,
        source=req.source,
        action=req.action,
        limit_price=req.limit_price,
        amount=req.amount,
        quantity=req.quantity,
        reason=req.reason,
        note=req.note,
        expires_at=req.expires_at,
    )
    return {"status": "ok", "plan": plan.model_dump()}


@router.patch("/manual-order-plans/{plan_id}")
async def update_plan(plan_id: str, req: UpdatePlanRequest):
    """Update plan note/reason."""
    plan = get_plan_by_id(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    # Simple update via direct DB
    from app.core.database import get_db
    conn = get_db()
    try:
        updates = []
        params = []
        if req.note is not None:
            updates.append("note = ?")
            params.append(req.note)
        if req.reason is not None:
            updates.append("reason = ?")
            params.append(req.reason)
        if updates:
            params.append(plan_id)
            conn.execute(f"UPDATE manual_order_plans SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "plan": get_plan_by_id(plan_id).model_dump()}


@router.post("/manual-order-plans/{plan_id}/accept")
async def accept(plan_id: str):
    """Accept a suggested plan (does NOT place any broker order)."""
    plan = accept_plan(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    return {"status": "ok", "plan": plan.model_dump()}


@router.post("/manual-order-plans/{plan_id}/reject")
async def reject(plan_id: str):
    """Reject a suggested plan."""
    plan = reject_plan(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    return {"status": "ok", "plan": plan.model_dump()}


@router.post("/manual-order-plans/{plan_id}/mark-filled")
async def fill(plan_id: str, req: FillPlanRequest):
    """Mark plan as manually filled. Auto-creates a trade record.

    This only records a trade after the user says it was manually executed.
    It does NOT send broker orders.
    """
    if req.filled_quantity <= 0:
        raise HTTPException(400, "filled_quantity must be positive")
    if req.filled_price <= 0:
        raise HTTPException(400, "filled_price must be positive")

    plan = mark_plan_filled(
        plan_id,
        filled_quantity=req.filled_quantity,
        filled_price=req.filled_price,
        filled_time=req.filled_time,
    )
    if not plan:
        raise HTTPException(404, "Plan not found")
    return {"status": "ok", "plan": plan.model_dump()}


@router.post("/manual-order-plans/{plan_id}/mark-cancelled")
async def cancel(plan_id: str, req: CancelPlanRequest = None):
    """Mark plan as manually cancelled. Does NOT cancel any broker order."""
    note = req.note if req else None
    plan = mark_plan_cancelled(plan_id, note=note)
    if not plan:
        raise HTTPException(404, "Plan not found")
    return {"status": "ok", "plan": plan.model_dump()}


@router.post("/manual-order-plans/{plan_id}/expire")
async def expire(plan_id: str):
    """Mark plan as expired."""
    plan = expire_plan(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    return {"status": "ok", "plan": plan.model_dump()}
