"""API routes for cash transactions."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.cash_service import (
    calculate_current_cash,
    create_cash_transaction,
    delete_cash_transaction,
    get_cash_transactions,
    update_cash_transaction,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["cash"])

VALID_TYPES = {"DEPOSIT", "WITHDRAW", "DIVIDEND", "FEE", "INTEREST"}


class CreateCashRequest(BaseModel):
    type: str
    amount: float
    currency: str = "USD"
    transaction_time: Optional[str] = None
    note: Optional[str] = None


class UpdateCashRequest(BaseModel):
    note: Optional[str] = None


@router.get("/cash-transactions")
async def list_cash_transactions(
    since: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
):
    """List cash transactions."""
    txs = get_cash_transactions(since=since, limit=limit)
    return {"transactions": [t.model_dump() for t in txs], "count": len(txs)}


@router.post("/cash-transactions")
async def add_cash_transaction(req: CreateCashRequest):
    """Record a cash transaction (deposit, withdrawal, dividend, etc.)."""
    if req.type not in VALID_TYPES:
        raise HTTPException(400, f"type must be one of {VALID_TYPES}")
    if req.amount <= 0:
        raise HTTPException(400, "amount must be positive")

    tx = create_cash_transaction(
        tx_type=req.type,
        amount=req.amount,
        currency=req.currency,
        transaction_time=req.transaction_time,
        note=req.note,
    )
    return {"status": "ok", "transaction": tx.model_dump()}


@router.patch("/cash-transactions/{tx_id}")
async def patch_cash_transaction(tx_id: str, req: UpdateCashRequest):
    """Update cash transaction note."""
    tx = update_cash_transaction(tx_id, note=req.note)
    if not tx:
        raise HTTPException(404, "Cash transaction not found")
    return {"status": "ok", "transaction": tx.model_dump()}


@router.delete("/cash-transactions/{tx_id}")
async def remove_cash_transaction(tx_id: str):
    """Delete a cash transaction."""
    if not delete_cash_transaction(tx_id):
        raise HTTPException(404, "Cash transaction not found")
    return {"status": "ok"}


@router.get("/cash/balance")
async def get_cash_balance():
    """Get current cash balance calculated from all transactions and trades."""
    balance = calculate_current_cash()
    return {"cash": balance}
