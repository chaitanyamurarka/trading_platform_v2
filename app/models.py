# app/models.py
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, validator, field_validator
from datetime import datetime, date

# --- Core System Models ---

class HealthResponse(BaseModel):
    """Response model for health check endpoint."""
    status: str = "OK"
    shoonya_api_status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

# --- Symbol and Instrument Information ---

class TokenInfo(BaseModel):
    """Detailed information for a specific instrument token."""
    exchange: str = Field(..., description="Exchange identifier (e.g., NSE, NFO).")
    token: str = Field(..., description="Unique instrument token for the exchange.")
    symbol: str = Field(..., description="The underlying symbol (e.g., NIFTY, RELIANCE).")
    trading_symbol: Optional[str] = Field(None, description="Full trading symbol or ticker (e.g., NIFTY23OCTFUT, RELIANCE-EQ).")
    instrument: Optional[str] = Field(None, description="Type of instrument (e.g., EQ, FUTIDX, OPTIDX, FUTSTK, OPTSTK).")
    # Add other relevant fields from scripmaster like 'expiry', 'option_type', 'strike_price' if needed directly here.

class AvailableSymbolsResponse(BaseModel):
    """Response model for listing available symbols for an exchange."""
    exchange: str
    symbols: List[TokenInfo]
    count: int

# --- Historical Data ---

class HistoricalDataRequest(BaseModel):
    """Request model for fetching historical OHLCV data."""
    exchange: str = Field(..., description="Exchange (e.g., NSE, NFO, MCX).")
    token: str = Field(..., description="Instrument token specific to the exchange.")
    start_time: date = Field(..., description="Start date for historical data (YYYY-MM-DD).")
    end_time: date = Field(..., description="End date for historical data (YYYY-MM-DD).")
    interval: str = Field(..., description="Candle interval. Examples: '1', '5', '15' (for minutes), '60' (for hourly), 'D' (for daily).")

    @field_validator('interval')
    @classmethod
    def interval_must_be_valid(cls, v: str) -> str:
        """
        Validates the interval.
        These intervals should align with what the data module supports for direct fetching or resampling.
        For direct Shoonya API: '1', '3', '5', '10', '15', '30', '60' (minutes), '240' (day - check Shoonya docs for exact daily code, often 'D' or a number)
        For resampling via pandas: '1T', '5T', '15T', '60T' or '1H', '1D' etc.
        The application logic will need to map these user inputs to API/resampling codes.
        """
        # This list can be expanded based on supported resampling rules and API direct intervals
        # It's a good idea to keep this flexible or map it internally.
        valid_user_intervals = ['1', '3', '5', '10', '15', '30', '60', 'D', '1H', '1T', '5T', '15T'] # Example
        if v not in valid_user_intervals:
            # Consider if this list should come from a config or be more dynamic.
            raise ValueError(f"Interval must be one of {valid_user_intervals}. Received: {v}")
        return v

    @field_validator('end_time')
    @classmethod
    def end_time_must_be_after_start_time(cls, v: date, values: Any) -> date:
        """Validates that end_time is not before start_time."""
        # Pydantic v2 way to get other field values if `field_validator` is used
        # For older Pydantic, you might need `root_validator` or pass `values.data`
        data = values.data
        if 'start_time' in data and v < data['start_time']:
            raise ValueError("end_time must not be before start_time.")
        return v

class OHLCDataPoint(BaseModel):
    """Represents a single OHLCV data point for a specific time."""
    time: datetime = Field(description="Timestamp for the candle (typically start time of the interval).")
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = Field(None, description="Volume for the interval.")
    oi: Optional[int] = Field(None, description="Open Interest for the interval, if applicable.")

    class Config:
        # For Pydantic V2, use `model_config`
        # For Pydantic V1, use `orm_mode = True` if creating from ORM objects
        # However, here we are creating from dicts or other models, so it might not be needed.
        # Example for V2:
        # model_config = {
        #     "from_attributes": True  #  Replaces orm_mode
        # }
        pass


class HistoricalDataResponse(BaseModel):
    """Response model for historical data requests."""
    request_params: HistoricalDataRequest
    data: List[OHLCDataPoint]
    count: int
    message: Optional[str] = Field(None, description="Optional message regarding the data retrieval (e.g., source, warnings).")

# --- Strategy, Backtesting, and Optimization Models ---

class StrategyParameter(BaseModel):
    """Defines a parameter for a trading strategy."""
    name: str = Field(description="Internal name of the parameter.")
    label: Optional[str] = Field(None, description="User-friendly display name for the parameter.")
    type: Literal['int', 'float', 'bool', 'choice'] = Field(description="Data type of the parameter.")
    default: Any = Field(description="Default value for the parameter.")
    value: Optional[Any] = Field(None, description="Actual value to be used (set during backtest/optimization).")
    min_value: Optional[float] = Field(None, description="Minimum allowed value (for numeric types).")
    max_value: Optional[float] = Field(None, description="Maximum allowed value (for numeric types).")
    step: Optional[float] = Field(None, description="Step for numeric ranges (e.g., for optimizers).")
    choices: Optional[List[Any]] = Field(None, description="List of allowed values (for 'choice' type).")
    description: Optional[str] = Field(None, description="Explanation of the parameter.")


class StrategyInfo(BaseModel):
    """Provides metadata about an available trading strategy."""
    id: str = Field(description="Unique identifier for the strategy.")
    name: str = Field(description="User-friendly name of the strategy.")
    description: Optional[str] = Field(None)
    parameters: List[StrategyParameter] = Field(description="List of parameters the strategy accepts.")

class AvailableStrategiesResponse(BaseModel):
    """Response model for listing available strategies."""
    strategies: List[StrategyInfo]

