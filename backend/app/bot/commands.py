"""Telegram bot command handlers."""

import logging

from app.core.config_loader import (
    get_all_tickers,
    load_portfolio,
    load_rules,
    load_watchlist,
)
from app.core.llm_client import enhance_report
from app.core.market_data import fetch_snapshots
from app.core.portfolio import analyze_portfolio
from app.core.report import (
    format_sleep_plan,
    generate_market_report,
    generate_sleep_plan_with_prices,
)
from app.core.scoring import build_market_summary

logger = logging.getLogger(__name__)


def _fetch_all():
    """Fetch all data and build summary."""
    tickers = get_all_tickers()
    watchlist = load_watchlist()
    rules = load_rules()
    portfolio_data = load_portfolio()

    snapshots = fetch_snapshots(tickers)
    summary = build_market_summary(snapshots, watchlist, rules)
    portfolio = analyze_portfolio(portfolio_data, snapshots)

    return snapshots, summary, portfolio, watchlist, rules


def handle_summary() -> str:
    """Handle /summary command."""
    try:
        snapshots, summary, portfolio, watchlist, rules = _fetch_all()
        report = generate_market_report(summary, portfolio, rules)
        return enhance_report(report)
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return f"生成报告时出错: {e}"


def handle_sleep() -> str:
    """Handle /sleep command."""
    try:
        snapshots, summary, portfolio, watchlist, rules = _fetch_all()
        plan = generate_sleep_plan_with_prices(
            summary, portfolio, rules, watchlist, snapshots
        )
        return format_sleep_plan(plan)
    except Exception as e:
        logger.error(f"Error generating sleep plan: {e}")
        return f"生成睡觉计划时出错: {e}"


def handle_strong() -> str:
    """Handle /strong command."""
    try:
        snapshots, summary, portfolio, watchlist, rules = _fetch_all()
        strong_buckets = [
            bs for bs in summary.bucket_scores
            if bs.stronger_than_smh or bs.stronger_than_soxx
        ]
        if strong_buckets:
            lines = ["强于板块的 AI 链路:"]
            for bs in strong_buckets:
                tags = []
                if bs.stronger_than_smh:
                    tags.append("强于SMH")
                if bs.stronger_than_soxx:
                    tags.append("强于SOXX")
                lines.append(f"  {bs.label}: 均涨 {bs.avg_pct_change:+.2f}% [{', '.join(tags)}]")
            return "\n".join(lines)
        return "当前暂无明显强于板块的链路。"
    except Exception as e:
        logger.error(f"Error: {e}")
        return f"出错: {e}"


def handle_avoid() -> str:
    """Handle /avoid command."""
    try:
        snapshots, summary, portfolio, watchlist, rules = _fetch_all()
        if summary.do_not_buy:
            lines = ["低于开盘价且接近日低，不建议接入:"]
            for ts in summary.do_not_buy:
                lines.append(f"  {ts.ticker}")
            return "\n".join(lines)
        return "当前暂无明显不能接的标的。"
    except Exception as e:
        logger.error(f"Error: {e}")
        return f"出错: {e}"


def handle_portfolio() -> str:
    """Handle /portfolio command."""
    try:
        portfolio_data = load_portfolio()
        portfolio = analyze_portfolio(portfolio_data)
        lines = [
            "持仓概览:",
            f"  账户总值: ${portfolio.account_value:.0f}",
            f"  现金: ${portfolio.cash:.0f} ({portfolio.cash_pct:.1f}%)",
            f"  持仓: ${portfolio.invested_value:.0f} ({portfolio.position_pct:.1f}%)",
        ]
        if portfolio.positions:
            lines.append("")
            lines.append("持仓明细:")
            for pos in portfolio.positions:
                lines.append(
                    f"  {pos.ticker}: ${pos.current_value:.0f} ({pos.pct_of_account:.1f}%)"
                )
        else:
            lines.append("  (空仓)")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error: {e}")
        return f"出错: {e}"


def handle_natural_language(text: str) -> str:
    """Handle natural language messages."""
    if any(kw in text for kw in ["睡觉", "limit", "睡前", "挂单"]):
        return handle_sleep()
    elif any(kw in text for kw in ["不能接", "avoid", "不要买", "别碰"]):
        return handle_avoid()
    elif any(kw in text for kw in ["能加", "加仓", "可以买", "候选"]):
        try:
            snapshots, summary, portfolio, watchlist, rules = _fetch_all()
            if summary.add_candidates:
                lines = ["高于开盘价且接近日高，可关注加仓:"]
                for ts in summary.add_candidates:
                    lines.append(f"  {ts.ticker}")
                return "\n".join(lines)
            return "当前暂无明显加仓候选。"
        except Exception as e:
            return f"出错: {e}"
    elif any(kw in text for kw in ["强势", "强链路", "哪个板块强"]):
        return handle_strong()
    elif any(kw in text for kw in ["光通信", "光互连"]):
        return _handle_bucket_query("optical_interconnect")
    elif any(kw in text for kw in ["半导体设备", "设备"]):
        return _handle_bucket_query("core_ai_semis")
    else:
        return handle_summary()


def _handle_bucket_query(bucket_name: str) -> str:
    """Handle a query about a specific bucket."""
    try:
        snapshots, summary, portfolio, watchlist, rules = _fetch_all()
        for bs in summary.bucket_scores:
            if bs.bucket_name == bucket_name:
                lines = [f"{bs.label}"]
                lines.append(f"均涨幅: {bs.avg_pct_change:+.2f}%")
                tags = []
                if bs.stronger_than_smh:
                    tags.append("强于SMH")
                if bs.stronger_than_soxx:
                    tags.append("强于SOXX")
                if tags:
                    lines.append(f"状态: {', '.join(tags)}")
                lines.append("")
                for t in bs.tickers:
                    snap = snapshots.get(t)
                    if snap and not snap.data_missing:
                        lines.append(
                            f"  {t}: {snap.pct_change_from_prev_close:+.2f}%"
                        )
                    else:
                        lines.append(f"  {t}: 数据缺失")
                return "\n".join(lines)
        return f"未找到板块: {bucket_name}"
    except Exception as e:
        return f"出错: {e}"
