"""Market-related API routes."""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.core.config_loader import (
    get_all_tickers,
    load_rules,
    load_watchlist,
)
from app.core.portfolio_db import get_portfolio_data
from app.core.llm_client import analyze_market
from app.core.market_data import fetch_snapshots
from app.core.models import MarketSummary, TickerSnapshot
from app.core.portfolio import analyze_portfolio
from app.core.report import generate_sleep_plan_with_prices
from app.core.scoring import build_market_summary
from app.core.report_dashboard import generate_dashboard_report
from app.core.stock_scorer import score_all_stocks
from app.core.limit_calculator import generate_daily_limits

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
    logger.info(f"[routes_market] _refresh_data called, {len(tickers)} tickers")
    watchlist = load_watchlist()
    rules = load_rules()

    snapshots = fetch_snapshots(tickers)
    summary = build_market_summary(snapshots, watchlist, rules)

    _cache["snapshots"] = snapshots
    _cache["summary"] = summary
    _cache["last_refresh"] = datetime.now(timezone.utc).isoformat()
    logger.info(f"[routes_market] Refresh done at {_cache['last_refresh']}")

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
    portfolio_data = get_portfolio_data()
    portfolio = analyze_portfolio(portfolio_data, snapshots)

    plan = generate_sleep_plan_with_prices(
        summary, portfolio, rules, watchlist, snapshots
    )
    result = plan.model_dump()
    if enhance:
        analysis = analyze_market(json.dumps(result, ensure_ascii=False, default=str), "sleep_plan")
        result["llm_analysis"] = analysis
    return result


