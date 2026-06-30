"""Chat API route with simple intent classification."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config_loader import (
    get_all_tickers,
    load_rules,
    load_watchlist,
)
from app.core.portfolio_db import get_portfolio_data
from app.core.llm_client import enhance_report, free_chat
from app.core.market_data import fetch_snapshots
from app.core.portfolio import analyze_portfolio
from app.core.report import (
    format_sleep_plan,
    generate_market_report,
    generate_sleep_plan_with_prices,
)
from app.core.scoring import build_market_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str
    market_regime: str = ""
    generated_at: str = ""


@router.post("/chat")
async def chat(req: ChatRequest):
    msg = req.message.strip()

    # Fetch data
    tickers = get_all_tickers()
    watchlist = load_watchlist()
    rules = load_rules()
    portfolio_data = get_portfolio_data()

    snapshots = fetch_snapshots(tickers)
    summary = build_market_summary(snapshots, watchlist, rules)
    portfolio = analyze_portfolio(portfolio_data, snapshots)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Simple intent classification
    if any(kw in msg for kw in ["睡觉", "limit", "睡前", "挂单"]):
        plan = generate_sleep_plan_with_prices(
            summary, portfolio, rules, watchlist, snapshots
        )
        answer = format_sleep_plan(plan)
    elif any(kw in msg for kw in ["不能接", "avoid", "不要买", "别碰"]):
        if summary.do_not_buy:
            lines = ["低于开盘价且接近日低，不建议接入:"]
            for ts in summary.do_not_buy:
                lines.append(f"  {ts.ticker}")
        else:
            lines = ["当前暂无明显不能接的标的。"]
        answer = "\n".join(lines)
    elif any(kw in msg for kw in ["能加", "加仓", "可以买", "候选"]):
        # Check if user is asking about specific tickers
        import re
        mentioned_tickers = re.findall(r'(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])', msg)
        if mentioned_tickers:
            # User asking about specific tickers — use AI with full context
            from app.core.trade_history_context import build_all_contexts
            from app.core.technical_analysis import analyze_batch_technical

            trade_contexts = build_all_contexts()
            ta_results = analyze_batch_technical(mentioned_tickers)

            position_lines = []
            for pos in portfolio.positions:
                if pos.shares > 0:
                    snap = snapshots.get(pos.ticker)
                    current = snap.last_price if snap and not snap.data_missing else 0
                    pnl_pct = ((current - pos.avg_cost) / pos.avg_cost * 100) if pos.avg_cost > 0 and current > 0 else 0
                    position_lines.append(
                        f"  {pos.ticker}: {pos.shares}股 成本${pos.avg_cost:.2f} 现价${current:.2f} {pnl_pct:+.1f}%"
                    )

            ctx_lines = []
            for ticker in mentioned_tickers:
                ctx = trade_contexts.get(ticker)
                if ctx:
                    tags = []
                    if ctx.recently_added: tags.append("近期加仓过")
                    if ctx.recently_trimmed: tags.append("近期减仓过")
                    if ctx.cooldown_until: tags.append(f"冷却至{ctx.cooldown_until}")
                    if ctx.adds_last_10_days: tags.append(f"10日内加仓{ctx.adds_last_10_days}次")
                    if tags:
                        ctx_lines.append(f"  {ticker}: {' | '.join(tags)}")

                ta = ta_results.get(ticker)
                if ta:
                    rsi = getattr(ta, 'rsi_14', None) or 'N/A'
                    ma20 = getattr(ta, 'ma20', None) or 'N/A'
                    trend = getattr(ta, 'trend', None) or 'N/A'
                    ctx_lines.append(f"  {ticker} 技术: RSI={rsi} MA20={ma20} 趋势={trend}")

            import json
            full_context = json.dumps({
                "market_regime": summary.market_regime,
                "account_value": portfolio.account_value,
                "cash": portfolio.cash,
                "cash_pct": (portfolio.cash / portfolio.account_value * 100) if portfolio.account_value else 0,
                "positions": position_lines,
                "trade_history_context": ctx_lines,
                "question_tickers": mentioned_tickers,
            }, ensure_ascii=False, indent=2)

            system_prompt = (
                "你是一个专业的AI半导体产业链投资组合助手。用户想了解特定标的的加仓建议。"
                "请基于以下数据给出具体的加仓建议，包括：\n"
                "1. 当前仓位权重是否过高/过低\n"
                "2. 建议加仓金额（考虑现金余额和仓位平衡）\n"
                "3. 建议的入场价位（参考技术面）\n"
                "4. 风险提示（是否处于冷却期、是否反复加仓）\n"
                "回答要简洁有数据支撑，给出具体数字。这不是投资建议，仅供参考。"
            )
            answer = free_chat(msg, full_context)
        else:
            # Generic "加仓" query — show add candidates
            if summary.add_candidates:
                lines = ["高于开盘价且接近日高，可关注加仓:"]
                for ts in summary.add_candidates:
                    lines.append(f"  {ts.ticker}")
            else:
                lines = ["当前暂无明显加仓候选。"]
            answer = "\n".join(lines)
    elif any(kw in msg for kw in ["强势", "强链路", "哪个板块强", "强于"]):
        strong_buckets = [
            bs for bs in summary.bucket_scores
            if bs.stronger_than_smh or bs.stronger_than_soxx
        ]
        if strong_buckets:
            lines = ["强于板块的 AI 链路:"]
            for bs in strong_buckets:
                lines.append(f"  {bs.label}: 均涨 {bs.avg_pct_change:+.2f}%")
        else:
            lines = ["当前暂无明显强于板块的链路。"]
        answer = "\n".join(lines)
    elif any(kw in msg for kw in ["光通信", "光互连"]):
        answer = _filter_bucket_report(summary, snapshots, "optical_interconnect")
    elif any(kw in msg for kw in ["半导体设备", "设备"]):
        answer = _filter_bucket_report(summary, snapshots, "core_ai_semis")
    elif any(kw in msg for kw in ["报告", "盯盘", "总结", "overview"]):
        # Full report
        plan = generate_sleep_plan_with_prices(
            summary, portfolio, rules, watchlist, snapshots
        )
        report = generate_market_report(
            summary, portfolio, rules,
            include_sleep_plan=True, sleep_plan=plan
        )
        answer = enhance_report(report)
    else:
        # Free chat with market context + portfolio + RAG knowledge retrieval
        import json
        from app.core.vector_store import search_knowledge
        from app.core.trade_history_context import build_all_contexts

        # Build portfolio context
        position_lines = []
        for pos in portfolio.positions:
            if pos.shares > 0:
                snap = snapshots.get(pos.ticker)
                current = snap.last_price if snap and not snap.data_missing else 0
                pnl_pct = ((current - pos.avg_cost) / pos.avg_cost * 100) if pos.avg_cost > 0 and current > 0 else 0
                position_lines.append(f"{pos.ticker}: {pos.shares}股 成本${pos.avg_cost:.2f} 现${current:.2f} {pnl_pct:+.1f}%")

        # Trade history context for mentioned tickers
        import re
        mentioned_tickers = re.findall(r'(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])', msg)
        trade_ctx_lines = []
        if mentioned_tickers:
            trade_contexts = build_all_contexts()
            for ticker in mentioned_tickers:
                ctx = trade_contexts.get(ticker)
                if ctx:
                    tags = []
                    if ctx.recently_added: tags.append("近期加仓")
                    if ctx.recently_trimmed: tags.append("近期减仓")
                    if ctx.cooldown_until: tags.append(f"冷却至{ctx.cooldown_until}")
                    if tags:
                        trade_ctx_lines.append(f"{ticker}: {' | '.join(tags)}")

        market_context = json.dumps({
            "market_regime": summary.market_regime,
            "bucket_scores": [{"name": bs.label, "avg_pct": bs.avg_pct_change} for bs in summary.bucket_scores],
            "portfolio": {
                "account_value": portfolio.account_value,
                "cash": portfolio.cash,
                "positions": position_lines,
            },
            "trade_activity": trade_ctx_lines if trade_ctx_lines else None,
        }, ensure_ascii=False)

        # Retrieve relevant knowledge from vector store
        relevant_docs = search_knowledge(msg, top_k=3)
        knowledge_context = ""
        if relevant_docs:
            knowledge_context = "\n\n相关策略知识:\n" + "\n".join(
                f"- {doc['text']}" for doc in relevant_docs
            )

        answer = free_chat(msg, market_context + knowledge_context)

    return ChatResponse(
        answer=answer,
        market_regime=summary.market_regime,
        generated_at=now_str,
    )


def _filter_bucket_report(
    summary, snapshots, bucket_name: str
) -> str:
    """Generate report for a specific bucket."""
    for bs in summary.bucket_scores:
        if bs.bucket_name == bucket_name:
            lines = [f"{bs.label} ({bs.bucket_name})"]
            lines.append(f"均涨幅: {bs.avg_pct_change:+.2f}%")
            tags = []
            if bs.stronger_than_smh:
                tags.append("强于SMH")
            if bs.stronger_than_soxx:
                tags.append("强于SOXX")
            if tags:
                lines.append(f"状态: {', '.join(tags)}")
            lines.append("")
            lines.append("成分股:")
            for t in bs.tickers:
                snap = snapshots.get(t)
                if snap and not snap.data_missing:
                    lines.append(
                        f"  {t}: {snap.pct_change_from_prev_close:+.2f}% "
                        f"(开盘{'↑' if snap.last_price > snap.open_price else '↓'}"
                        f" 日高{snap.pct_from_day_high:.2f}%)"
                    )
                else:
                    lines.append(f"  {t}: 数据缺失")
            return "\n".join(lines)
    return f"未找到板块: {bucket_name}"
