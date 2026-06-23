"""Portfolio API routes."""

from fastapi import APIRouter

from app.core.config_loader import load_portfolio
from app.core.portfolio import analyze_portfolio

router = APIRouter(prefix="/api")


@router.get("/portfolio")
async def get_portfolio():
    portfolio_data = load_portfolio()
    summary = analyze_portfolio(portfolio_data)
    return summary.model_dump()