@router.get("/daily-plan")
async def daily_plan():
    """Generate unified daily plan: market regime → scoring → limit prices → amounts.

    This is the 🎯 每日计划 endpoint combining:
    1. Market regime assessment
    2. Technical analysis (ATR, Fibonacci, support/resistance)
    3. Stock scoring (category + relative_strength + support + open)
    4. Limit price calculation (3-method median, 2 tiers)
    5. Order amount calculation (with position constraints)
    """
    from app.core.technical_analysis import analyze_batch_technical

    snapshots, summary = _get_or_refresh()
    rules = load_rules()
    watchlist = load_watchlist()
    portfolio_data = get_portfolio_data()
    portfolio = analyze_portfolio(portfolio_data, snapshots)
    account_value = portfolio.account_value or rules.get("account", {}).get("base_capital", 40000)

    # Get sector benchmark change for relative strength
    smh_snap = snapshots.get("SMH")
    sector_pct = smh_snap.pct_change_from_prev_close if smh_snap and not smh_snap.data_missing else 0.0

    # Run TA on all watchlist tickers
    all_tickers = [t for t in snapshots.keys() if not t.startswith("^")]
    ta_results = analyze_batch_technical(all_tickers)

    # Score all stocks
    scored = score_all_stocks(
        snapshots=snapshots,
        ta_results=ta_results,
        sector_pct_change=sector_pct,
        portfolio=portfolio,
        watchlist=watchlist,
    )

    # Exclude already-held tickers from daily plan candidates
    # (pullback-add in /api/exit-plan handles existing positions)
    held_tickers = {p.ticker for p in portfolio.positions if p.shares > 0}
    scored_new = [s for s in scored if s["ticker"] not in held_tickers]

    # Map market regime from summary to limit calculator regime
    regime_map = {
        "market_strong": "strong",
        "market_neutral": "neutral",
        "market_weak": "weak",
        "semi_strong_qqq_weak": "neutral",
    }
    market_regime = regime_map.get(summary.market_regime, "neutral")

    # Generate limit orders (only for non-held tickers)
    orders = generate_daily_limits(
        scored_stocks=scored_new,
        ta_results=ta_results,
        snapshots=snapshots,
        market_regime=market_regime,
        account_value=account_value,
        portfolio=portfolio,
    )

    return {
        "market_regime": summary.market_regime,
        "market_regime_label": {
            "market_strong": "强势",
            "market_neutral": "中性",
            "market_weak": "弱势",
            "semi_strong_qqq_weak": "半导体强/QQQ弱",
        }.get(summary.market_regime, "未知"),
        "sector_pct_change": round(sector_pct, 2),
        "scored_stocks": scored_new[:10],  # top 10 non-held by score
        "limit_orders": orders,
        "total_order_amount": sum(o["amount_l1"] for o in orders),
        "max_daily_amount": account_value * 0.30,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


@router.post("/refresh")
async def refresh():
    try:
        _refresh_data()
        return {"status": "ok", "refreshed_at": _cache["last_refresh"]}
    except Exception as e:
        logger.error(f"Refresh failed: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/exit-plan")
async def exit_plan():
    """Generate exit/trim/hold plan for all current positions.

    Complements /api/daily-plan (buy decisions) with sell/risk management:
    1. Classify each position (CORE/SEMI_CORE/CYCLICAL/HIGH_BETA/LEVERAGED_ETF)
    2. Evaluate stop-loss, MA breakdown, trailing profit, resistance, RSI
    3. Output action (HOLD/WATCH/TRIM_1_3/TRIM_1_2/REDUCE_2_3/EXIT)
    4. Portfolio-level risk assessment
    """
    from app.core.technical_analysis import analyze_batch_technical
    from app.core.exit_engine import generate_exit_plan
    from app.core.pullback_engine import generate_pullback_add_plan

    snapshots, summary = _get_or_refresh()
    watchlist = load_watchlist()
    portfolio_data = get_portfolio_data()
    portfolio = analyze_portfolio(portfolio_data, snapshots)

    # Run TA on all held tickers
    held_tickers = [p.ticker for p in portfolio.positions if p.shares > 0]
    # Also include SMH for relative strength
    ta_tickers = list(set(held_tickers + ["SMH"]))
    ta_results = analyze_batch_technical(ta_tickers)

    regime_map = {
        "market_strong": "STRONG",
        "market_neutral": "NEUTRAL",
        "market_weak": "WEAK",
        "semi_strong_qqq_weak": "NEUTRAL",
    }
    market_regime = regime_map.get(summary.market_regime, "NEUTRAL")

    result = generate_exit_plan(
        portfolio=portfolio,
        snapshots=snapshots,
        ta_results=ta_results,
        watchlist=watchlist,
        market_regime=market_regime,
    )

    # Merge pullback add plan into exit-plan response
    pullback_data = generate_pullback_add_plan(
        portfolio=portfolio,
        snapshots=snapshots,
        ta_results=ta_results,
        watchlist=watchlist,
    )
    result["addOnPullback"] = pullback_data

    result["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return result


@router.get("/pullback-add-plan")
async def pullback_add_plan():
    """Generate pullback add plan for all current positions.

    Evaluates whether existing holdings on pullback should be added to.
    Distinguishes buyable pullbacks from breakdowns.
    """
    from app.core.technical_analysis import analyze_batch_technical
    from app.core.pullback_engine import generate_pullback_add_plan

    snapshots, summary = _get_or_refresh()
    watchlist = load_watchlist()
    portfolio_data = get_portfolio_data()
    portfolio = analyze_portfolio(portfolio_data, snapshots)

    held_tickers = [p.ticker for p in portfolio.positions if p.shares > 0]
    ta_tickers = list(set(held_tickers + ["SMH"]))
    ta_results = analyze_batch_technical(ta_tickers)

    result = generate_pullback_add_plan(
        portfolio=portfolio,
        snapshots=snapshots,
        ta_results=ta_results,
        watchlist=watchlist,
    )
    return result


@router.get("/market/dashboard")
async def market_dashboard(enhance: bool = Query(False)):
    """Generate dashboard report with local technical analysis + optional LLM.

    - enhance=false: Pure local TA (MA/RSI/support/resistance) - fast, free
    - enhance=true: Local TA + LLM structured analysis per top mover - richer but slower
    """
    snapshots, summary = _get_or_refresh()
    rules = load_rules()
    portfolio_data = get_portfolio_data()
    portfolio = analyze_portfolio(portfolio_data, snapshots)

    report = generate_dashboard_report(
        summary=summary,
        snapshots=snapshots,
        portfolio=portfolio,
        rules=rules,
        use_llm=enhance,
    )
    return {"report": report, "generated_at": _cache.get("last_refresh")}


@router.get("/market/technical/{ticker}")
async def ticker_technical(ticker: str):
    """Get technical analysis for a single ticker (MA, RSI, MACD, support/resistance)."""
    from app.core.technical_analysis import analyze_ticker_technical

    result = analyze_ticker_technical(ticker.upper())
    if not result.data_available:
        return {"ticker": ticker.upper(), "error": result.error or "No data available"}
    return result.to_dict()


@router.get("/market/score/{ticker}")
async def ticker_score(ticker: str):
    """Score a single ticker for limit order candidacy.

    Works for any valid US stock ticker, not just watchlist stocks.
    Returns score, category, limit prices, and suggested amount.
    """
    from app.core.technical_analysis import analyze_ticker_technical
    from app.core.market_data import fetch_snapshots as fetch_single
    from app.core.stock_scorer import score_stock, get_category
    from app.core.limit_calculator import calculate_limit_prices, calculate_order_amount

    ticker = ticker.upper()
    snapshots, summary = _get_or_refresh()
    rules = load_rules()
    watchlist = load_watchlist()
    portfolio_data = get_portfolio_data()
    portfolio = analyze_portfolio(portfolio_data, snapshots)
    account_value = portfolio.account_value or rules.get("account", {}).get("base_capital", 40000)

    # Get snapshot - use cached if available, otherwise fetch
    snap = snapshots.get(ticker)
    if not snap:
        fetched = fetch_single([ticker])
        snap = fetched.get(ticker)
        if not snap:
            return {"ticker": ticker, "error": "无法获取价格数据"}

    # Run TA
    ta = analyze_ticker_technical(ticker)

    # Determine watchlist role
    role = "beta"
    for bucket_data in watchlist.get("buckets", {}).values():
        if ticker in bucket_data.get("tickers", []):
            role = bucket_data.get("role", "beta")
            break

    # Get sector benchmark
    smh_snap = snapshots.get("SMH")
    sector_pct = smh_snap.pct_change_from_prev_close if smh_snap and not smh_snap.data_missing else 0.0

    # Score
    scored = score_stock(ticker, snap, ta, sector_pct, portfolio, role)

    # Calculate limits
    price = ta.current_price if ta.data_available else snap.last_price
    category = scored["category"]
    limits = calculate_limit_prices(ticker, category, price, ta)

    # Market regime for amount calc
    regime_map = {
        "market_strong": "strong", "market_neutral": "neutral",
        "market_weak": "weak", "semi_strong_qqq_weak": "neutral",
    }
    market_regime = regime_map.get(summary.market_regime, "neutral")

    amounts = calculate_order_amount(
        ticker, category, market_regime, scored["score"], account_value, portfolio
    )

    return {
        "ticker": ticker,
        "current_price": round(price, 2),
        "score": scored["score"],
        "category": scored["category"],
        "chain": scored["chain"],
        "action": scored["action"],
        "reasons": scored["reasons"],
        "limit_1": limits["limit_1"],
        "limit_2": limits["limit_2"],
        "limit_methods": limits["methods"],
        "limit_reason": limits["reason"],
        "amount_l1": amounts["amount_l1"],
        "amount_l2": amounts["amount_l2"],
        "amount_multipliers": amounts["multipliers"],
        "capped_reason": amounts["capped_reason"],
        "ta": ta.to_dict() if ta.data_available else None,
    }


@router.post("/ai-exit-analysis")
async def ai_exit_analysis():
    """AI-enhanced exit analysis — DeepSeek explanation layer over /api/exit-plan.

    Consumes the deterministic exit-plan, runs pre-checks (exposure, conflicts,
    concentration), then calls DeepSeek to produce plain-English explanations
    and risk audit. Falls back to deterministic output if DeepSeek fails.
    """
    from app.core.technical_analysis import analyze_batch_technical
    from app.core.exit_engine import generate_exit_plan
    from app.core.ai_exit_analysis import generate_ai_exit_analysis
    from app.core.pullback_engine import generate_pullback_add_plan

    snapshots, summary = _get_or_refresh()
    watchlist = load_watchlist()
    portfolio_data = get_portfolio_data()
    portfolio = analyze_portfolio(portfolio_data, snapshots)

    # Run exit plan (same logic as GET /api/exit-plan)
    held_tickers = [p.ticker for p in portfolio.positions if p.shares > 0]
    ta_tickers = list(set(held_tickers + ["SMH"]))
    ta_results = analyze_batch_technical(ta_tickers)

    regime_map = {
        "market_strong": "STRONG",
        "market_neutral": "NEUTRAL",
        "market_weak": "WEAK",
        "semi_strong_qqq_weak": "NEUTRAL",
    }
    market_regime = regime_map.get(summary.market_regime, "NEUTRAL")

    exit_plan_data = generate_exit_plan(
        portfolio=portfolio,
        snapshots=snapshots,
        ta_results=ta_results,
        watchlist=watchlist,
        market_regime=market_regime,
    )

    # Build portfolio summary dict for AI analysis
    portfolio_dict = {
        "account_value": portfolio.account_value,
        "cash": portfolio.cash,
        "invested_value": portfolio.invested_value,
        "position_pct": portfolio.position_pct,
        "bucket_exposure": portfolio.bucket_exposure,
        "single_ticker_exposure": portfolio.single_ticker_exposure,
    }

    # Generate pullback add plan
    pullback_data = generate_pullback_add_plan(
        portfolio=portfolio,
        snapshots=snapshots,
        ta_results=ta_results,
        watchlist=watchlist,
    )

    # Generate AI-enhanced analysis
    result = generate_ai_exit_analysis(
        portfolio_summary=portfolio_dict,
        exit_plan=exit_plan_data,
        daily_plan=None,  # Could optionally fetch daily-plan here
        global_brief=None,  # Could optionally fetch global-brief here
        pullback_add_plan=pullback_data,
    )

    result["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return result
