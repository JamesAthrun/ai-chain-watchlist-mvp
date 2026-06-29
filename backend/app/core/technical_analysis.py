"""Technical analysis module - local calculation of indicators.

Calculates MA, RSI, MACD, support/resistance levels using pandas.
Data source priority: Polygon proxy (historical bars) → yfinance fallback.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

from app.core.models import TickerSnapshot

logger = logging.getLogger(__name__)

# Tolerance for MA support detection (3%)
MA_SUPPORT_TOLERANCE = 0.03


class TechnicalIndicators:
    """Technical indicators for a single ticker."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        self.current_price: float = 0.0
        self.prev_close: float = 0.0
        self.ma5: float = 0.0
        self.ma10: float = 0.0
        self.ma20: float = 0.0
        self.ma60: float = 0.0
        self.rsi_14: float = 50.0
        self.macd: float = 0.0
        self.macd_signal: float = 0.0
        self.macd_hist: float = 0.0
        self.atr_14: float = 0.0  # 14-day Average True Range
        self.support_levels: list[float] = []
        self.resistance_levels: list[float] = []
        # Fibonacci retracement levels (from 60-day swing high/low)
        self.fib_382: float = 0.0
        self.fib_500: float = 0.0
        self.fib_618: float = 0.0
        self.swing_high: float = 0.0
        self.swing_low: float = 0.0
        self.ma50: float = 0.0
        self.ma100: float = 0.0
        self.ma200: float = 0.0
        # MA slope (pct change over lookback period)
        self.ma20_slope_pct: float = 0.0
        self.ma50_slope_pct: float = 0.0
        self.ma100_slope_pct: float = 0.0
        # Multi-timeframe relative strength vs SMH
        self.rs_5d_vs_smh: float = 0.0
        self.rs_20d_vs_smh: float = 0.0
        self.rs_60d_vs_smh: float = 0.0
        # Recent swing low (20-day low for structural support)
        self.recent_swing_low: float = 0.0
        self.volume_ratio: float = 1.0  # today vol / 5-day avg vol
        self.trend: str = "neutral"  # up / down / neutral
        self.days_below_ma20: int = 0  # consecutive closes below MA20
        self.days_below_ma50: int = 0  # consecutive closes below MA50
        self.data_available: bool = False
        self.error: Optional[str] = None

    def nearest_support(self) -> Optional[float]:
        return self.support_levels[0] if self.support_levels else None

    def next_support(self) -> Optional[float]:
        """Second support level (for limit_2 calculation)."""
        return self.support_levels[1] if len(self.support_levels) >= 2 else None

    def nearest_resistance(self) -> Optional[float]:
        return self.resistance_levels[0] if self.resistance_levels else None

    def second_resistance(self) -> Optional[float]:
        return self.resistance_levels[1] if len(self.resistance_levels) >= 2 else None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "current_price": round(self.current_price, 2),
            "prev_close": round(self.prev_close, 2),
            "ma5": round(self.ma5, 2),
            "ma10": round(self.ma10, 2),
            "ma20": round(self.ma20, 2),
            "ma50": round(self.ma50, 2),
            "ma60": round(self.ma60, 2),
            "rsi_14": round(self.rsi_14, 1),
            "macd": round(self.macd, 4),
            "macd_signal": round(self.macd_signal, 4),
            "macd_hist": round(self.macd_hist, 4),
            "atr_14": round(self.atr_14, 2),
            "support_levels": [round(s, 2) for s in self.support_levels],
            "resistance_levels": [round(r, 2) for r in self.resistance_levels],
            "fib_382": round(self.fib_382, 2),
            "fib_500": round(self.fib_500, 2),
            "fib_618": round(self.fib_618, 2),
            "swing_high": round(self.swing_high, 2),
            "swing_low": round(self.swing_low, 2),
            "ma100": round(self.ma100, 2),
            "ma200": round(self.ma200, 2),
            "ma20_slope_pct": round(self.ma20_slope_pct, 3),
            "ma50_slope_pct": round(self.ma50_slope_pct, 3),
            "ma100_slope_pct": round(self.ma100_slope_pct, 3),
            "rs_5d_vs_smh": round(self.rs_5d_vs_smh, 2),
            "rs_20d_vs_smh": round(self.rs_20d_vs_smh, 2),
            "rs_60d_vs_smh": round(self.rs_60d_vs_smh, 2),
            "recent_swing_low": round(self.recent_swing_low, 2),
            "volume_ratio": round(self.volume_ratio, 2),
            "trend": self.trend,
            "days_below_ma20": self.days_below_ma20,
            "days_below_ma50": self.days_below_ma50,
        }


