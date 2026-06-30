"""Decision Center API — unified view of all active decisions with conflict detection.

GET /api/decisions — aggregates daily-plan, exit-plan, pullback-add, and trade history
into a single response with conflicts highlighted.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.conflict_detector import detect_conflicts
from app.core.trade_history_context import build_all_contexts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/decisions")
async def get_decisions():
    """Unified decision center — aggregates all engine outputs + conflict detection.

    Returns:
        - active_buy_plans: Current daily plan limit orders
        - exit_signals: Positions with non-HOLD actions
        - pullback_candidates: Symbols eligible for pullback-add
        - conflicts: Detected contradictions between engines
        - trade_history: Recent activity context per symbol
        - summary: Quick stats
    """
    from app.core.portfolio_db import get_portfolio_data
    from app.core.portfolio import analyze_portfolio

    # Import the route handlers to reuse their logic
    from app.api.routes_market import _get_or_refresh, _cache

    # Get market data (use cache if available)
    try:
        snapshots, summary = _get_or_refresh()
    except Exception as e:
        logger.error(f"Decision center: market data unavailable: {e}")
        return {"error": "Market data unavailable", "message": str(e)}

    # Get portfolio
    portfolio_data = get_portfolio_data()
    portfolio = analyze_portfolio(portfolio_data, snapshots)

    # Build trade history contexts
    trade_contexts = build_all_contexts()
    trade_ctx_dict = {}
    for symbol, ctx in trade_contexts.items():
        trade_ctx_dict[symbol] = {
            "recently_added": ctx.recently_added,
            "recently_trimmed": ctx.recently_trimmed,
            "recently_sold": ctx.recently_sold,
            "cooldown_until": ctx.cooldown_until,
            "adds_last_10_days": ctx.adds_last_10_days,
            "trims_last_10_days": ctx.trims_last_10_days,
            "last_buy_price": ctx.last_buy_price,
            "last_sell_price": ctx.last_sell_price,
            "realized_pnl": ctx.realized_pnl,
        }

    # Gather engine outputs (lightweight — reuse cached market data)
    daily_plan = None
    exit_plan_data = None
    pullback_data = None

    try:
        from app.core.technical_analysis import analyze_batch_technical
        from app.core.stock_scorer import score_all_stocks
        from app.core.limit_calculator import generate_daily_limits
        from app.core.config_loader import load_rules, load_watchlist
        from app.core.exit_engine import generate_exit_plan
        from app.core.pullback_engine import generate_pullback_add_plan
        from app.core.trade_history_context import is_in_cooldown

        rules = load_rules()
        watchlist = load_watchlist()
        account_value = portfolio.account_value or rules.get("account", {}).get("base_capital", 40000)

        # --- Daily plan ---
        smh_snap = snapshots.get("SMH")
        sector_pct = smh_snap.pct_change_from_prev_close if smh_snap and not smh_snap.data_missing else 0.0
        all_tickers = [t for t in snapshots.keys() if not t.startswith("^")]
        ta_results = analyze_batch_technical(all_tickers)

        scored = score_all_stocks(
            snapshots=snapshots,
            ta_results=ta_results,
            sector_pct_change=sector_pct,
            portfolio=portfolio,
            watchlist=watchlist,
        )

        held_tickers = {p.ticker for p in portfolio.positions if p.shares > 0}
        scored_new = [s for s in scored if s["ticker"] not in held_tickers]

        # Cooldown filter
        filtered_scored = []
        for s in scored_new:
            ctx = trade_contexts.get(s["ticker"])
            if ctx:
                in_cd, _ = is_in_cooldown(ctx)
                if in_cd:
                    continue
            filtered_scored.append(s)

        regime_map = {"market_strong": "strong", "market_neutral": "neutral", "market_weak": "weak", "semi_strong_qqq_weak": "neutral"}
        market_regime = regime_map.get(summary.market_regime, "neutral")

        orders = generate_daily_limits(
            scored_stocks=filtered_scored,
            ta_results=ta_results,
            snapshots=snapshots,
            market_regime=market_regime,
            account_value=account_value,
            portfolio=portfolio,
        )

        daily_plan = {
            "market_regime": summary.market_regime,
            "limit_orders": orders,
            "total_order_amount": sum(o["amount_l1"] for o in orders),
            "max_daily_amount": account_value * 0.30,
        }

        # --- Exit plan ---
        held_list = [p.ticker for p in portfolio.positions if p.shares > 0]
        ta_held = analyze_batch_technical(list(set(held_list + ["SMH"])))

        exit_regime_map = {"market_strong": "STRONG", "market_neutral": "NEUTRAL", "market_weak": "WEAK", "semi_strong_qqq_weak": "NEUTRAL"}

        exit_plan_data = generate_exit_plan(
            portfolio=portfolio,
            snapshots=snapshots,
            ta_results=ta_held,
            watchlist=watchlist,
            market_regime=exit_regime_map.get(summary.market_regime, "NEUTRAL"),
        )

        # --- Pullback plan ---
        pullback_data = generate_pullback_add_plan(
            portfolio=portfolio,
            snapshots=snapshots,
            ta_results=ta_held,
            watchlist=watchlist,
        )

    except Exception as e:
        logger.error(f"Decision center engine error: {e}")

    # --- Conflict detection ---
    conflicts = detect_conflicts(
        daily_plan=daily_plan,
        exit_plan=exit_plan_data,
        pullback_plan=pullback_data,
        trade_contexts=trade_contexts,
        portfolio_summary=portfolio,
    )

    # --- Build response ---
    active_buy_plans = daily_plan.get("limit_orders", []) if daily_plan else []

    exit_signals = []
    if exit_plan_data:
        for pos in exit_plan_data.get("positions", []):
            if pos.get("action", "HOLD") != "HOLD":
                exit_signals.append({
                    "symbol": pos.get("symbol"),
                    "action": pos.get("action"),
                    "urgency": pos.get("urgency", "NORMAL"),
                    "reasoning": pos.get("reasoning", [])[:2],
                })

    pullback_candidates = []
    if pullback_data:
        for plan in pullback_data.get("plans", []):
            if plan.get("action") in ("ADD_SMALL", "ADD_NORMAL", "ADD_AGGRESSIVE"):
                pullback_candidates.append({
                    "symbol": plan.get("symbol"),
                    "action": plan.get("action"),
                    "pullbackStatus": plan.get("pullbackStatus"),
                    "addLimits": plan.get("addLimits", []),
                    "in_cooldown": trade_contexts.get(plan.get("symbol"), None) is not None and
                                   is_in_cooldown(trade_contexts.get(plan.get("symbol")))[0],
                })

    return {
        "active_buy_plans": active_buy_plans,
        "exit_signals": exit_signals,
        "pullback_candidates": pullback_candidates,
        "conflicts": [c.model_dump() for c in conflicts],
        "trade_history": trade_ctx_dict,
        "summary": {
            "market_regime": summary.market_regime if daily_plan else None,
            "total_buy_orders": len(active_buy_plans),
            "total_buy_amount": daily_plan.get("total_order_amount", 0) if daily_plan else 0,
            "exit_signal_count": len(exit_signals),
            "pullback_add_count": len(pullback_candidates),
            "conflict_count": len(conflicts),
            "high_severity_conflicts": sum(1 for c in conflicts if c.severity == "HIGH"),
            "held_positions": len(held_tickers) if daily_plan else 0,
            "cash_available": portfolio.cash if portfolio else 0,
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
