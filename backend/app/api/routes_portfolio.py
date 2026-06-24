"""Portfolio API routes."""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config_loader import CONFIG_DIR, load_portfolio
from app.core.portfolio import analyze_portfolio

router = APIRouter(prefix="/api")


class PositionInput(BaseModel):
    ticker: str
    shares: float
    avg_cost: float
    bucket: Optional[str] = None
    intent: Optional[str] = None


class PortfolioUpdate(BaseModel):
    account_value: float
    cash: float
    positions: list[PositionInput]


class TradeInput(BaseModel):
    ticker: str
    action: str  # "buy" or "sell"
    shares: float
    price: float
    bucket: Optional[str] = None
    intent: Optional[str] = None


@router.get("/portfolio")
async def get_portfolio():
    portfolio_data = load_portfolio()
    summary = analyze_portfolio(portfolio_data)
    return summary.model_dump()


@router.put("/portfolio")
async def update_portfolio(update: PortfolioUpdate):
    """Replace the full portfolio."""
    data = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "account_value": update.account_value,
        "cash": update.cash,
        "positions": [p.model_dump(exclude_none=True) for p in update.positions],
    }
    filepath = CONFIG_DIR / "portfolio.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return {"status": "ok", "portfolio": data}


@router.post("/portfolio/trade")
async def record_trade(trade: TradeInput):
    """Record a buy/sell trade and update portfolio accordingly."""
    portfolio_data = load_portfolio()
    positions = portfolio_data.get("positions", [])
    cash = portfolio_data.get("cash", 0.0)

    trade_value = trade.shares * trade.price

    existing = None
    for p in positions:
        if p["ticker"] == trade.ticker:
            existing = p
            break

    if trade.action == "buy":
        cash -= trade_value
        if existing:
            old_value = existing["shares"] * existing["avg_cost"]
            new_shares = existing["shares"] + trade.shares
            existing["avg_cost"] = (old_value + trade_value) / new_shares if new_shares > 0 else 0
            existing["shares"] = new_shares
        else:
            new_pos = {"ticker": trade.ticker, "shares": trade.shares, "avg_cost": trade.price}
            if trade.bucket:
                new_pos["bucket"] = trade.bucket
            if trade.intent:
                new_pos["intent"] = trade.intent
            positions.append(new_pos)
    elif trade.action == "sell":
        cash += trade_value
        if existing:
            existing["shares"] -= trade.shares
            if existing["shares"] <= 0:
                positions.remove(existing)
        else:
            return {"status": "error", "message": f"No position found for {trade.ticker}"}
    else:
        return {"status": "error", "message": "action must be 'buy' or 'sell'"}

    portfolio_data["cash"] = round(cash, 2)
    portfolio_data["positions"] = positions
    portfolio_data["as_of"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    filepath = CONFIG_DIR / "portfolio.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(portfolio_data, f, indent=2, ensure_ascii=False)

    return {"status": "ok", "trade": trade.model_dump(), "cash_remaining": portfolio_data["cash"]}
