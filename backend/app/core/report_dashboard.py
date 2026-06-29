"""Dashboard report renderer using Jinja2 + local technical indicators + optional LLM.

Flow:
1. Local technical analysis (MA, RSI, support/resistance) - always runs
2. Optional LLM structured analysis per ticker - enriches with sentiment/catalysts
3. Jinja2 template renders final report

This replaces the old string-concatenation report with a data-driven template approach.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from app.core.models import MarketSummary, PortfolioSummary, TickerSnapshot
from app.core.technical_analysis import TechnicalIndicators, analyze_batch_technical
from app.core.llm_client import analyze_structured

logger = logging.getLogger(__name__)

# Template directory
_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _signal_emoji(signal: str) -> str:
    return {"buy": "🟢", "hold": "🟡", "sell": "🔴", "avoid": "🔴"}.get(signal, "⚪")


def _trend_label(trend: str) -> str:
    return {"up": "多头排列", "down": "空头排列", "neutral": "震荡"}.get(trend, "—")


def _regime_label(regime: str) -> str:
    return {
        "market_strong": "🟢 市场强势",
        "market_weak": "🔴 市场弱势",
        "market_neutral": "🟡 市场中性",
        "semi_strong_qqq_weak": "🔄 半导体强/QQQ弱",
    }.get(regime, "❓ 未知")


def generate_dashboard_report(
    summary: MarketSummary,
    snapshots: dict[str, TickerSnapshot],
    portfolio: Optional[PortfolioSummary] = None,
    rules: Optional[dict] = None,
    use_llm: bool = False,
) -> str:
    """Generate dashboard report combining local TA + optional LLM analysis.

    Args:
        summary: Market summary from scoring engine
        snapshots: Raw ticker snapshots
        portfolio: Optional portfolio data for position sizing
        rules: Optional rules dict
        use_llm: Whether to call LLM for per-ticker structured analysis (slower but richer)

    Returns:
        Rendered report string (suitable for Telegram/console)
    """
    # Step 1: Run local technical analysis on all non-benchmark tickers
    analysis_tickers = [
        t for t in snapshots.keys()
        if not snapshots[t].data_missing and not t.startswith("^") and t not in ("QQQ", "SMH", "SOXX")
    ]

    logger.info(f"[dashboard] Running technical analysis on {len(analysis_tickers)} tickers")
    ta_results = analyze_batch_technical(analysis_tickers)

    # Step 2: Optional LLM structured analysis
    llm_results: dict[str, dict] = {}
    if use_llm:
        # Only analyze top movers (by absolute change) to save LLM calls
        sorted_by_move = sorted(
            analysis_tickers,
            key=lambda t: abs(snapshots[t].pct_change_from_prev_close),
            reverse=True,
        )
        llm_tickers = sorted_by_move[:10]  # Top 10 movers only

        for ticker in llm_tickers:
            snap = snapshots[ticker]
            ta = ta_results.get(ticker)
            if ta and ta.data_available:
                result = analyze_structured(
                    ticker=ticker,
                    snapshot_json=json.dumps(snap.model_dump(), default=str),
                    technical_json=json.dumps(ta.to_dict(), default=str),
                    market_regime=summary.market_regime,
                )
                if result:
                    llm_results[ticker] = result

    # Step 3: Build template context
    top_movers = []
    risk_alerts = []
    catalysts = []
    signal_counts = {"buy": 0, "hold": 0, "avoid": 0}

    # Sort by absolute pct change (biggest movers first)
    # Use TA data as fallback for sorting when snapshot price is 0
    def _sort_key(t: str) -> float:
        snap = snapshots[t]
        if snap.last_price > 0:
            return abs(snap.pct_change_from_prev_close)
        ta = ta_results.get(t)
        if ta and ta.data_available and ta.current_price > 0 and ta.prev_close > 0:
            return abs((ta.current_price - ta.prev_close) / ta.prev_close * 100)
        return 0.0

    sorted_tickers = sorted(
        analysis_tickers,
        key=_sort_key,
        reverse=True,
    )

    for ticker in sorted_tickers[:15]:  # Top 15 in report
        snap = snapshots[ticker]
        ta = ta_results.get(ticker)

        # Use TA price as fallback when snapshot has no real-time price (e.g. after hours)
        display_price = snap.last_price
        display_pct = snap.pct_change_from_prev_close
        if display_price <= 0 and ta and ta.data_available and ta.current_price > 0:
            display_price = ta.current_price
            if ta.prev_close > 0:
                display_pct = (ta.current_price - ta.prev_close) / ta.prev_close * 100
            else:
                display_pct = 0.0

        # Determine signal from LLM or local heuristic
        llm_data = llm_results.get(ticker)
        if llm_data:
            signal = llm_data.get("signal", "hold")
            # Collect risks and catalysts from LLM
            for r in llm_data.get("risks", []):
                risk_alerts.append(f"{ticker}: {r}")
            for c in llm_data.get("catalysts", []):
                catalysts.append(f"{ticker}: {c}")
        else:
            # Local signal heuristic
            signal = _local_signal(snap, ta)

        signal_counts[signal if signal in signal_counts else "hold"] += 1

        mover_data = {
            "ticker": ticker,
            "emoji": _signal_emoji(signal),
            "price": f"{display_price:.2f}",
            "pct_change": f"{display_pct:+.2f}",
            "rsi": f"{ta.rsi_14:.0f}" if ta and ta.data_available else "—",
            "trend_label": _trend_label(ta.trend) if ta and ta.data_available else "—",
            "support": f"{ta.nearest_support():.2f}" if ta and ta.nearest_support() else None,
            "resistance": f"{ta.nearest_resistance():.2f}" if ta and ta.nearest_resistance() else None,
        }
        top_movers.append(mover_data)

    # Bucket scores
    bucket_data = []
    for bs in summary.bucket_scores:
        tags = []
        if bs.stronger_than_smh:
            tags.append("强于SMH")
        if bs.stronger_than_soxx:
            tags.append("强于SOXX")
        bucket_data.append({
            "label": bs.label,
            "avg_pct": f"{bs.avg_pct_change:+.2f}",
            "emoji": "🟢" if bs.avg_pct_change > 0.5 else ("🔴" if bs.avg_pct_change < -0.5 else "🟡"),
            "tags": ", ".join(tags) if tags else "",
        })

    # Action suggestion
    action_suggestion = "观望"
    new_buy_cap = 0.0
    if portfolio and rules:
        from app.core.report import _get_action_suggestion
        action_suggestion, new_buy_cap = _get_action_suggestion(
            summary.market_regime, portfolio, rules.get("risk_rules", {})
        )

    # De-duplicate and limit
    risk_alerts = list(dict.fromkeys(risk_alerts))[:5]
    catalysts = list(dict.fromkeys(catalysts))[:5]

    # Render template
    bucket_lines = "\n".join(
        f"{b['emoji']} {b['label']}  {b['avg_pct']}%" + (f"  [{b['tags']}]" if b['tags'] else "")
        for b in bucket_data
    )

    template = _jinja_env.get_template("report_dashboard.j2")
    report = template.render(
        report_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        total_tickers=len(analysis_tickers),
        regime_label=_regime_label(summary.market_regime),
        signal_counts=signal_counts,
        top_movers=top_movers,
        risk_alerts=risk_alerts,
        catalysts=catalysts,
        bucket_lines=bucket_lines,
        add_candidates=[ts.ticker for ts in summary.add_candidates[:5]],
        avoid_tickers=[ts.ticker for ts in summary.do_not_buy[:5]],
        action_suggestion=action_suggestion,
        new_buy_cap=f"{new_buy_cap:.0f}",
        sleep_orders=[],  # Filled by caller if needed
    )

    return report


def _local_signal(snap: TickerSnapshot, ta: Optional[TechnicalIndicators]) -> str:
    """Determine signal from local data only (no LLM)."""
    if not ta or not ta.data_available:
        return "hold"

    # RSI extremes
    if ta.rsi_14 > 75:
        return "avoid"
    if ta.rsi_14 < 25 and ta.support_levels:
        return "buy"

    # Trend + momentum
    if ta.trend == "up" and snap.pct_change_from_prev_close > 1.0 and ta.volume_ratio > 1.3:
        return "buy"
    if ta.trend == "down" and snap.pct_change_from_prev_close < -2.0:
        return "avoid"

    # Default
    if snap.pct_change_from_prev_close > 0.5 and ta.trend == "up":
        return "buy"
    if snap.pct_change_from_prev_close < -1.0 and ta.trend == "down":
        return "avoid"

    return "hold"
