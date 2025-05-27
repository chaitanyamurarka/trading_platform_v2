# app/strategies/ema_crossover_strategy.py
import pandas as pd
from typing import Dict, Any, Optional, List

from .base_strategy import BaseStrategy, PortfolioState 
from .. import models 
from ..config import logger 

class EMACrossoverStrategy(BaseStrategy):
    strategy_id: str = "ema_crossover"
    strategy_name: str = "EMA Crossover Strategy"
    strategy_description: str = "Generates buy/sell signals based on crossover of two EMAs."

    def __init__(self, shared_ohlc_data: pd.DataFrame, params: Dict[str, Any], portfolio: PortfolioState):
        super().__init__(shared_ohlc_data, params, portfolio)
        # _init_indicators is called by super()

    def _init_indicators(self):
        """
        Validate periods. No heavy calculation or data copying here.
        We could pre-calculate K values for EMA if using incremental EMA.
        For on-the-fly slice-based calculation, this might just validate params.
        """
        self.fast_period = self.params.get('fast_ema_period', 10)
        self.slow_period = self.params.get('slow_ema_period', 20)

        if not isinstance(self.fast_period, int) or not isinstance(self.slow_period, int) or \
           self.fast_period <= 0 or self.slow_period <= 0:
            raise ValueError("EMA periods must be positive integers.")
        logger.info(f"'{self.strategy_id}' initialized. Params: Fast={self.fast_period}, Slow={self.slow_period}.")


    def get_indicator_values(self, bar_index: int) -> Optional[Dict[str, Any]]:
        """
        Calculates EMAs for current bar_index and required previous bars on-the-fly.
        Needs to look back enough to get prev2 values.
        """
        # Determine the required lookback window for calculations
        # Longest period + number of shifts (2 for prev2)
        required_lookback = max(self.fast_period, self.slow_period) + 2 

        if bar_index < required_lookback -1 : # Need enough data points to calculate the longest EMA and shift it twice
            # Example: slow_period=20, need 20 points for EMA, +2 for shift(2) -> index 21 is first valid point for prev2_slow_ema
            # So if bar_index is less than (20+2-1) = 21, it's not enough.
            return None 

        # Define the slice of data needed: from start of data up to current bar_index
        # Pandas slicing iloc[:end] includes end-1. So, iloc[:bar_index + 1] includes current bar.
        start_slice_idx = 0 # Could optimize by slicing a smaller window, but full history up to bar_index is safest for EWM
        current_data_slice = self.shared_ohlc_data['close'].iloc[start_slice_idx : bar_index + 1]
        
        if len(current_data_slice) < required_lookback: # Double check after slicing
            return None

        # Calculate EMAs on this slice
        fast_ema_series = current_data_slice.ewm(span=self.fast_period, adjust=False).mean()
        slow_ema_series = current_data_slice.ewm(span=self.slow_period, adjust=False).mean()

        # Get the required values (current, prev, prev2)
        # These are relative to the end of the fast_ema_series/slow_ema_series
        # which corresponds to bar_index in the original shared_ohlc_data
        
        # Check if we have enough calculated EMA values (at least 3 for current, prev, prev2)
        if len(fast_ema_series) < 3 or len(slow_ema_series) < 3:
            return None # Not enough data points yet for prev2_ema even after slicing

        indicators = {
            "fast_ema": fast_ema_series.iloc[-1], # Current bar's fast_ema
            "slow_ema": slow_ema_series.iloc[-1], # Current bar's slow_ema
            "prev_fast_ema": fast_ema_series.iloc[-2],
            "prev_slow_ema": slow_ema_series.iloc[-2],
            "prev2_fast_ema": fast_ema_series.iloc[-3],
            "prev2_slow_ema": slow_ema_series.iloc[-3]
        }
        return indicators

    def generate_signals(self, bar_index: int, current_ohlc_bar: pd.Series, indicators: Dict[str, Any]) -> Optional[str]:
        log_this_bar = bar_index < 50 # Or some other condition for focused logging

        prev_fast = indicators.get('prev_fast_ema')
        prev_slow = indicators.get('prev_slow_ema')
        prev2_fast = indicators.get('prev2_fast_ema')
        prev2_slow = indicators.get('prev2_slow_ema')

        def sf(val): return f"{val:.2f}" if pd.notna(val) else "NaN"

        # The None check for indicators is now implicitly handled by get_indicator_values returning None
        # If get_indicator_values returned None, generate_signals wouldn't be called with valid indicators.
        # However, individual values from the dict could still be None if calculation failed for some reason.
        if any(pd.isna(v) for v in [prev_fast, prev_slow, prev2_fast, prev2_slow]):
            if log_this_bar:
                 logger.debug(f"Bar {bar_index} ({current_ohlc_bar.name}): Indicator values contain NaN after get_indicator_values. "
                              f"P2F:{sf(prev2_fast)}, P2S:{sf(prev2_slow)}, P1F:{sf(prev_fast)}, P1S:{sf(prev_slow)}")
            return None


        if log_this_bar:
            logger.debug(f"Bar {bar_index} ({current_ohlc_bar.name}): Close={current_ohlc_bar['close']:.2f}, "
                         f"P2F:{sf(prev2_fast)}, P2S:{sf(prev2_slow)}, P1F:{sf(prev_fast)}, P1S:{sf(prev_slow)}, "
                         f"Pos: {self.portfolio.current_position_type}")

        signal = None
        bullish_crossover_condition = prev2_fast <= prev2_slow and prev_fast > prev_slow
        bearish_crossover_condition = prev2_fast >= prev2_slow and prev_fast < prev_slow

        if bullish_crossover_condition:
            logger.info(f"Bar {bar_index} ({current_ohlc_bar.name}): BULLISH CROSSOVER DETECTED. "
                        f"P2F:{sf(prev2_fast)}, P2S:{sf(prev2_slow)}, P1F:{sf(prev_fast)}, P1S:{sf(prev_slow)}")
            if self.portfolio.current_position_type == "SHORT":
                signal = "CLOSE_SHORT"
            elif self.portfolio.current_position_type != "LONG":
                signal = "BUY"
        
        elif bearish_crossover_condition:
            logger.info(f"Bar {bar_index} ({current_ohlc_bar.name}): BEARISH CROSSOVER DETECTED. "
                        f"P2F:{sf(prev2_fast)}, P2S:{sf(prev2_slow)}, P1F:{sf(prev_fast)}, P1S:{sf(prev_slow)}")
            if self.portfolio.current_position_type == "LONG":
                signal = "CLOSE_LONG"
            elif self.portfolio.current_position_type != "SHORT":
                signal = "SELL"
        
        # Logging the final generated signal
        if signal:
             logger.info(f"Bar {bar_index} ({current_ohlc_bar.name}): Signal: {signal} "
                         f"(P2F:{sf(prev2_fast)}, P2S:{sf(prev2_slow)}, P1F:{sf(prev_fast)}, P1S:{sf(prev_slow)}, Pos:{self.portfolio.current_position_type})")
        elif log_this_bar: # Log if it's an early bar and no signal
             logger.debug(f"Bar {bar_index} ({current_ohlc_bar.name}): No crossover, no signal. Pos: {self.portfolio.current_position_type}")
             
        return signal

    @classmethod
    def get_info(cls) -> models.StrategyInfo:
        # ... (get_info remains the same, defining parameters)
        parameters = [
            models.StrategyParameter(name="fast_ema_period", type="int", default=10, min_value=1, max_value=100, step=1), 
            models.StrategyParameter(name="slow_ema_period", type="int", default=20, min_value=2, max_value=200, step=1), 
            models.StrategyParameter(name="stop_loss_pct", type="float", default=2.0, value=2.0, min_value=0.1, max_value=10.0, step=0.1), # Added value=default for StrategyParameter model if it's mandatory
            models.StrategyParameter(name="take_profit_pct", type="float", default=4.0, value=4.0, min_value=0.1, max_value=20.0, step=0.1) # Added value=default
        ]
        return models.StrategyInfo(
            id=cls.strategy_id, name=cls.strategy_name,
            description=cls.strategy_description, parameters=parameters
        )