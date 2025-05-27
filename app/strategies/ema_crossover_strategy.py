# app/strategies/ema_crossover_strategy.py
import pandas as pd
from typing import Dict, Any, Optional, List # Added List here

from .base_strategy import BaseStrategy, PortfolioState 
from .. import models 
from ..config import logger 

class EMACrossoverStrategy(BaseStrategy):
    strategy_id: str = "ema_crossover"
    strategy_name: str = "EMA Crossover Strategy"
    strategy_description: str = "Generates signals based on two EMA crossovers using incremental calculation."

    def __init__(self, shared_ohlc_data: pd.DataFrame, params: Dict[str, Any], portfolio: PortfolioState):
        super().__init__(shared_ohlc_data, params, portfolio)

    def _initialize_strategy_state(self):
        self.fast_period = self.params.get('fast_ema_period', self.params.get('fast_ma_length', 10))
        self.slow_period = self.params.get('slow_ema_period', self.params.get('slow_ma_length', 20))

        if not (isinstance(self.fast_period, int) and isinstance(self.slow_period, int) and \
                self.fast_period > 0 and self.slow_period > 0):
            raise ValueError(f"EMA periods must be positive integers. Got fast={self.fast_period}, slow={self.slow_period}")
        if self.fast_period >= self.slow_period:
             logger.warning(f"Strategy '{self.strategy_id}': Fast EMA period ({self.fast_period}) "
                            f"is not less than Slow EMA period ({self.slow_period}). This is allowed but unusual.")
        
        self.k_fast = 2 / (self.fast_period + 1)
        self.k_slow = 2 / (self.slow_period + 1)

        self.current_fast_ema: Optional[float] = None
        self.prev_fast_ema: Optional[float] = None
        self.prev2_fast_ema: Optional[float] = None
        
        self.current_slow_ema: Optional[float] = None
        self.prev_slow_ema: Optional[float] = None
        self.prev2_slow_ema: Optional[float] = None
        
        # Initialize lists to store all calculated EMA values for charting
        # Ensure this is done *before* any calls to update_indicators_and_generate_signals if data is not empty
        if not self.shared_ohlc_data.empty:
            self.all_fast_ema_values: List[Optional[float]] = [None] * len(self.shared_ohlc_data)
            self.all_slow_ema_values: List[Optional[float]] = [None] * len(self.shared_ohlc_data)
        else: # Handle empty data case
            self.all_fast_ema_values = []
            self.all_slow_ema_values = []
        
        logger.info(f"'{self.strategy_id}' instance initialized. Params: Fast={self.fast_period}, Slow={self.slow_period}.")


    def _calculate_incremental_ema(self, current_price: float, prev_ema_val: Optional[float], k_multiplier: float) -> float:
        if prev_ema_val is None or pd.isna(prev_ema_val):
            return current_price
        return (current_price * k_multiplier) + (prev_ema_val * (1 - k_multiplier))

    def update_indicators_and_generate_signals(self, bar_index: int, current_ohlc_bar: pd.Series) -> Optional[str]:
        current_close_price = current_ohlc_bar['close']

        self.prev2_fast_ema, self.prev_fast_ema = self.prev_fast_ema, self.current_fast_ema
        self.prev2_slow_ema, self.prev_slow_ema = self.prev_slow_ema, self.current_slow_ema

        self.current_fast_ema = self._calculate_incremental_ema(current_close_price, self.prev_fast_ema, self.k_fast)
        self.current_slow_ema = self._calculate_incremental_ema(current_close_price, self.prev_slow_ema, self.k_slow)

        # Store calculated EMAs for chart, ensure lists are initialized
        if bar_index < len(self.all_fast_ema_values): # Check bounds
             self.all_fast_ema_values[bar_index] = self.current_fast_ema
        if bar_index < len(self.all_slow_ema_values): # Check bounds
             self.all_slow_ema_values[bar_index] = self.current_slow_ema

        if bar_index < 2 or self.prev_fast_ema is None or self.prev_slow_ema is None or \
           self.prev2_fast_ema is None or self.prev2_slow_ema is None:
            return None # Not enough data for crossover signal

        signal = None
        bullish_crossover_condition = self.prev2_fast_ema <= self.prev2_slow_ema and self.prev_fast_ema > self.prev_slow_ema
        bearish_crossover_condition = self.prev2_fast_ema >= self.prev2_slow_ema and self.prev_fast_ema < self.prev_slow_ema

        if bullish_crossover_condition:
            if self.portfolio.current_position_type == "SHORT": signal = "CLOSE_SHORT"
            elif self.portfolio.current_position_type != "LONG": signal = "BUY"
        elif bearish_crossover_condition:
            if self.portfolio.current_position_type == "LONG": signal = "CLOSE_LONG"
            elif self.portfolio.current_position_type != "SHORT": signal = "SELL"
        return signal
        
    # This method MUST be implemented to override the abstract method in BaseStrategy
    def get_indicator_series(self, ohlc_timestamps: List[pd.Timestamp]) -> List[models.IndicatorSeries]:
        indicator_data_list = []
        
        # Ensure 'all_fast_ema_values' and 'all_slow_ema_values' are initialized in _initialize_strategy_state
        # and populated during process_bar calls.
        
        current_fast_ema_period = self.params.get('fast_ma_length', self.params.get('fast_ema_period', self.fast_period))
        current_slow_ema_period = self.params.get('slow_ma_length', self.params.get('slow_ema_period', self.slow_period))

        if hasattr(self, 'all_fast_ema_values') and self.all_fast_ema_values and \
           len(self.all_fast_ema_values) >= len(ohlc_timestamps): # Check length consistency
            fast_ema_points = [
                models.IndicatorDataPoint(time=int(ts.timestamp()), value=self.all_fast_ema_values[i])
                for i, ts in enumerate(ohlc_timestamps) 
                if i < len(self.all_fast_ema_values) and pd.notna(self.all_fast_ema_values[i]) and self.all_fast_ema_values[i] is not None
            ]
            if fast_ema_points: # Only add if there are points
                indicator_data_list.append(models.IndicatorSeries(
                    name=f"Fast EMA ({current_fast_ema_period})",
                    data=fast_ema_points,
                    config=models.IndicatorConfig(color="blue", lineWidth=1)
                ))

        if hasattr(self, 'all_slow_ema_values') and self.all_slow_ema_values and \
           len(self.all_slow_ema_values) >= len(ohlc_timestamps): # Check length consistency
            slow_ema_points = [
                models.IndicatorDataPoint(time=int(ts.timestamp()), value=self.all_slow_ema_values[i])
                for i, ts in enumerate(ohlc_timestamps) 
                if i < len(self.all_slow_ema_values) and pd.notna(self.all_slow_ema_values[i]) and self.all_slow_ema_values[i] is not None
            ]
            if slow_ema_points: # Only add if there are points
                indicator_data_list.append(models.IndicatorSeries(
                    name=f"Slow EMA ({current_slow_ema_period})",
                    data=slow_ema_points,
                    config=models.IndicatorConfig(color="red", lineWidth=1)
                ))
        return indicator_data_list

    @classmethod
    def get_info(cls) -> models.StrategyInfo:
        parameters = [
            models.StrategyParameter(
                name="fast_ma_length", label="Fast EMA Period", type="int", default=10,
                min_value=1, max_value=200, step=1,
                min_opt_range=5, max_opt_range=50, step_opt_range=1,
                category="Entry Logic", description="Period for the faster EMA."
            ),
            models.StrategyParameter(
                name="slow_ma_length", label="Slow EMA Period", type="int", default=20,
                min_value=2, max_value=500, step=1,
                min_opt_range=10, max_opt_range=100, step_opt_range=1,
                category="Entry Logic", description="Period for the slower EMA."
            ),
            models.StrategyParameter(
                name="stop_loss_pct", label="Stop Loss (%)", type="float", default=2.0,
                min_value=0.1, max_value=10.0, step=0.1,
                min_opt_range=0.5, max_opt_range=5.0, step_opt_range=0.1,
                category="Risk Management", description="Stop loss percentage."
            ),
            models.StrategyParameter(
                name="take_profit_pct", label="Take Profit (%)", type="float", default=4.0,
                min_value=0.1, max_value=20.0, step=0.1,
                min_opt_range=1.0, max_opt_range=10.0, step_opt_range=0.1,
                category="Risk Management", description="Take profit percentage."
            )
        ]
        return models.StrategyInfo(
            id=cls.strategy_id, name=cls.strategy_name,
            description=cls.strategy_description, parameters=parameters
        )