class BacktestRequest(BaseModel):
    """Request model for running a single backtest."""
    exchange: str
    token: str
    start_date: date
    end_date: date
    timeframe: str = Field(description="Candle interval for the backtest (e.g., '5T', '1D'). Must match a valid interval format.")
    strategy_id: str = Field(description="Identifier of the strategy to backtest.")
    parameters: Dict[str, Any] = Field(description="Key-value pairs of strategy parameters and their chosen values.")
    initial_capital: float = Field(default=100000.0, gt=0, description="Initial capital for the backtest.")
    execution_price_type: Literal['open', 'close'] = Field(default='close', description="Price (open or close of the bar) to use for simulated trade execution.")

    @field_validator('timeframe')
    @classmethod
    def timeframe_must_be_valid_interval(cls, v: str) -> str:
        # Reuse or adapt the interval validation from HistoricalDataRequest
        # This ensures consistency in how intervals are specified.
        try:
            HistoricalDataRequest.interval_must_be_valid(v) # Call the validator from the other model
        except ValueError as e:
            raise ValueError(f"Invalid timeframe: {e}")
        return v

class Trade(BaseModel):
    """Represents a single simulated trade in a backtest."""
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    trade_type: Literal["LONG", "SHORT"]
    qty: int = Field(default=1, gt=0)
    pnl: Optional[float] = None
    status: Literal["OPEN", "CLOSED"]

class BacktestResult(BaseModel):
    """Response model containing the results of a backtest."""
    request: BacktestRequest
    # Performance Metrics
    net_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Optional[float] = None # winning_trades / total_trades if total_trades > 0
    average_profit_per_trade: Optional[float] = None
    average_loss_per_trade: Optional[float] = None
    profit_factor: Optional[float] = None # Gross profit / Gross loss
    max_drawdown: float # Maximum peak-to-trough decline during a specific period
    sharpe_ratio: Optional[float] = Field(None, description="Risk-adjusted return (requires risk-free rate, not implemented here).")
    sortino_ratio: Optional[float] = Field(None, description="Risk-adjusted return focusing on downside deviation.")
    # Equity Curve
    equity_curve: List[Dict[str, Any]] = Field(description="List of equity values over time, e.g., [{'time': datetime, 'equity': float}].")
    trades: List[Trade]
    logs: Optional[List[str]] = Field(None, description="Optional logs or messages generated during the backtest.")

class OptimizationParameterRange(BaseModel):
    """Defines the range and step for a parameter during optimization."""
    name: str = Field(description="Name of the strategy parameter to optimize.")
    start_value: Any # Can be int or float
    end_value: Any   # Can be int or float
    step: Any      # Can be int or float

    @field_validator('end_value')
    @classmethod
    def end_value_must_be_gte_start_value(cls, v: Any, values: Any) -> Any:
        data = values.data
        if 'start_value' in data and isinstance(data['start_value'], (int, float)) and isinstance(v, (int, float)):
            if v < data['start_value']:
                raise ValueError("end_value must be greater than or equal to start_value.")
        return v

    @field_validator('step')
    @classmethod
    def step_must_be_positive(cls, v: Any, values: Any) -> Any:
        data = values.data
        if 'start_value' in data and isinstance(data['start_value'], (int, float)) and isinstance(v, (int, float)):
            if v <= 0:
                raise ValueError("step must be a positive value.")
        return v


class OptimizationRequest(BaseModel):
    """Request model for running a strategy parameter optimization."""
    exchange: str
    token: str
    start_date: date
    end_date: date
    timeframe: str
    strategy_id: str
    parameter_ranges: List[OptimizationParameterRange] = Field(description="List of parameters and their ranges to optimize.")
    metric_to_optimize: str = Field(default="net_pnl", description="Performance metric to maximize/minimize (e.g., 'net_pnl', 'sharpe_ratio').")
    execution_price_type: Literal['open', 'close'] = Field(default='close')
    initial_capital: float = Field(default=100000.0, gt=0)

class OptimizationJobStatus(BaseModel):
    """Status of a potentially long-running optimization job."""
    job_id: str
    status: Literal["PENDING", "QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="Job progress from 0.0 to 1.0.")
    message: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    estimated_remaining_time_seconds: Optional[float] = None
    current_iteration: Optional[int] = None # Renamed from current_combination_count
    total_iterations: Optional[int] = None  # Renamed from total_combinations

class OptimizationResultEntry(BaseModel):
    """Result of a single backtest run within an optimization process."""
    parameters: Dict[str, Any] = Field(description="The combination of parameters used for this run.")
    performance_metrics: Dict[str, Any] = Field(description="Key-value pairs of performance metrics for this run (e.g., {'net_pnl': 1234.5}).") # Renamed from 'performance'

class OptimizationResultsResponse(BaseModel):
    """Response model containing the results of an optimization job."""
    job_id: str
    strategy_id: str
    request_details: OptimizationRequest # Include the original request for context
    results: List[OptimizationResultEntry] = Field(description="List of results for each parameter combination tested.")
    best_result: Optional[OptimizationResultEntry] = Field(None, description="The best performing result based on the optimization metric.")
    summary_stats: Optional[Dict[str, Any]] = Field(None, description="Overall summary, e.g., total combinations, time taken.") # Renamed from summary
    total_combinations_tested: int


# Example of how you might define a more specific parameter type using Literal for 'type'
class IntStrategyParameter(StrategyParameter):
    type: Literal['int'] = 'int'
    default: int
    value: Optional[int] = None
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    step: Optional[int] = None

class FloatStrategyParameter(StrategyParameter):
    type: Literal['float'] = 'float'
    default: float
    value: Optional[float] = None
    # min_value, max_value, step are already float in base

# This shows how you could make StrategyParameter more specific if needed,
# but often the flexible version is easier to work with initially.