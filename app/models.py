# app/models.py
from typing import List, Optional, Dict, Any,Literal
from pydantic import BaseModel, Field, validator
from datetime import datetime, date

class HealthResponse(BaseModel):
    status: str
    shoonya_api_status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class TokenInfo(BaseModel):
    exchange: str
    token: str
    symbol: str
    trading_symbol: Optional[str] = None
    instrument: Optional[str] = None

class AvailableSymbolsResponse(BaseModel):
    exchange: str
    symbols: List[TokenInfo]
    count: int

class HistoricalDataRequest(BaseModel):
    exchange: str = Field(..., description="Exchange (e.g., NSE, NFO)")
    token: str = Field(..., description="Instrument token")
    start_time: date = Field(..., description="Start date (YYYY-MM-DD)")
    end_time: date = Field(..., description="End date (YYYY-MM-DD)")
    interval: str = Field(..., description="Candle interval (e.g., '1', '5', '15', 'D' for day)")

    @validator('interval')
    def interval_must_be_valid(cls, v):
        # Add more valid intervals as per Shoonya API or your needs
        valid_intervals = ['1', '3', '5', '10', '15', '30', '60', 'D']
        if v not in valid_intervals:
            raise ValueError(f"Interval must be one of {valid_intervals}")
        return v

class OHLCDataPoint(BaseModel):
    time: datetime # Or str, depending on how Shoonya returns it and how we process
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = None
    oi: Optional[int] = None # Open Interest, if applicable

class HistoricalDataResponse(BaseModel):
    request_params: HistoricalDataRequest
    data: List[OHLCDataPoint]
    count: int
    message: Optional[str] = None

# --- Models for Strategy and Optimization ---

class StrategyParameter(BaseModel):
    name: str
    type: str # e.g., 'int', 'float', 'string_choice' (you can define an Enum for this too)
    default: Optional[Any] = None
    value: Optional[Any] = None  # <<<< MADE THIS OPTIONAL
    min_value: Optional[float] = None # For numeric types if it's a range
    max_value: Optional[float] = None # For numeric types if it's a range
    step: Optional[float] = None      # For numeric types if it's a range
    choices: Optional[List[Any]] = None # For 'string_choice' or categorical types


class StrategyInfo(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    parameters: List[StrategyParameter]

class AvailableStrategiesResponse(BaseModel):
    strategies: List[StrategyInfo]

class BacktestParams(BaseModel):
    # Parameters for a single strategy run (subset of StrategyParameter with specific values)
    # Example: {"fast_ma": 10, "slow_ma": 20, "stop_loss_pct": 2.0}
    # This can be a simple Dict[str, Any] for flexibility or more structured
    # if we want strict validation per strategy.
    params: Dict[str, Any]

class BacktestRequest(BaseModel):
    exchange: str
    token: str
    start_date: date
    end_date: date
    timeframe: str # e.g., "1D", "5m" (needs to map to Shoonya's interval)
    strategy_id: str
    parameters: Dict[str, Any] # e.g., {"fast_ma": 10, "slow_ma": 50, "stop_loss_pct": 2.0}
    execution_price_type: Literal['open', 'close'] = Field(default='close', description="Price to use for trade execution: 'open' or 'close' of the current bar.")

    # Initial capital could be added here if dynamic
    # initial_capital: float = Field(default=100000.0)

class Trade(BaseModel):
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    trade_type: str # "LONG" or "SHORT"
    qty: int = 1
    pnl: Optional[float] = None
    status: str # "OPEN" or "CLOSED"

class BacktestResult(BaseModel):
    request: BacktestRequest
    # Performance Metrics
    net_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    max_drawdown: float
    sharpe_ratio: Optional[float] = None # Requires risk-free rate
    # Further metrics can be added
    # Equity Curve (simplified for now)
    equity_curve: List[Dict[str, Any]] # e.g., [{"time": datetime, "equity": float}]
    trades: List[Trade]
    logs: Optional[List[str]] = None

class OptimizationParameterRange(BaseModel):
    name: str
    start: Any # int or float
    end: Any   # int or float
    step: Any  # int or float

class OptimizationRequest(BaseModel):
    exchange: str
    token: str
    start_date: date
    end_date: date
    timeframe: str
    strategy_id: str
    parameter_ranges: List[OptimizationParameterRange]
    execution_price_type: Literal['open', 'close'] = Field(default='close', description="Global execution price type for this optimization run.")
    initial_capital: float = Field(default=100000.0, description="Initial capital for each backtest in optimization.")

class OptimizationJobStatus(BaseModel):
    job_id: str
    status: str # e.g., "PENDING", "RUNNING", "COMPLETED", "FAILED"
    progress: float = Field(default=0.0, ge=0.0, le=1.0) # 0.0 to 1.0
    message: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    estimated_remaining_time_seconds: Optional[float] = None # Rough estimate
    current_combination_count: Optional[int] = None
    total_combinations: Optional[int] = None

class OptimizationResultEntry(BaseModel):
    parameters: Dict[str, Any] # The combination of parameters used
    performance: Dict[str, Any] # Key-value of performance metrics (e.g., "net_pnl": 1234.5, "total_trades": 10)

class OptimizationResultsResponse(BaseModel):
    job_id: str
    strategy_id: str
    results: List[OptimizationResultEntry]
    summary: Optional[Dict[str, Any]] = None # e.g., best performing parameters based on a metric
    total_combinations_tested: int