def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate Average True Range (14-day)."""
    if len(df) < period + 1:
        # Fallback: use today's range
        return float(df["High"].iloc[-1] - df["Low"].iloc[-1]) if len(df) > 0 else 0.0

    high = df["High"]
    low = df["Low"]
    close = df["Close"].shift(1)

    tr1 = high - low
    tr2 = (high - close).abs()
    tr3 = (low - close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean().iloc[-1]
    return float(atr) if not pd.isna(atr) else 0.0


def _calc_fibonacci(df: pd.DataFrame, period: int = 60) -> tuple[float, float, float, float, float]:
    """Calculate Fibonacci retracement levels from swing high/low over N days.

    Returns: (fib_382, fib_500, fib_618, swing_high, swing_low)
    """
    if len(df) < period:
        period = len(df)
    if period < 5:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    recent = df.iloc[-period:]
    swing_high = float(recent["High"].max())
    swing_low = float(recent["Low"].min())

    if swing_high <= swing_low:
        return 0.0, 0.0, 0.0, swing_high, swing_low

    diff = swing_high - swing_low
    fib_382 = swing_high - diff * 0.382
    fib_500 = swing_high - diff * 0.500
    fib_618 = swing_high - diff * 0.618

    return fib_382, fib_500, fib_618, swing_high, swing_low


def _calc_rsi(closes: pd.Series, period: int = 14) -> float:
    """Calculate RSI using standard Wilder method."""
    if len(closes) < period + 1:
        return 50.0

    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean().iloc[-1]
    avg_loss = loss.rolling(window=period, min_periods=period).mean().iloc[-1]

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calc_macd(closes: pd.Series) -> tuple[float, float, float]:
    """Calculate MACD (12, 26, 9)."""
    if len(closes) < 26:
        return 0.0, 0.0, 0.0

    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(histogram.iloc[-1])


def _calc_support_resistance(
    df: pd.DataFrame, current_price: float, ma5: float, ma10: float, ma20: float
) -> tuple[list[float], list[float]]:
    """Calculate support and resistance levels using MA + recent highs/lows.

    Support: MAs below current price within tolerance
    Resistance: 20-day high above current price
    """
    supports = []
    resistances = []

    # MA support detection (DSA method)
    for ma, label in [(ma5, "MA5"), (ma10, "MA10"), (ma20, "MA20")]:
        if ma > 0 and current_price >= ma:
            distance = (current_price - ma) / ma
            if distance <= MA_SUPPORT_TOLERANCE:
                supports.append(ma)

    # Recent low as support (20-day low)
    if len(df) >= 20:
        recent_low = float(df["Low"].iloc[-20:].min())
        if recent_low < current_price and recent_low not in supports:
            supports.append(recent_low)

    # Resistance: 20-day high
    if len(df) >= 20:
        recent_high = float(df["High"].iloc[-20:].max())
        if recent_high > current_price:
            resistances.append(recent_high)

    # Sort: supports descending (nearest first), resistances ascending
    supports.sort(reverse=True)
    resistances.sort()

    return supports, resistances


def _determine_trend(ma5: float, ma10: float, ma20: float, current_price: float) -> str:
    """Determine trend based on MA alignment."""
    if ma5 <= 0 or ma10 <= 0 or ma20 <= 0:
        return "neutral"

    if current_price > ma5 > ma10 > ma20:
        return "up"
    elif current_price < ma5 < ma10 < ma20:
        return "down"
    else:
        return "neutral"


def analyze_ticker_technical(ticker: str, period: str = "1y") -> TechnicalIndicators:
    """Fetch historical data and calculate technical indicators for a single ticker.

    Uses yfinance for historical daily data (free, no API key needed for this).
    """
    result = TechnicalIndicators(ticker=ticker)

    try:
        tk = yf.Ticker(ticker)
        df = tk.history(period=period, interval="1d")

        if df is None or df.empty or len(df) < 5:
            result.error = "Insufficient historical data"
            return result

        closes = df["Close"]
        current_price = float(closes.iloc[-1])
        result.current_price = current_price
        result.prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else current_price

        # Moving averages
        result.ma5 = float(closes.iloc[-5:].mean()) if len(closes) >= 5 else 0.0
        result.ma10 = float(closes.iloc[-10:].mean()) if len(closes) >= 10 else 0.0
        result.ma20 = float(closes.iloc[-20:].mean()) if len(closes) >= 20 else 0.0
        result.ma60 = float(closes.iloc[-60:].mean()) if len(closes) >= 60 else 0.0
        result.ma50 = float(closes.iloc[-50:].mean()) if len(closes) >= 50 else 0.0
        result.ma100 = float(closes.iloc[-100:].mean()) if len(closes) >= 100 else 0.0
        result.ma200 = float(closes.iloc[-200:].mean()) if len(closes) >= 200 else 0.0

        # RSI
        result.rsi_14 = _calc_rsi(closes, 14)

        # MACD
        result.macd, result.macd_signal, result.macd_hist = _calc_macd(closes)

        # Support / Resistance
        result.support_levels, result.resistance_levels = _calc_support_resistance(
            df, current_price, result.ma5, result.ma10, result.ma20
        )

        # ATR (14-day)
        result.atr_14 = _calc_atr(df, 14)

        # Fibonacci retracement (60-day swing)
        result.fib_382, result.fib_500, result.fib_618, result.swing_high, result.swing_low = (
            _calc_fibonacci(df, 60)
        )

        # Volume ratio (today vs 5-day average)
        if len(df) >= 5 and "Volume" in df.columns:
            vol_5avg = float(df["Volume"].iloc[-5:].mean())
            today_vol = float(df["Volume"].iloc[-1])
            result.volume_ratio = today_vol / vol_5avg if vol_5avg > 0 else 1.0

        # Trend
        result.trend = _determine_trend(result.ma5, result.ma10, result.ma20, current_price)
        result.data_available = True

    except Exception as e:
        logger.warning(f"[ta] {ticker} technical analysis failed: {e}")
        result.error = str(e)

    return result


def _fetch_bars_polygon(ticker: str, days: int = 90) -> Optional[pd.DataFrame]:
    """Fetch historical daily bars from Polygon proxy.

    Returns DataFrame with columns: Open, High, Low, Close, Volume
    or None on failure.
    """
    proxy_url = os.getenv("POLYGON_PROXY_URL", "").rstrip("/")
    proxy_key = os.getenv("POLYGON_PROXY_KEY", "")

    if not proxy_url or not proxy_key:
        return None

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    from_str = start_date.strftime("%Y-%m-%d")
    to_str = end_date.strftime("%Y-%m-%d")

    url = f"{proxy_url}/v2/aggs/ticker/{ticker}/range/1/day/{from_str}/{to_str}"
    headers = {"X-Proxy-Key": proxy_key}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None

        df = pd.DataFrame(results)
        # Polygon fields: o=open, h=high, l=low, c=close, v=volume, t=timestamp
        df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume", "t": "Timestamp"})
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        return df

    except Exception as e:
        logger.debug(f"[ta] Polygon proxy bars failed for {ticker}: {e}")
        return None


def analyze_batch_technical(tickers: list[str], period: str = "1y") -> dict[str, TechnicalIndicators]:
    """Analyze multiple tickers. Uses Polygon proxy for historical bars, yfinance as fallback.

    Polygon proxy requests run concurrently (up to 8 threads) to avoid timeout.
    """
    valid_tickers = [t for t in tickers if not t.startswith("^")]
    results = {}

    if not valid_tickers:
        return results

    days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}.get(period, 365)
    polygon_available = bool(os.getenv("POLYGON_PROXY_URL") and os.getenv("POLYGON_PROXY_KEY"))
    yf_fallback_tickers = []
    # Store raw close series for relative strength calculation
    _raw_closes: dict[str, pd.Series] = {}

    def _fetch_and_compute(ticker: str) -> tuple[str, TechnicalIndicators, bool, Optional[pd.Series]]:
        """Fetch bars and compute indicators for one ticker. Returns (ticker, result, success, closes)."""
        result = TechnicalIndicators(ticker=ticker)
        df = _fetch_bars_polygon(ticker, days) if polygon_available else None
        if df is not None and len(df) >= 5:
            try:
                result = _compute_indicators(ticker, df)
                return (ticker, result, True, df["Close"] if "Close" in df.columns else None)
            except Exception as e:
                logger.warning(f"[ta] {ticker} indicator calc failed: {e}")
                result.error = str(e)
                return (ticker, result, False, None)
        return (ticker, result, False, None)

    # Run Polygon fetches concurrently
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_and_compute, t): t for t in valid_tickers}
        for future in as_completed(futures):
            ticker, result, success, closes_series = future.result()
            results[ticker] = result
            if success and closes_series is not None:
                _raw_closes[ticker] = closes_series
            if not success:
                yf_fallback_tickers.append(ticker)

    # Batch fallback via yfinance for tickers where Polygon failed
    if yf_fallback_tickers:
        logger.info(f"[ta] Falling back to yfinance for {len(yf_fallback_tickers)} tickers")
        try:
            df_all = yf.download(yf_fallback_tickers, period=period, interval="1d",
                                 group_by="ticker", progress=False, threads=True)
            if df_all is not None and not df_all.empty:
                for ticker in yf_fallback_tickers:
                    try:
                        if len(yf_fallback_tickers) == 1:
                            df = df_all.copy()
                        else:
                            df = df_all[ticker].copy() if ticker in df_all.columns.get_level_values(0) else pd.DataFrame()
                        df = df.dropna(subset=["Close"]) if not df.empty and "Close" in df.columns else df
                        if not df.empty and len(df) >= 5:
                            results[ticker] = _compute_indicators(ticker, df)
                            if "Close" in df.columns:
                                _raw_closes[ticker] = df["Close"]
                    except Exception as e:
                        logger.warning(f"[ta] {ticker} yfinance fallback failed: {e}")
                        results[ticker].error = str(e)
        except Exception as e:
            logger.warning(f"[ta] yfinance batch download failed: {e}")

    # Compute multi-timeframe relative strength vs SMH
    smh_closes = _raw_closes.get("SMH")
    if smh_closes is not None:
        compute_relative_strength(results, smh_closes, _raw_closes)

    return results


def _count_consecutive_below(closes: pd.Series, ma_series: pd.Series) -> int:
    """Count consecutive recent closes below a moving average (from most recent backwards)."""
    count = 0
    for i in range(len(closes) - 1, -1, -1):
        c = closes.iloc[i]
        m = ma_series.iloc[i]
        if pd.isna(m):
            break
        if c < m:
            count += 1
        else:
            break
    return count


def _compute_indicators(ticker: str, df: pd.DataFrame) -> TechnicalIndicators:
    """Compute all technical indicators from a DataFrame with OHLCV columns."""
    result = TechnicalIndicators(ticker=ticker)

    closes = df["Close"]
    current_price = float(closes.iloc[-1])
    result.current_price = current_price
    result.prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else current_price

    # Moving averages
    result.ma5 = float(closes.iloc[-5:].mean()) if len(closes) >= 5 else 0.0
    result.ma10 = float(closes.iloc[-10:].mean()) if len(closes) >= 10 else 0.0
    result.ma20 = float(closes.iloc[-20:].mean()) if len(closes) >= 20 else 0.0
    result.ma50 = float(closes.iloc[-50:].mean()) if len(closes) >= 50 else 0.0
    result.ma60 = float(closes.iloc[-60:].mean()) if len(closes) >= 60 else 0.0
    result.ma100 = float(closes.iloc[-100:].mean()) if len(closes) >= 100 else 0.0
    result.ma200 = float(closes.iloc[-200:].mean()) if len(closes) >= 200 else 0.0

    # MA slopes (pct change over lookback period)
    if len(closes) >= 25 and result.ma20 > 0:
        ma20_series = closes.rolling(20).mean()
        ma20_5ago = float(ma20_series.iloc[-6]) if len(ma20_series) >= 6 and not pd.isna(ma20_series.iloc[-6]) else 0.0
        result.ma20_slope_pct = ((result.ma20 - ma20_5ago) / ma20_5ago * 100) if ma20_5ago > 0 else 0.0
    if len(closes) >= 60 and result.ma50 > 0:
        ma50_series = closes.rolling(50).mean()
        ma50_10ago = float(ma50_series.iloc[-11]) if len(ma50_series) >= 11 and not pd.isna(ma50_series.iloc[-11]) else 0.0
        result.ma50_slope_pct = ((result.ma50 - ma50_10ago) / ma50_10ago * 100) if ma50_10ago > 0 else 0.0
    if len(closes) >= 120 and result.ma100 > 0:
        ma100_series = closes.rolling(100).mean()
        ma100_20ago = float(ma100_series.iloc[-21]) if len(ma100_series) >= 21 and not pd.isna(ma100_series.iloc[-21]) else 0.0
        result.ma100_slope_pct = ((result.ma100 - ma100_20ago) / ma100_20ago * 100) if ma100_20ago > 0 else 0.0

    # Recent swing low (20-day low for structural support confirmation)
    if len(df) >= 20:
        result.recent_swing_low = float(df["Low"].iloc[-20:].min())

    # RSI
    result.rsi_14 = _calc_rsi(closes, 14)

    # MACD
    result.macd, result.macd_signal, result.macd_hist = _calc_macd(closes)

    # Support / Resistance
    result.support_levels, result.resistance_levels = _calc_support_resistance(
        df, current_price, result.ma5, result.ma10, result.ma20
    )

    # ATR (14-day)
    result.atr_14 = _calc_atr(df, 14)

    # Fibonacci retracement (60-day swing)
    result.fib_382, result.fib_500, result.fib_618, result.swing_high, result.swing_low = (
        _calc_fibonacci(df, 60)
    )

    # Volume ratio
    if len(df) >= 5 and "Volume" in df.columns:
        vol_5avg = float(df["Volume"].iloc[-5:].mean())
        today_vol = float(df["Volume"].iloc[-1])
        result.volume_ratio = today_vol / vol_5avg if vol_5avg > 0 else 1.0

    # Trend
    result.trend = _determine_trend(result.ma5, result.ma10, result.ma20, current_price)

    # Days below MA20/MA50 (consecutive recent closes below the MA)
    if len(closes) >= 20 and result.ma20 > 0:
        ma20_series = closes.rolling(20).mean()
        result.days_below_ma20 = _count_consecutive_below(closes, ma20_series)
    if len(closes) >= 50 and result.ma50 > 0:
        ma50_series = closes.rolling(50).mean()
        result.days_below_ma50 = _count_consecutive_below(closes, ma50_series)

    # Multi-timeframe relative strength vs SMH (computed externally via compute_relative_strength)

    result.data_available = True

    return result


def compute_relative_strength(
    ta_results: dict[str, "TechnicalIndicators"],
    smh_closes: Optional[pd.Series] = None,
    ticker_closes_map: Optional[dict[str, pd.Series]] = None,
) -> None:
    """Compute multi-timeframe relative strength vs SMH and set rs_*d_vs_smh fields.

    Called after batch TA to enrich results with 5d/20d/60d relative strength.
    Requires raw close series for SMH and individual tickers.
    """
    if smh_closes is None or ticker_closes_map is None:
        return

    smh_len = len(smh_closes)
    if smh_len < 5:
        return

    def _pct_return(series: pd.Series, days: int) -> float:
        if len(series) < days + 1:
            return 0.0
        return (float(series.iloc[-1]) - float(series.iloc[-1 - days])) / float(series.iloc[-1 - days]) * 100

    smh_5d = _pct_return(smh_closes, 5)
    smh_20d = _pct_return(smh_closes, 20) if smh_len >= 21 else 0.0
    smh_60d = _pct_return(smh_closes, 60) if smh_len >= 61 else 0.0

    for ticker, ta in ta_results.items():
        if ticker == "SMH" or not ta.data_available:
            continue
        closes = ticker_closes_map.get(ticker)
        if closes is None or len(closes) < 5:
            continue

        ta.rs_5d_vs_smh = round(_pct_return(closes, 5) - smh_5d, 2)
        ta.rs_20d_vs_smh = round(_pct_return(closes, 20) - smh_20d, 2) if len(closes) >= 21 else 0.0
        ta.rs_60d_vs_smh = round(_pct_return(closes, 60) - smh_60d, 2) if len(closes) >= 61 else 0.0
