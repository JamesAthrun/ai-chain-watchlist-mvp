"""Technical analysis module - local calculation of indicators.

Calculates MA, RSI, MACD, support/resistance levels using pandas.
Inspired by daily_stock_analysis's StockTrendAnalyzer approach.
"""

import logging
from typing import Optional

import pandas as pd
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
        self.volume_ratio: float = 1.0  # today vol / 5-day avg vol
        self.trend: str = "neutral"  # up / down / neutral
        self.data_available: bool = False
        self.error: Optional[str] = None

    def nearest_support(self) -> Optional[float]:
        return self.support_levels[0] if self.support_levels else None

    def next_support(self) -> Optional[float]:
        """Second support level (for limit_2 calculation)."""
        return self.support_levels[1] if len(self.support_levels) >= 2 else None

    def nearest_resistance(self) -> Optional[float]:
        return self.resistance_levels[0] if self.resistance_levels else None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "current_price": round(self.current_price, 2),
            "prev_close": round(self.prev_close, 2),
            "ma5": round(self.ma5, 2),
            "ma10": round(self.ma10, 2),
            "ma20": round(self.ma20, 2),
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
            "volume_ratio": round(self.volume_ratio, 2),
            "trend": self.trend,
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


def analyze_ticker_technical(ticker: str, period: str = "3mo") -> TechnicalIndicators:
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


def analyze_batch_technical(tickers: list[str], period: str = "3mo") -> dict[str, TechnicalIndicators]:
    """Analyze multiple tickers. Returns dict of ticker -> TechnicalIndicators."""
    results = {}
    for ticker in tickers:
        # Skip index tickers (^SOX etc.) - no historical data via yfinance for indices
        if ticker.startswith("^"):
            continue
        results[ticker] = analyze_ticker_technical(ticker, period)
    return results
