"""API routes for trade ledger CRUD + position rebuild."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.trade_ledger import (
    create_trade,
    delete_trade,
    get_current_positions,
    get_trades,
    update_trade,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["trades"])


class CreateTradeRequest(BaseModel):
    symbol: str
    side: str  # BUY or SELL
    quantity: float
    price: float
    fee: float = 0
    source: str = "MANUAL"
    reason: Optional[str] = None
    note: Optional[str] = None
    trade_time: Optional[str] = None


class UpdateTradeRequest(BaseModel):
    reason: Optional[str] = None
    note: Optional[str] = None


@router.get("/trades")
async def list_trades(
    symbol: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
):
    """List trades with optional filters."""
    trades = get_trades(symbol=symbol, since=since, limit=limit)
    return {"trades": [t.model_dump() for t in trades], "count": len(trades)}


@router.post("/trades")
async def add_trade(req: CreateTradeRequest):
    """Record a new trade."""
    if req.side not in ("BUY", "SELL"):
        raise HTTPException(400, "side must be BUY or SELL")
    if req.quantity <= 0:
        raise HTTPException(400, "quantity must be positive")
    if req.price <= 0:
        raise HTTPException(400, "price must be positive")

    trade = create_trade(
        symbol=req.symbol,
        side=req.side,
        quantity=req.quantity,
        price=req.price,
        fee=req.fee,
        source=req.source,
        reason=req.reason,
        note=req.note,
        trade_time=req.trade_time,
    )
    return {"status": "ok", "trade": trade.model_dump()}


@router.patch("/trades/{trade_id}")
async def patch_trade(trade_id: str, req: UpdateTradeRequest):
    """Update trade reason/note."""
    trade = update_trade(trade_id, reason=req.reason, note=req.note)
    if not trade:
        raise HTTPException(404, "Trade not found")
    return {"status": "ok", "trade": trade.model_dump()}


@router.delete("/trades/{trade_id}")
async def remove_trade(trade_id: str):
    """Delete a trade."""
    if not delete_trade(trade_id):
        raise HTTPException(404, "Trade not found")
    return {"status": "ok"}


@router.get("/positions/rebuild")
async def rebuild_positions():
    """Get current positions rebuilt from trade ledger (source of truth)."""
    positions = get_current_positions()
    return {
        "positions": [p.model_dump() for p in positions.values()],
        "count": len(positions),
    }
