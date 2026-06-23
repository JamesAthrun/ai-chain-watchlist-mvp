"""Scoring engine for market regime, tickers, and buckets."""

from datetime import datetime, timezone

from app.core.models import (
    BucketScore,
    MarketSummary,
    TickerScore,
    TickerSnapshot,
)


def classify_strength(pct_change: float) -> str:
    if pct_change > 0.5:
        return "strong"
    elif pct_change < -0.5:
        return "weak"
    else:
        return "neutral"


def score_market_regime(
    snapshots: dict[str, TickerSnapshot], watchlist: dict
) -> dict:
    """Determine market regime based on QQQ, SMH, SOXX."""
    benchmarks = ["QQQ", "SMH", "SOXX"]
    strength_map: dict[str, str] = {}

    for b in benchmarks:
        snap = snapshots.get(b)
        if snap and not snap.data_missing:
            strength_map[b] = classify_strength(snap.pct_change_from_prev_close)
        else:
            strength_map[b] = "unknown"

    qqq_s = strength_map.get("QQQ", "unknown")
    smh_s = strength_map.get("SMH", "unknown")
    soxx_s = strength_map.get("SOXX", "unknown")

    if qqq_s == "strong" and smh_s == "strong" and soxx_s == "strong":
        regime = "market_strong"
    elif qqq_s == "weak" and (smh_s == "strong" or soxx_s == "strong"):
        regime = "semi_strong_qqq_weak"
    elif qqq_s == "weak" and smh_s == "weak" and soxx_s == "weak":
        regime = "market_weak"
    else:
        regime = "market_neutral"

    return {
        "market_regime": regime,
        "benchmark_strength": strength_map,
    }


def score_tickers(
    snapshots: dict[str, TickerSnapshot], rules: dict
) -> dict[str, TickerScore]:
    """Score each ticker for entry/avoid signals."""
    entry_rules = rules.get("entry_rules", {})
    near_high_thresh = entry_rules.get("near_day_high_threshold_pct", 1.0)
    near_low_thresh = entry_rules.get("near_day_low_threshold_pct", 1.0)

    results: dict[str, TickerScore] = {}

    for ticker, snap in snapshots.items():
        if snap.data_missing:
            results[ticker] = TickerScore(
                ticker=ticker,
                reason=f"Data missing: {snap.error}",
            )
            continue

        above_open = snap.last_price > snap.open_price
        below_open = snap.last_price < snap.open_price
        # pct_from_day_high is <= 0; near high means >= -threshold
        near_day_high = snap.pct_from_day_high >= -near_high_thresh
        # pct_from_day_low is >= 0; near low means <= threshold
        near_day_low = snap.pct_from_day_low <= near_low_thresh

        do_not_buy = below_open and near_day_low
        add_candidate = above_open and near_day_high

        results[ticker] = TickerScore(
            ticker=ticker,
            above_open=above_open,
            below_open=below_open,
            near_day_high=near_day_high,
            near_day_low=near_day_low,
            add_candidate=add_candidate,
            do_not_buy=do_not_buy,
        )

    return results


def score_buckets(
    snapshots: dict[str, TickerSnapshot], watchlist: dict
) -> list[BucketScore]:
    """Score each bucket by average pct change."""
    smh_snap = snapshots.get("SMH")
    soxx_snap = snapshots.get("SOXX")
    smh_pct = smh_snap.pct_change_from_prev_close if smh_snap and not smh_snap.data_missing else None
    soxx_pct = soxx_snap.pct_change_from_prev_close if soxx_snap and not soxx_snap.data_missing else None

    bucket_scores: list[BucketScore] = []

    for bucket_name, bucket_data in watchlist.get("buckets", {}).items():
        tickers = bucket_data.get("tickers", [])
        label = bucket_data.get("label", bucket_name)
        role = bucket_data.get("role", "unknown")

        pct_changes = []
        for t in tickers:
            snap = snapshots.get(t)
            if snap and not snap.data_missing:
                pct_changes.append(snap.pct_change_from_prev_close)

        avg_pct = sum(pct_changes) / len(pct_changes) if pct_changes else 0.0

        stronger_than_smh = avg_pct > smh_pct if smh_pct is not None else False
        stronger_than_soxx = avg_pct > soxx_pct if soxx_pct is not None else False

        bucket_scores.append(
            BucketScore(
                bucket_name=bucket_name,
                label=label,
                role=role,
                avg_pct_change=round(avg_pct, 3),
                stronger_than_smh=stronger_than_smh,
                stronger_than_soxx=stronger_than_soxx,
                tickers=tickers,
            )
        )

    return bucket_scores


def build_market_summary(
    snapshots: dict[str, TickerSnapshot],
    watchlist: dict,
    rules: dict,
) -> MarketSummary:
    """Build complete market summary."""
    regime_info = score_market_regime(snapshots, watchlist)
    ticker_scores = score_tickers(snapshots, rules)
    bucket_scores = score_buckets(snapshots, watchlist)

    # Filter add_candidates and do_not_buy (exclude NVDA from add_candidates)
    add_candidates = [
        ts for ts in ticker_scores.values()
        if ts.add_candidate and ts.ticker != "NVDA"
    ]
    do_not_buy_list = [
        ts for ts in ticker_scores.values()
        if ts.do_not_buy
    ]

    # NVDA status
    nvda_snap = snapshots.get("NVDA")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return MarketSummary(
        market_regime=regime_info["market_regime"],
        benchmark_strength=regime_info["benchmark_strength"],
        bucket_scores=bucket_scores,
        add_candidates=add_candidates,
        do_not_buy=do_not_buy_list,
        nvda_status=nvda_snap,
        generated_at=now_str,
    )
