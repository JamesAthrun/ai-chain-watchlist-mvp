"""Data models for the watchlist MVP."""

from typing import Optional
from pydantic import BaseModel


class TickerSnapshot(BaseModel):
    ticker: str
    last_price: float = 0.0
    prev_close: float = 0.0
    open_price: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    pct_change_from_prev_close: float = 0.0
    pct_from_open: float = 0.0
    pct_from_day_high: float = 0.0
    pct_from_day_low: float = 0.0
    volume: float = 0.0
    data_missing: bool = False
    error: Optional[str] = None


class TickerScore(BaseModel):
    ticker: str
    above_open: bool = False
    below_open: bool = False
    near_day_high: bool = False
    near_day_low: bool = False
    add_candidate: bool = False
    do_not_buy: bool = False
    reason: Optional[str] = None


class BucketScore(BaseModel):
    bucket_name: str
    label: str
    role: str
    avg_pct_change: float = 0.0
    stronger_than_smh: bool = False
    stronger_than_soxx: bool = False
    tickers: list[str] = []


class MarketSummary(BaseModel):
    market_regime: str = "unknown"
    benchmark_strength: dict[str, str] = {}
    bucket_scores: list[BucketScore] = []
    add_candidates: list[TickerScore] = []
    do_not_buy: list[TickerScore] = []
    nvda_status: Optional[TickerSnapshot] = None
    generated_at: str = ""


class PositionInfo(BaseModel):
    ticker: str
    shares: float = 0.0
    avg_cost: float = 0.0
    manual_value: Optional[float] = None
    bucket: Optional[str] = None
    intent: Optional[str] = None
    current_value: float = 0.0
    pct_of_account: float = 0.0


class PortfolioSummary(BaseModel):
    account_value: float = 0.0
    cash: float = 0.0
    invested_value: float = 0.0
    cash_pct: float = 0.0
    position_pct: float = 0.0
    positions: list[PositionInfo] = []
    bucket_exposure: dict[str, float] = {}
    single_ticker_exposure: dict[str, float] = {}


class SleepLimitOrder(BaseModel):
    ticker: str
    bucket: str
    bucket_label: str
    suggested_limit_low: float
    suggested_limit_high: float
    max_dollars: float
    reason: str


class SleepPlan(BaseModel):
    orders: list[SleepLimitOrder] = []
    total_pending_amount: float = 0.0
    max_pending_amount: float = 0.0
    market_regime: str = ""
    generated_at: str = ""
