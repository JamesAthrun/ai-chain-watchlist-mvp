"""Report generation module."""

from datetime import datetime, timezone

from app.core.models import (
    MarketSummary,
    PortfolioSummary,
    SleepLimitOrder,
    SleepPlan,
    TickerSnapshot,
)
from app.core.config_loader import get_bucket_label, get_bucket_role, get_bucket_for_ticker


def generate_market_report(
    summary: MarketSummary,
    portfolio: PortfolioSummary,
    rules: dict,
    include_sleep_plan: bool = False,
    sleep_plan: "SleepPlan | None" = None,
) -> str:
    """Generate Chinese market report."""
    lines: list[str] = []
    lines.append("=" * 40)
    lines.append("AI 产业链盯盘报告")
    lines.append(f"生成时间: {summary.generated_at}")
    lines.append("=" * 40)

    # 1. Market regime
    regime_labels = {
        "market_strong": "市场强势 ✅",
        "market_weak": "市场弱势 ⚠️",
        "market_neutral": "市场中性 ➖",
        "semi_strong_qqq_weak": "半导体强但QQQ弱 🔄",
        "unknown": "未知",
    }
    lines.append("")
    lines.append("【1. 市场总判断】")
    lines.append(f"  {regime_labels.get(summary.market_regime, summary.market_regime)}")

    # 2. Benchmark strength
    lines.append("")
    lines.append("【2. QQQ / SMH / SOXX 强弱】")
    strength_labels = {"strong": "强", "weak": "弱", "neutral": "中性", "unknown": "未知"}
    for bm, s in summary.benchmark_strength.items():
        lines.append(f"  {bm}: {strength_labels.get(s, s)}")

    # NVDA indicator
    if summary.nvda_status and not summary.nvda_status.data_missing:
        nvda = summary.nvda_status
        lines.append(f"  NVDA(风向标): {nvda.pct_change_from_prev_close:+.2f}%")

    # 3. Strong buckets
    lines.append("")
    lines.append("【3. 强于板块的 AI 链路】")
    strong_buckets = [
        bs for bs in summary.bucket_scores
        if bs.stronger_than_smh or bs.stronger_than_soxx
    ]
    if strong_buckets:
        for bs in strong_buckets:
            tags = []
            if bs.stronger_than_smh:
                tags.append("强于SMH")
            if bs.stronger_than_soxx:
                tags.append("强于SOXX")
            lines.append(f"  {bs.label} ({bs.bucket_name}): 均涨 {bs.avg_pct_change:+.2f}% [{', '.join(tags)}]")
    else:
        lines.append("  暂无明显强于板块的链路")

    # 4. Add candidates
    lines.append("")
    lines.append("【4. 高于开盘价并接近日高（可关注加仓）】")
    if summary.add_candidates:
        for ts in summary.add_candidates:
            lines.append(f"  {ts.ticker}")
    else:
        lines.append("  暂无")

    # 5. Do not buy
    lines.append("")
    lines.append("【5. 低于开盘价并接近日低（不能接）】")
    if summary.do_not_buy:
        for ts in summary.do_not_buy:
            lines.append(f"  {ts.ticker}")
    else:
        lines.append("  暂无")

    # 6. Position action
    lines.append("")
    lines.append("【6. 仓位与动作建议】")
    risk_rules = rules.get("risk_rules", {})
    action_text, new_buy_cap = _get_action_suggestion(
        summary.market_regime, portfolio, risk_rules
    )
    lines.append(f"  结论: {action_text}")
    lines.append(f"  新买入资金上限: ${new_buy_cap:.0f}")
    lines.append(f"  当前现金: ${portfolio.cash:.0f} ({portfolio.cash_pct:.1f}%)")
    lines.append(f"  当前仓位: ${portfolio.invested_value:.0f} ({portfolio.position_pct:.1f}%)")

    # 7. Sleep plan
    if include_sleep_plan and sleep_plan:
        lines.append("")
        lines.append("【7. 睡觉 Limit Plan】")
        lines.append(format_sleep_plan(sleep_plan))
    else:
        lines.append("")
        lines.append("【7. 睡觉 Limit Plan】")
        lines.append("  (未生成，使用 /sleep 命令查看)")

    # 8. Risk notice
    lines.append("")
    lines.append("【8. 风险提示】")
    lines.append("  提示：本报告只用于个人盯盘和交易计划整理，不构成投资建议，也不会自动下单。")

    return "\n".join(lines)


