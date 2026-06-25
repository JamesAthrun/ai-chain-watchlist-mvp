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
        # Free chat with market context + RAG knowledge retrieval
        import json
        from app.core.vector_store import search_knowledge

        market_context = json.dumps({
            "market_regime": summary.market_regime,
            "benchmark_strength": {k: v for k, v in summary.benchmark_strength.items()} if hasattr(summary, 'benchmark_strength') else {},
            "bucket_scores": [{"name": bs.label, "avg_pct": bs.avg_pct_change} for bs in summary.bucket_scores],
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
