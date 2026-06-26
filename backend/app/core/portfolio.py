"""Portfolio analysis module."""

from app.core.models import PortfolioSummary, PositionInfo, TickerSnapshot


def analyze_portfolio(
    portfolio_data: dict,
    snapshots: dict[str, TickerSnapshot] | None = None,
) -> PortfolioSummary:
    """Analyze portfolio and compute exposures.

    account_value is dynamically calculated as cash + market value of positions.
    """
    cash = portfolio_data.get("cash", 0.0)

    positions: list[PositionInfo] = []
    invested_value = 0.0
    bucket_exposure: dict[str, float] = {}
    single_ticker_exposure: dict[str, float] = {}

    for pos in portfolio_data.get("positions", []):
        ticker = pos.get("ticker", "")
        shares = pos.get("shares", 0.0)
        avg_cost = pos.get("avg_cost", 0.0)
        manual_value = pos.get("manual_value")
        bucket = pos.get("bucket")
        intent = pos.get("intent")

        # Determine current value
        if manual_value is not None:
            current_value = manual_value
        elif snapshots and ticker in snapshots and not snapshots[ticker].data_missing:
            current_value = shares * snapshots[ticker].last_price
        else:
            current_value = shares * avg_cost  # fallback

        invested_value += current_value

        pct_of_account = (current_value / account_value * 100) if account_value > 0 else 0.0

        positions.append(
            PositionInfo(
                ticker=ticker,
                shares=shares,
                avg_cost=avg_cost,
                manual_value=manual_value,
                bucket=bucket,
                intent=intent,
                current_value=current_value,
                pct_of_account=round(pct_of_account, 2),
            )
        )

        # Bucket exposure
        if bucket:
            bucket_exposure[bucket] = bucket_exposure.get(bucket, 0.0) + current_value

        # Single ticker exposure
        single_ticker_exposure[ticker] = (
            single_ticker_exposure.get(ticker, 0.0) + current_value
        )

    # Dynamic account value = cash + market value of all positions
    account_value = cash + invested_value

    cash_pct = (cash / account_value * 100) if account_value > 0 else 0.0
    position_pct = (invested_value / account_value * 100) if account_value > 0 else 0.0

    # Convert bucket exposure to percentages
    bucket_exposure_pct = {
        k: round(v / account_value * 100, 2) if account_value > 0 else 0.0
        for k, v in bucket_exposure.items()
    }
    single_ticker_exposure_pct = {
        k: round(v / account_value * 100, 2) if account_value > 0 else 0.0
        for k, v in single_ticker_exposure.items()
    }

    return PortfolioSummary(
        account_value=account_value,
        cash=cash,
        invested_value=round(invested_value, 2),
        cash_pct=round(cash_pct, 2),
        position_pct=round(position_pct, 2),
        positions=positions,
        bucket_exposure=bucket_exposure_pct,
        single_ticker_exposure=single_ticker_exposure_pct,
    )