def _get_action_suggestion(
    market_regime: str,
    portfolio: PortfolioSummary,
    risk_rules: dict,
) -> tuple[str, float]:
    """Get action suggestion and new buy cap."""
    account_value = portfolio.account_value
    cash = portfolio.cash

    if market_regime == "market_weak":
        text = "等 / 减弱留强"
        regime_cap = account_value * risk_rules.get("max_new_buy_if_market_weak_pct", 0.15)
    elif market_regime == "semi_strong_qqq_weak":
        text = "只小仓买半导体和电力基建强势回踩"
        regime_cap = account_value * risk_rules.get("max_new_buy_if_market_neutral_pct", 0.30)
    elif market_regime == "market_neutral":
        text = "轻仓试，等确认"
        regime_cap = account_value * risk_rules.get("max_new_buy_if_market_neutral_pct", 0.30)
    elif market_regime == "market_strong":
        text = "可以加仓，但不追高"
        regime_cap = account_value * risk_rules.get("max_new_buy_if_market_strong_pct", 0.45)
    else:
        text = "数据不足，观望"
        regime_cap = 0.0

    actual_cap = min(cash, regime_cap)
    return text, actual_cap


def generate_sleep_plan(
    summary: MarketSummary,
    portfolio: PortfolioSummary,
    rules: dict,
    watchlist: dict,
) -> SleepPlan:
    """Generate sleep limit order plan."""
    risk_rules = rules.get("risk_rules", {})
    sleep_rules = rules.get("sleep_limit_rules", {})

    max_pending = portfolio.account_value * risk_rules.get(
        "sleep_mode_max_pending_orders_pct", 0.30
    )

    core_discounts = sleep_rules.get("strong_core_discount_from_prev_close_pct", [1.5, 3.0])
    beta_discounts = sleep_rules.get("beta_discount_from_prev_close_pct", [4.0, 7.0])
    high_beta_discounts = sleep_rules.get("high_beta_discount_from_prev_close_pct", [8.0, 12.0])

    # Collect candidates: add_candidates + tickers in strong buckets
    candidate_tickers: set[str] = set()
    for ts in summary.add_candidates:
        candidate_tickers.add(ts.ticker)

    # Add tickers from strong buckets
    for bs in summary.bucket_scores:
        if bs.stronger_than_smh or bs.stronger_than_soxx:
            for t in bs.tickers:
                candidate_tickers.add(t)

    # Remove do_not_buy and NVDA
    do_not_buy_tickers = {ts.ticker for ts in summary.do_not_buy}
    candidate_tickers -= do_not_buy_tickers
    candidate_tickers.discard("NVDA")

    orders: list[SleepLimitOrder] = []
    total_amount = 0.0

    for ticker in sorted(candidate_tickers):
        if total_amount >= max_pending:
            break

        buckets = get_bucket_for_ticker(ticker)
        if not buckets:
            continue

        bucket_name = buckets[0]
        role = get_bucket_role(bucket_name)
        label = get_bucket_label(bucket_name)

        # Determine discounts and max dollars based on role
        if role == "core":
            discounts = core_discounts
            max_dollars = min(2000.0, max_pending - total_amount)
        elif role == "high_beta":
            discounts = high_beta_discounts
            max_dollars = min(500.0, max_pending - total_amount)
        else:  # beta
            discounts = beta_discounts
            max_dollars = min(1000.0, max_pending - total_amount)

        if max_dollars <= 0:
            break

        # Find prev_close for this ticker from nvda_status or summary
        # We need snapshots; use the add_candidates info
        # For now, generate discount from a reference price
        # We'll use the bucket score avg as reference if no snapshot
        prev_close = 0.0
        if summary.nvda_status and ticker == "NVDA":
            continue  # skip NVDA

        # Try to find snapshot data from add_candidates
        # Since we don't have direct snapshot access here, use prev_close = 0 placeholder
        # In practice, this function should receive snapshots
        # For MVP, we'll compute limit prices as percentages

        discount_low = discounts[1] if len(discounts) > 1 else discounts[0]
        discount_high = discounts[0]

        reason = f"{label} {'强势回踩' if role == 'core' else '回调接入'}"

        orders.append(
            SleepLimitOrder(
                ticker=ticker,
                bucket=bucket_name,
                bucket_label=label,
                suggested_limit_low=discount_low,
                suggested_limit_high=discount_high,
                max_dollars=round(max_dollars, 0),
                reason=reason,
            )
        )
        total_amount += max_dollars

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return SleepPlan(
        orders=orders,
        total_pending_amount=round(total_amount, 0),
        max_pending_amount=round(max_pending, 0),
        market_regime=summary.market_regime,
        generated_at=now_str,
    )


