"""Data models for the watchlist MVP."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


# ─── Trade Ledger Enums ─────────────────────────────────────────────

class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeSource(str, Enum):
    MANUAL = "MANUAL"
    PARSED_TEXT = "PARSED_TEXT"
    MANUAL_PLAN = "MANUAL_PLAN"
    IMPORT = "IMPORT"


class TradeReason(str, Enum):
    DAILY_PLAN_BUY = "DAILY_PLAN_BUY"
    PULLBACK_ADD = "PULLBACK_ADD"
    MANUAL_BUY = "MANUAL_BUY"
    TRIM_PROFIT = "TRIM_PROFIT"
    TRIM_RISK = "TRIM_RISK"
    EXIT_SIGNAL = "EXIT_SIGNAL"
    STOP_LOSS = "STOP_LOSS"
    CASH_MANAGEMENT = "CASH_MANAGEMENT"
    MANUAL_SELL = "MANUAL_SELL"


class CashTransactionType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"
    DIVIDEND = "DIVIDEND"
    FEE = "FEE"
    INTEREST = "INTEREST"


class ManualOrderPlanSource(str, Enum):
    DAILY_PLAN = "DAILY_PLAN"
    PULLBACK_ADD_PLAN = "PULLBACK_ADD_PLAN"
    EXIT_PLAN = "EXIT_PLAN"
    MANUAL = "MANUAL"


class ManualOrderPlanStatus(str, Enum):
    SUGGESTED = "SUGGESTED"
    USER_ACCEPTED = "USER_ACCEPTED"
    USER_REJECTED = "USER_REJECTED"
    MANUALLY_FILLED = "MANUALLY_FILLED"
    MANUALLY_CANCELLED = "MANUALLY_CANCELLED"
    EXPIRED = "EXPIRED"


class ConflictSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConflictType(str, Enum):
    BUY_WHILE_EXIT_SIGNAL = "BUY_WHILE_EXIT_SIGNAL"
    PULLBACK_ADD_WHILE_EXIT_RISK = "PULLBACK_ADD_WHILE_EXIT_RISK"
    HIGH_BETA_NOT_ALLOWED = "HIGH_BETA_NOT_ALLOWED"
    SECTOR_OVEREXPOSURE = "SECTOR_OVEREXPOSURE"
    SINGLE_POSITION_OVEREXPOSURE = "SINGLE_POSITION_OVEREXPOSURE"
    TOTAL_EXPOSURE_TOO_HIGH = "TOTAL_EXPOSURE_TOO_HIGH"
    DAILY_BUDGET_EXCEEDED = "DAILY_BUDGET_EXCEEDED"
    DUPLICATE_SECTOR_BUYING = "DUPLICATE_SECTOR_BUYING"
    EVENT_RISK = "EVENT_RISK"
    AI_MORE_AGGRESSIVE_THAN_RULES = "AI_MORE_AGGRESSIVE_THAN_RULES"
    STALE_DATA = "STALE_DATA"
    RECENTLY_SOLD_REBUY = "RECENTLY_SOLD_REBUY"
    RECENTLY_TRIMMED_REBUY = "RECENTLY_TRIMMED_REBUY"
    REPEATED_AVERAGING_DOWN = "REPEATED_AVERAGING_DOWN"
    DUPLICATE_ACTIVE_MANUAL_PLAN = "DUPLICATE_ACTIVE_MANUAL_PLAN"


# ─── Trade Ledger Models ────────────────────────────────────────────

class Trade(BaseModel):
    id: str
    symbol: str
    side: TradeSide
    quantity: float
    price: float
    amount: float
    fee: float = 0
    currency: str = "USD"
    trade_time: str
    source: str = "MANUAL"
    reason: Optional[str] = None
    note: Optional[str] = None
    created_at: str = ""


class CashTransaction(BaseModel):
    id: str
    type: CashTransactionType
    amount: float
    currency: str = "USD"
    transaction_time: str
    note: Optional[str] = None
    created_at: str = ""


class ManualOrderPlan(BaseModel):
    id: str
    symbol: str
    source: str
    action: str
    limit_price: Optional[float] = None
    amount: Optional[float] = None
    quantity: Optional[float] = None
    status: ManualOrderPlanStatus = ManualOrderPlanStatus.SUGGESTED
    filled_quantity: float = 0
    filled_amount: float = 0
    reason: Optional[str] = None
    note: Optional[str] = None
    created_at: str = ""
    expires_at: Optional[str] = None


class RebuiltPosition(BaseModel):
    symbol: str
    quantity: float
    average_cost: float
    realized_pnl: float = 0
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    exposure_pct: Optional[float] = None
    bucket: Optional[str] = None
    position_type: Optional[str] = None


class RebuiltPortfolio(BaseModel):
    account_value: float = 0
    cash: float = 0
    total_market_value: float = 0
    total_exposure_pct: float = 0
    positions: list[RebuiltPosition] = []
    sector_exposures: list[dict] = []


class TradeHistoryContext(BaseModel):
    symbol: str
    last_buy_date: Optional[str] = None
    last_buy_price: Optional[float] = None
    last_buy_amount: Optional[float] = None
    last_sell_date: Optional[str] = None
    last_sell_price: Optional[float] = None
    last_sell_amount: Optional[float] = None
    last_sell_reason: Optional[str] = None
    buys_last_5_days: int = 0
    sells_last_5_days: int = 0
    adds_last_10_days: int = 0
    trims_last_10_days: int = 0
    recently_sold: bool = False
    recently_trimmed: bool = False
    recently_added: bool = False
    cooldown_until: Optional[str] = None
    average_entry_price: Optional[float] = None
    highest_entry_price: Optional[float] = None
    lowest_entry_price: Optional[float] = None
    realized_pnl: float = 0
    unrealized_pnl: float = 0


class DecisionConflict(BaseModel):
    severity: ConflictSeverity
    type: ConflictType
    symbol: Optional[str] = None
    sector_group: Optional[str] = None
    message: str
    recommended_fix: str


class ParsedTradeInput(BaseModel):
    symbol: Optional[str] = None
    side: Optional[TradeSide] = None
    quantity: Optional[float] = None
    amount: Optional[float] = None
    price: Optional[float] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    cash_transaction_type: Optional[CashTransactionType] = None


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
