"""Market-related API routes."""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.core.config_loader import (
    get_all_tickers,
    load_portfolio,
    load_rules,
    load_watchlist,
)
from app.core.llm_client import analyze_market
from app.core.market_data import fetch_snapshots
from app.core.models import MarketSummary, TickerSnapshot
from app.core.portfolio import analyze_portfolio
from app.core.report import generate_sleep_plan_with_prices
from app.core.scoring import build_market_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Simple in-memory cache (extensible later)
_cache: dict = {
    "snapshots": None,
    "summary": None,
    "last_refresh": None,
}


def _refresh_data() -> tuple[dict[str, TickerSnapshot], MarketSummary]:
    """Refresh market data and build summary."""
    tickers = get_all_tickers()
    watchlist = load_watchlist()
    rules = load_rules()

    snapshots = fetch_snapshots(tickers)
    summary = build_market_summary(snapshots, watchlist, rules)

    _cache["snapshots"] = snapshots
    _cache["summary"] = summary
    _cache["last_refresh"] = datetime.now(timezone.utc).isoformat()

    return snapshots, summary


def _get_or_refresh() -> tuple[dict[str, TickerSnapshot], MarketSummary]:
    """Get cached data or refresh."""
    if _cache["summary"] is None:
        return _refresh_data()
    return _cache["snapshots"], _cache["summary"]


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "ai-chain-watchlist-mvp",
        "last_refresh": _cache.get("last_refresh"),
    }


@router.get("/market/summary")
async def market_summary(enhance: bool = Query(False)):
    snapshots, summary = _get_or_refresh()
    result = summary.model_dump()
    if enhance:
        analysis = analyze_market(json.dumps(result, ensure_ascii=False, default=str), "market")
        result["llm_analysis"] = analysis
    return result


@router.get("/watchlist")
async def get_watchlist():
    watchlist = load_watchlist()
    return watchlist


@router.get("/sleep-plan")
async def sleep_plan(enhance: bool = Query(False)):
    snapshots, summary = _get_or_refresh()
    rules = load_rules()
    watchlist = load_watchlist()
    portfolio_data = load_portfolio()
    portfolio = analyze_portfolio(portfolio_data, snapshots)

    plan = generate_sleep_plan_with_prices(
        summary, portfolio, rules, watchlist, snapshots
    )
    result = plan.model_dump()
    if enhance:
        analysis = analyze_market(json.dumps(result, ensure_ascii=False, default=str), "sleep_plan")
        result["llm_analysis"] = analysis
    return result


@router.post("/refresh")
async def refresh():
    try:
        _refresh_data()
        return {"status": "ok", "refreshed_at": _cache["last_refresh"]}
    except Exception as e:
        logger.error(f"Refresh failed: {e}")
        return {"status": "error", "message": str(e)}