def generate_sleep_plan_with_prices(
    summary: MarketSummary,
    portfolio: PortfolioSummary,
    rules: dict,
    watchlist: dict,
    snapshots: dict[str, TickerSnapshot],
) -> SleepPlan:
    """Generate sleep limit order plan with actual price levels."""
    risk_rules = rules.get("risk_rules", {})
    sleep_rules = rules.get("sleep_limit_rules", {})

    max_pending = portfolio.account_value * risk_rules.get(
        "sleep_mode_max_pending_orders_pct", 0.30
    )

    core_discounts = sleep_rules.get("strong_core_discount_from_prev_close_pct", [1.5, 3.0])
    beta_discounts = sleep_rules.get("beta_discount_from_prev_close_pct", [4.0, 7.0])
    high_beta_discounts = sleep_rules.get("high_beta_discount_from_prev_close_pct", [8.0, 12.0])

    # Collect candidates
    candidate_tickers: set[str] = set()
    for ts in summary.add_candidates:
        candidate_tickers.add(ts.ticker)

    for bs in summary.bucket_scores:
        if bs.stronger_than_smh or bs.stronger_than_soxx:
            for t in bs.tickers:
                candidate_tickers.add(t)

    do_not_buy_tickers = {ts.ticker for ts in summary.do_not_buy}
    candidate_tickers -= do_not_buy_tickers
    candidate_tickers.discard("NVDA")

    orders: list[SleepLimitOrder] = []
    total_amount = 0.0

    for ticker in sorted(candidate_tickers):
        if total_amount >= max_pending:
            break

        snap = snapshots.get(ticker)
        if not snap or snap.data_missing or snap.prev_close <= 0:
            continue

        buckets = get_bucket_for_ticker(ticker)
        if not buckets:
            continue

        bucket_name = buckets[0]
        role = get_bucket_role(bucket_name)
        label = get_bucket_label(bucket_name)

        if role == "core":
            discounts = core_discounts
            max_dollars = min(2000.0, max_pending - total_amount)
        elif role == "high_beta":
            discounts = high_beta_discounts
            max_dollars = min(500.0, max_pending - total_amount)
        else:
            discounts = beta_discounts
            max_dollars = min(1000.0, max_pending - total_amount)

        if max_dollars <= 0:
            break

        prev_close = snap.prev_close
        limit_high = round(prev_close * (1 - discounts[0] / 100), 2)
        limit_low = round(prev_close * (1 - discounts[1] / 100), 2)

        reason = f"{label} {'强势回踩' if role == 'core' else '回调接入'}"

        orders.append(
            SleepLimitOrder(
                ticker=ticker,
                bucket=bucket_name,
                bucket_label=label,
                suggested_limit_low=limit_low,
                suggested_limit_high=limit_high,
                max_dollars=round(max_dollars, 0),
                reason=reason,
            )
        )
        total_amount += max_dollars

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return SleepPlan(
        orders=orders,
        total_pending_amount=round(total_amount, 0),
        max_pending_amount=round(max_pending, 0),
        market_regime=summary.market_regime,
        generated_at=now_str,
    )


def format_sleep_plan(plan: SleepPlan) -> str:
    """Format sleep plan as text."""
    if not plan.orders:
        return "  当前无合适的 limit 挂单建议。"

    lines: list[str] = []
    lines.append(f"  总挂单上限: ${plan.max_pending_amount:.0f}")
    lines.append(f"  计划挂单: ${plan.total_pending_amount:.0f}")
    lines.append(f"  市场状态: {plan.market_regime}")
    lines.append("")

    for order in plan.orders:
        lines.append(f"  {order.ticker} [{order.bucket_label}]")
        lines.append(f"    Limit 区间: ${order.suggested_limit_low:.2f} ~ ${order.suggested_limit_high:.2f}")
        lines.append(f"    最大金额: ${order.max_dollars:.0f}")
        lines.append(f"    理由: {order.reason}")
        lines.append("")

    return "\n".join(lines)
