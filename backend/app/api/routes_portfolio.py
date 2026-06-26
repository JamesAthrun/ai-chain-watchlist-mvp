"""Portfolio API routes — backed by SQLite."""

import json
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.llm_client import analyze_market, parse_trade_intent
from app.core.portfolio import analyze_portfolio
from app.core.portfolio_db import (
    get_portfolio_data,
    get_trade_history,
    record_trade as db_record_trade,
    set_portfolio as db_set_portfolio,
    adjust_cash as db_adjust_cash,
)

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


class NaturalInput(BaseModel):
    text: str


class ConfirmInput(BaseModel):
    parsed: dict


@router.get("/portfolio")
async def get_portfolio(enhance: bool = Query(False)):
    portfolio_data = get_portfolio_data()
    summary = analyze_portfolio(portfolio_data)
    result = summary.model_dump()
    if enhance:
        analysis = analyze_market(json.dumps(result, ensure_ascii=False, default=str), "portfolio")
        result["llm_analysis"] = analysis
    return result


@router.put("/portfolio")
async def update_portfolio(update: PortfolioUpdate):
    """Replace the full portfolio."""
    positions = [p.model_dump(exclude_none=True) for p in update.positions]
    result = db_set_portfolio(update.account_value, update.cash, positions)
    return result


@router.post("/portfolio/trade")
async def record_trade(trade: TradeInput):
    """Record a buy/sell trade."""
    result = db_record_trade(
        action=trade.action,
        ticker=trade.ticker,
        shares=trade.shares,
        price=trade.price,
        bucket=trade.bucket,
        intent=trade.intent,
    )
    return result


@router.get("/portfolio/history")
async def portfolio_history(limit: int = Query(50), ticker: Optional[str] = None):
    """Get trade history."""
    history = get_trade_history(limit=limit, ticker=ticker)
    return {"trades": history, "count": len(history)}


class CashAdjustInput(BaseModel):
    amount: float
    reason: Optional[str] = ""


@router.post("/portfolio/cash")
async def adjust_cash(req: CashAdjustInput):
    """Add or withdraw cash. Positive = deposit, negative = withdrawal."""
    result = db_adjust_cash(req.amount, req.reason or "")
    return result


@router.post("/portfolio/parse")
async def parse_portfolio(req: NaturalInput):
    """Parse natural language into structured trade data (does NOT write to DB).

    Returns parsed data for user confirmation.
    """
    portfolio_data = get_portfolio_data()
    portfolio_json = json.dumps(portfolio_data, ensure_ascii=False)

    parsed = parse_trade_intent(req.text, portfolio_json)
    if parsed is None:
        return {"status": "error", "message": "无法解析，请检查描述是否清楚，或 LLM 不可用。"}

    # Build a human-readable preview
    preview = _build_preview(parsed, portfolio_data)

    return {
        "status": "ok",
        "parsed": parsed,
        "preview": preview,
    }


@router.post("/portfolio/confirm")
async def confirm_portfolio(req: ConfirmInput):
    """Confirm and execute a previously parsed trade/portfolio update."""
    parsed = req.parsed

    if parsed.get("type") == "trade":
        results = []
        for t in parsed.get("trades", []):
            r = db_record_trade(
                action=t["action"],
                ticker=t["ticker"],
                shares=t["shares"],
                price=t["price"],
            )
            results.append(r)
        # Check for errors
        errors = [r for r in results if r.get("status") == "error"]
        if errors:
            return {"status": "error", "message": errors[0]["message"], "results": results}
        return {"status": "ok", "results": results}

    elif parsed.get("type") == "set_portfolio":
        result = db_set_portfolio(
            account_value=parsed.get("account_value", 0),
            cash=parsed.get("cash", 0),
            positions=parsed.get("positions", []),
        )
        return result

    else:
        return {"status": "error", "message": f"Unknown parsed type: {parsed.get('type')}"}


def _build_preview(parsed: dict, portfolio_data: dict) -> str:
    """Build a human-readable preview of the parsed trade intent."""
    cash = portfolio_data.get("cash", 0)
    existing_positions = {p["ticker"]: p for p in portfolio_data.get("positions", [])}

    if parsed.get("type") == "trade":
        lines = ["识别到以下交易：\n"]
        total_cost = 0
        for t in parsed.get("trades", []):
            action_zh = "买入" if t["action"] == "buy" else "卖出"
            value = t["shares"] * t["price"]
            total_cost += value if t["action"] == "buy" else -value
            lines.append(f"• {action_zh} {t['ticker']} {t['shares']}股 @ ${t['price']:.2f}  (${value:,.2f})")

            # Show position change
            existing = existing_positions.get(t["ticker"])
            if existing and t["action"] == "buy":
                new_shares = existing["shares"] + t["shares"]
                lines.append(f"  持仓: {existing['shares']}股 → {new_shares}股")
            elif existing and t["action"] == "sell":
                new_shares = existing["shares"] - t["shares"]
                lines.append(f"  持仓: {existing['shares']}股 → {new_shares}股")

        new_cash = cash - total_cost
        lines.append(f"\n现金: ${cash:,.2f} → ${new_cash:,.2f}")
        return "\n".join(lines)

    elif parsed.get("type") == "set_portfolio":
        lines = ["识别到设置完整仓位：\n"]
        lines.append(f"• 总资产: ${parsed.get('account_value', 0):,.2f}")
        lines.append(f"• 现金: ${parsed.get('cash', 0):,.2f}")
        for p in parsed.get("positions", []):
            lines.append(f"• {p['ticker']}: {p['shares']}股 @ ${p.get('avg_cost', 0):.2f}")
        lines.append(f"\n⚠️ 这将替换当前所有仓位数据")
        return "\n".join(lines)

    return "无法生成预览"
