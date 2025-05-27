# app/strategies/ema_crossover_strategy.py
import pandas as pd
from typing import Dict, Any, Optional

from .base_strategy import BaseStrategy, PortfolioState 
from .. import models 
from ..config import logger 

class EMACrossoverStrategy(BaseStrategy):
    strategy_id: str = "ema_crossover"
    strategy_name: str = "EMA Crossover Strategy"
    strategy_description: str = "Generates signals based on two EMA crossovers using incremental calculation."

    def __init__(self, shared_ohlc_data: pd.DataFrame, params: Dict[str, Any], portfolio: PortfolioState):
        # The super().__init__ call will invoke self._initialize_strategy_state()
        super().__init__(shared_ohlc_data, params, portfolio)


    def _initialize_strategy_state(self):
        """Initialize EMA periods, multipliers (K), and last known EMA values."""
        self.fast_period = self.params.get('fast_ema_period', 10)
        self.slow_period = self.params.get('slow_ema_period', 20)

        if not (isinstance(self.fast_period, int) and isinstance(self.slow_period, int) and \
                self.fast_period > 0 and self.slow_period > 0):
            raise ValueError("EMA periods must be positive integers.")
        if self.fast_period >= self.slow_period:
             logger.warning(f"Strategy '{self.strategy_id}': Fast EMA period ({self.fast_period}) "
                            f"is not less than Slow EMA period ({self.slow_period}).")
        
        # EMA multipliers
        self.k_fast = 2 / (self.fast_period + 1)
        self.k_slow = 2 / (self.slow_period + 1)

        # State for incremental EMAs (current, previous, day-before-previous)
        self.current_fast_ema: Optional[float] = None
        self.prev_fast_ema: Optional[float] = None
        self.prev2_fast_ema: Optional[float] = None
        
        self.current_slow_ema: Optional[float] = None
        self.prev_slow_ema: Optional[float] = None
        self.prev2_slow_ema: Optional[float] = None
        
        logger.info(f"'{self.strategy_id}' instance initialized for incremental EMAs. "
                    f"Params: Fast={self.fast_period}, Slow={self.slow_period}.")

    def _calculate_incremental_ema(self, current_price: float, prev_ema_val: Optional[float], k_multiplier: float) -> float:
        """ Helper to calculate EMA incrementally. """
        if prev_ema_val is None or pd.isna(prev_ema_val): # First calculation, use current price as seed
            return current_price
        return (current_price * k_multiplier) + (prev_ema_val * (1 - k_multiplier))

    def update_indicators_and_generate_signals(self, bar_index: int, current_ohlc_bar: pd.Series) -> Optional[str]:
        current_close_price = current_ohlc_bar['close']

        # 1. Update EMA history (shift values back)
        self.prev2_fast_ema = self.prev_fast_ema
        self.prev_fast_ema = self.current_fast_ema
        
        self.prev2_slow_ema = self.prev_slow_ema
        self.prev_slow_ema = self.current_slow_ema

        # 2. Calculate current EMAs incrementally based on the *newly shifted* previous_ema
        self.current_fast_ema = self._calculate_incremental_ema(current_close_price, self.prev_fast_ema, self.k_fast)
        self.current_slow_ema = self._calculate_incremental_ema(current_close_price, self.prev_slow_ema, self.k_slow)

        # --- Signal Generation Logic (uses the now updated prev & prev2 values) ---
        # Minimum data needed for prev2_ema to be valid (after two shifts from initial seeding)
        if bar_index < 2: # Not enough history for prev2 values to be meaningful
            # Log for first few bars if needed
            if bar_index < max(self.fast_period, self.slow_period) + 5: 
                 logger.debug(f"Bar {bar_index} ({current_ohlc_bar.name}) for '{self.strategy_id}': Warming up EMAs (bar_index < 2). "
                              f"P2F:{self.prev2_fast_ema}, P2S:{self.prev2_slow_ema}, "
                              f"P1F:{self.prev_fast_ema}, P1S:{self.prev_slow_ema}, "
                              f"CurF:{self.current_fast_ema}, CurS:{self.current_slow_ema}")
            return None

        # Ensure all necessary previous EMAs are now populated (no longer NaN/None after seeding and a few iterations)
        if self.prev2_fast_ema is None or self.prev2_slow_ema is None or \
           self.prev_fast_ema is None or self.prev_slow_ema is None:
            if bar_index < max(self.fast_period, self.slow_period) + 5:
                 logger.debug(f"Bar {bar_index} ({current_ohlc_bar.name}) for '{self.strategy_id}': Still warming up (some prev EMAs are None). "
                              f"P2F:{self.prev2_fast_ema}, P2S:{self.prev2_slow_ema}, "
                              f"P1F:{self.prev_fast_ema}, P1S:{self.prev_slow_ema}, "
                              f"CurF:{self.current_fast_ema}, CurS:{self.current_slow_ema}")
            return None


        def sf(val): return f"{val:.2f}" if pd.notna(val) and val is not None else "None"
        log_this_bar = bar_index < 50 # Or another condition

        if log_this_bar:
            logger.debug(f"Bar {bar_index} ({current_ohlc_bar.name}) for '{self.strategy_id}': C={current_close_price:.2f}, "
                         f"P2F:{sf(self.prev2_fast_ema)}, P2S:{sf(self.prev2_slow_ema)}, "
                         f"P1F:{sf(self.prev_fast_ema)}, P1S:{sf(self.prev_slow_ema)}, "
                         f"CurF:{sf(self.current_fast_ema)}, CurS:{sf(self.current_slow_ema)}, "
                         f"Pos: {self.portfolio.current_position_type}")
        
        signal = None
        # Crossover condition: checks if prev_fast crossed prev_slow, using prev2 as reference
        bullish_crossover_condition = self.prev2_fast_ema <= self.prev2_slow_ema and self.prev_fast_ema > self.prev_slow_ema
        bearish_crossover_condition = self.prev2_fast_ema >= self.prev2_slow_ema and self.prev_fast_ema < self.prev_slow_ema

        if bullish_crossover_condition:
            logger.info(f"Bar {bar_index} ({current_ohlc_bar.name}) for '{self.strategy_id}': BULLISH CROSSOVER. "
                        f"P2F:{sf(self.prev2_fast_ema)}, P2S:{sf(self.prev2_slow_ema)}, P1F:{sf(self.prev_fast_ema)}, P1S:{sf(self.prev_slow_ema)}")
            if self.portfolio.current_position_type == "SHORT":
                signal = "CLOSE_SHORT"
            elif self.portfolio.current_position_type != "LONG":
                signal = "BUY"
        
        elif bearish_crossover_condition:
            logger.info(f"Bar {bar_index} ({current_ohlc_bar.name}) for '{self.strategy_id}': BEARISH CROSSOVER. "
                        f"P2F:{sf(self.prev2_fast_ema)}, P2S:{sf(self.prev2_slow_ema)}, P1F:{sf(self.prev_fast_ema)}, P1S:{sf(self.prev_slow_ema)}")
            if self.portfolio.current_position_type == "LONG":
                signal = "CLOSE_LONG"
            elif self.portfolio.current_position_type != "SHORT":
                signal = "SELL"
        
        if signal:
             logger.info(f"Bar {bar_index} ({current_ohlc_bar.name}) for '{self.strategy_id}': Signal: {signal}")
        elif log_this_bar:
             logger.debug(f"Bar {bar_index} ({current_ohlc_bar.name}) for '{self.strategy_id}': No crossover. Pos: {self.portfolio.current_position_type}")
             
        return signal

    @classmethod
    def get_info(cls) -> models.StrategyInfo:
        parameters = [
            models.StrategyParameter(name="fast_ema_period", type="int", default=10, value=10, min_value=1, max_value=200, step=1), 
            models.StrategyParameter(name="slow_ema_period", type="int", default=20, value=20, min_value=2, max_value=500, step=1), 
            models.StrategyParameter(name="stop_loss_pct", type="float", default=2.0, value=2.0, min_value=0.1, max_value=10.0, step=0.1),
            models.StrategyParameter(name="take_profit_pct", type="float", default=4.0, value=4.0, min_value=0.1, max_value=20.0, step=0.1)
        ]
        return models.StrategyInfo(
            id=cls.strategy_id, name=cls.strategy_name,
            description=cls.strategy_description, parameters=parameters
        )