"""Market data fetcher using yfinance."""

import logging
from typing import Optional

import yfinance as yf

from app.core.models import TickerSnapshot

logger = logging.getLogger(__name__)


def fetch_snapshots(tickers: list[str]) -> dict[str, TickerSnapshot]:
    """Fetch market data for a list of tickers and return snapshots."""
    results: dict[str, TickerSnapshot] = {}
    logger.info(f"[market_data] Starting fetch for {len(tickers)} tickers: {tickers}")

    for ticker in tickers:
        try:
            snap = _fetch_single(ticker)
            if snap.data_missing:
                logger.warning(f"[market_data] {ticker} -> data_missing=True, error={snap.error}")
            else:
                logger.info(f"[market_data] {ticker} -> price={snap.last_price:.2f}, vol={snap.volume}")
            results[ticker] = snap
        except Exception as e:
            logger.warning(f"[market_data] {ticker} -> EXCEPTION: {e}")
            results[ticker] = TickerSnapshot(
                ticker=ticker,
                data_missing=True,
                error=str(e),
            )

    missing = [t for t, s in results.items() if s.data_missing]
    logger.info(f"[market_data] Done. {len(results)-len(missing)}/{len(results)} success, missing: {missing}")
    return results


def _fetch_single(ticker: str) -> TickerSnapshot:
    """Fetch data for a single ticker."""
    tk = yf.Ticker(ticker)

    # Try intraday first (1d period, 5m interval)
    last_price = 0.0
    open_price = 0.0
    day_high = 0.0
    day_low = 0.0
    prev_close = 0.0
    volume = 0.0

    try:
        # Get intraday data
        intraday = tk.history(period="1d", interval="5m")
        if intraday is not None and not intraday.empty:
            open_price = float(intraday["Open"].iloc[0])
            day_high = float(intraday["High"].max())
            day_low = float(intraday["Low"].min())
            last_price = float(intraday["Close"].iloc[-1])
            volume = float(intraday["Volume"].sum())
        else:
            # Fallback to daily
            daily = tk.history(period="5d", interval="1d")
            if daily is not None and not daily.empty:
                last_row = daily.iloc[-1]
                open_price = float(last_row["Open"])
                day_high = float(last_row["High"])
                day_low = float(last_row["Low"])
                last_price = float(last_row["Close"])
                volume = float(last_row["Volume"])
            else:
                return TickerSnapshot(
                    ticker=ticker,
                    data_missing=True,
                    error="No data available",
                )
    except Exception as e:
        # Try daily as fallback
        try:
            daily = tk.history(period="5d", interval="1d")
            if daily is not None and not daily.empty:
                last_row = daily.iloc[-1]
                open_price = float(last_row["Open"])
                day_high = float(last_row["High"])
                day_low = float(last_row["Low"])
                last_price = float(last_row["Close"])
                volume = float(last_row["Volume"])
            else:
                return TickerSnapshot(
                    ticker=ticker,
                    data_missing=True,
                    error=f"Intraday failed and no daily data: {e}",
                )
        except Exception as e2:
            return TickerSnapshot(
                ticker=ticker,
                data_missing=True,
                error=f"All fetches failed: {e2}",
            )

    # Get prev_close from daily data
    try:
        daily = tk.history(period="5d", interval="1d")
        if daily is not None and len(daily) >= 2:
            prev_close = float(daily["Close"].iloc[-2])
        elif daily is not None and len(daily) == 1:
            # Only one day available, use open as fallback
            prev_close = open_price
        else:
            prev_close = open_price
    except Exception:
        prev_close = open_price

    # Calculate percentages
    pct_change_from_prev_close = 0.0
    pct_from_open = 0.0
    pct_from_day_high = 0.0
    pct_from_day_low = 0.0

    if prev_close > 0:
        pct_change_from_prev_close = (last_price - prev_close) / prev_close * 100

    if open_price > 0:
        pct_from_open = (last_price - open_price) / open_price * 100

    if day_high > 0:
        pct_from_day_high = (last_price - day_high) / day_high * 100

    if day_low > 0:
        pct_from_day_low = (last_price - day_low) / day_low * 100

    return TickerSnapshot(
        ticker=ticker,
        last_price=last_price,
        prev_close=prev_close,
        open_price=open_price,
        day_high=day_high,
        day_low=day_low,
        pct_change_from_prev_close=round(pct_change_from_prev_close, 3),
        pct_from_open=round(pct_from_open, 3),
        pct_from_day_high=round(pct_from_day_high, 3),
        pct_from_day_low=round(pct_from_day_low, 3),
        volume=volume,
        data_missing=False,
        error=None,
    )
