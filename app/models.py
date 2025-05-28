# app/models.py
from typing import List, Optional, Dict, Any, Literal, Union # Added Union
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
        valid_user_intervals = ['1', '3', '5', '10', '15', '30', '60', 'D', '1H', '1T', '5T', '15T', '1min', '5min', '1D'] # Added user-friendly versions
        if v not in valid_user_intervals:
            raise ValueError(f"Interval must be one of {valid_user_intervals}. Received: {v}")
        return v

    @field_validator('end_time')
    @classmethod
    def end_time_must_be_after_start_time(cls, v: date, values: Any) -> date:
        data = values.data
        if 'start_time' in data and v < data['start_time']:
            raise ValueError("end_time must not be before start_time.")
        return v

class OHLCDataPoint(BaseModel):
    """Represents a single OHLCV data point for a specific time."""
    time: Union[datetime, int] = Field(description="Timestamp for the candle (can be datetime object or UNIX timestamp in seconds).") # Modified to Union
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = Field(None, description="Volume for the interval.")
    oi: Optional[int] = Field(None, description="Open Interest for the interval, if applicable.")

    class Config:
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
    # Proposed additions for UI/UX enhancements
    min_opt_range: Optional[float] = Field(None, description="Default minimum value for optimization range if applicable.")
    max_opt_range: Optional[float] = Field(None, description="Default maximum value for optimization range if applicable.")
    step_opt_range: Optional[float] = Field(None, description="Default step for optimization range if applicable.")
    category: Optional[str] = Field(None, description="UI Category (e.g., 'Entry Logic', 'Risk Management', 'General').")

class StrategyInfo(BaseModel):
    """Provides metadata about an available trading strategy."""
    id: str = Field(description="Unique identifier for the strategy.")
    name: str = Field(description="User-friendly name of the strategy.")
    description: Optional[str] = Field(None)
    parameters: List[StrategyParameter] = Field(description="List of parameters the strategy accepts.")

class AvailableStrategiesResponse(BaseModel):
    """Response model for listing available strategies."""
    strategies: List[StrategyInfo]

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

class OptimizationParameterRange(BaseModel):
    """Defines the range and step for a parameter during optimization."""
    name: str = Field(description="Name of the strategy parameter to optimize.")
    start_value: Any
    end_value: Any
    step: Any

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
            if v <= 0: # Step must be positive, direction is handled in generation
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
    current_iteration: Optional[int] = None
    total_iterations: Optional[int] = None

class OptimizationResultEntry(BaseModel):
    """Result of a single backtest run within an optimization process."""
    parameters: Dict[str, Any] = Field(description="The combination of parameters used for this run.")
    performance_metrics: Dict[str, Any] = Field(description="Key-value pairs of performance metrics for this run (e.g., {'net_pnl': 1234.5}).")

class OptimizationResultsResponse(BaseModel):
    """Response model containing the results of an optimization job."""
    job_id: str
    strategy_id: str
    request_details: OptimizationRequest
    results: List[OptimizationResultEntry]
    best_result: Optional[OptimizationResultEntry] = Field(None, description="The best performing result based on the optimization metric.")
    summary_stats: Optional[Dict[str, Any]] = Field(None, description="Overall summary, e.g., total combinations, time taken.")
    total_combinations_tested: int

# --- New Models for Chart Data Endpoint ---

class ChartDataRequest(BaseModel):
    exchange: str
    token: str
    timeframe: str = Field(description="e.g., '1min', '5min', '1H', '1D'")
    start_date: Optional[date] = None # Optional for loading specific historical range
    end_date: Optional[date] = None   # Optional for loading specific historical range
    strategy_id: Optional[str] = Field(None, description="Nullable: if no strategy, only OHLC")
    strategy_params: Optional[Dict[str, Any]] = Field({}, description="Current parameters for the selected strategy")

    @field_validator('timeframe')
    @classmethod
    def timeframe_must_be_valid_chart_interval(cls, v: str) -> str:
        try:
            # Reuse interval validation, ensuring it covers chart-friendly formats
            HistoricalDataRequest.interval_must_be_valid(v)
        except ValueError as e:
            raise ValueError(f"Invalid timeframe for chart: {e}")
        return v

class IndicatorDataPoint(BaseModel):
    time: int # UNIX timestamp in seconds
    value: Optional[float] = None # Allow for NaN or gaps in indicator data

class IndicatorConfig(BaseModel):
    color: str = "blue"
    lineWidth: int = 1
    paneId: str = "main_chart" # e.g., "main_chart", "rsi_pane"
    priceScaleId: Optional[str] = None # e.g., "rsi_price_scale" for separate y-axis

class IndicatorSeries(BaseModel):
    name: str # For display/legend, e.g., "Fast EMA (10)"
    data: List[IndicatorDataPoint]
    config: IndicatorConfig

class TradeMarker(BaseModel):
    time: int # UNIX timestamp in seconds
    position: Literal["aboveBar", "belowBar", "inBar"] = "belowBar"
    color: str = "green"
    shape: Literal["arrowUp", "arrowDown", "circle", "square"] = "arrowUp"
    text: Optional[str] = None

class ChartDataResponse(BaseModel):
    ohlc_data: List[OHLCDataPoint] # OHLCDataPoint.time should be UNIX timestamp
    indicator_data: List[IndicatorSeries] = []
    trade_markers: List[TradeMarker] = []
    chart_header_info: str = ""
    timeframe_actual: str

class CancelOptimizationResponse(BaseModel):
    status: str
    job_id: str

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