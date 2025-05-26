# app/strategies/ema_crossover_strategy.py
import pandas as pd
from typing import Dict, Any, Optional, List

from .base_strategy import BaseStrategy, PortfolioState # PortfolioState might not be directly used here if it's only in BaseStrategy
from .. import models 
from ..config import logger 


class EMACrossoverStrategy(BaseStrategy):
    strategy_id: str = "ema_crossover"
    strategy_name: str = "EMA Crossover Strategy"
    strategy_description: str = "Generates buy/sell signals based on the crossover of two Exponential Moving Averages."

    def __init__(self, data: pd.DataFrame, params: Dict[str, Any], portfolio: PortfolioState):
        super().__init__(data, params, portfolio)

    def _init_indicators(self):
        fast_period = self.params.get('fast_ema_period', 10)
        slow_period = self.params.get('slow_ema_period', 20)

        if not isinstance(fast_period, int) or not isinstance(slow_period, int) or \
           fast_period <= 0 or slow_period <= 0:
            raise ValueError("EMA periods must be positive integers.")
        
        # Indicators are added to self.data
        self.data['fast_ema'] = self.data['close'].ewm(span=fast_period, adjust=False).mean()
        self.data['slow_ema'] = self.data['close'].ewm(span=slow_period, adjust=False).mean()
        
        self.data['prev_fast_ema'] = self.data['fast_ema'].shift(1)
        self.data['prev_slow_ema'] = self.data['slow_ema'].shift(1)
        self.data['prev2_fast_ema'] = self.data['fast_ema'].shift(2)
        self.data['prev2_slow_ema'] = self.data['slow_ema'].shift(2)
        logger.info(f"'{self.strategy_id}' initialized. Parameters: Fast={fast_period}, Slow={slow_period}. Data shape for indicators: {self.data.shape}")

    def generate_signals_for_bar(self, current_bar_with_indicators: pd.Series, bar_index: int) -> Optional[str]:
        # current_bar_with_indicators is a row from self.data and includes EMA columns
        log_this_bar = bar_index < 50 # Log first 50 bars to see initial indicator values

        if bar_index < 2: 
            if log_this_bar:
                logger.debug(f"Bar {bar_index} ({current_bar_with_indicators.name}): Not enough data for full EMA comparison yet.")
            return None

        # Now these .get calls will work because current_bar_with_indicators is from self.data
        prev_fast = current_bar_with_indicators.get('prev_fast_ema')
        prev_slow = current_bar_with_indicators.get('prev_slow_ema')
        prev2_fast = current_bar_with_indicators.get('prev2_fast_ema')
        prev2_slow = current_bar_with_indicators.get('prev2_slow_ema')

        def sf(val): return f"{val:.2f}" if pd.notna(val) else "NaN"

        if pd.isna(prev_fast) or pd.isna(prev_slow) or pd.isna(prev2_fast) or pd.isna(prev2_slow):
            if log_this_bar:
                logger.debug(f"Bar {bar_index} ({current_bar_with_indicators.name}): EMA values still NaN. "
                             f"P2F:{sf(prev2_fast)}, P2S:{sf(prev2_slow)}, P1F:{sf(prev_fast)}, P1S:{sf(prev_slow)}")
            return None 
        
        if log_this_bar:
            logger.debug(f"Bar {bar_index} ({current_bar_with_indicators.name}): Close={current_bar_with_indicators['close']:.2f}, "
                         f"P2F:{sf(prev2_fast)}, P2S:{sf(prev2_slow)}, P1F:{sf(prev_fast)}, P1S:{sf(prev_slow)}, "
                         f"Pos: {self.portfolio.current_position_type}")

        signal = None
        bullish_crossover_condition = prev2_fast <= prev2_slow and prev_fast > prev_slow
        bearish_crossover_condition = prev2_fast >= prev2_slow and prev_fast < prev_slow

        if bullish_crossover_condition:
            logger.info(f"Bar {bar_index} ({current_bar_with_indicators.name}): BULLISH CROSSOVER DETECTED. "
                        f"P2F:{sf(prev2_fast)}, P2S:{sf(prev2_slow)}, P1F:{sf(prev_fast)}, P1S:{sf(prev_slow)}")
            if self.portfolio.current_position_type == "SHORT":
                signal = "CLOSE_SHORT"
                logger.info(f"Bar {bar_index} ({current_bar_with_indicators.name}): Signal: CLOSE_SHORT (bullish crossover)")
            elif self.portfolio.current_position_type != "LONG":
                signal = "BUY"
                logger.info(f"Bar {bar_index} ({current_bar_with_indicators.name}): Signal: BUY")
        
        elif bearish_crossover_condition:
            logger.info(f"Bar {bar_index} ({current_bar_with_indicators.name}): BEARISH CROSSOVER DETECTED. "
                        f"P2F:{sf(prev2_fast)}, P2S:{sf(prev2_slow)}, P1F:{sf(prev_fast)}, P1S:{sf(prev_slow)}")
            if self.portfolio.current_position_type == "LONG":
                signal = "CLOSE_LONG"
                logger.info(f"Bar {bar_index} ({current_bar_with_indicators.name}): Signal: CLOSE_LONG (bearish crossover)")
            elif self.portfolio.current_position_type != "SHORT":
                signal = "SELL"
                logger.info(f"Bar {bar_index} ({current_bar_with_indicators.name}): Signal: SELL")
        
        if signal and not log_this_bar: 
             logger.debug(f"Bar {bar_index} ({current_bar_with_indicators.name}): Close={current_bar_with_indicators['close']:.2f}, "
                         f"P2F:{sf(prev2_fast)}, P2S:{sf(prev2_slow)}, P1F:{sf(prev_fast)}, P1S:{sf(prev_slow)}, "
                         f"Pos: {self.portfolio.current_position_type}, FINAL SIGNAL: {signal}")
        elif log_this_bar and not signal:
             logger.debug(f"Bar {bar_index} ({current_bar_with_indicators.name}): No crossover, no signal. Pos: {self.portfolio.current_position_type}")

        return signal

    @classmethod
    def get_info(cls) -> models.StrategyInfo:
        parameters = [
            models.StrategyParameter(name="fast_ema_period", type="int", default=10, min_value=1, max_value=100, step=1), 
            models.StrategyParameter(name="slow_ema_period", type="int", default=20, min_value=2, max_value=200, step=1), 
            models.StrategyParameter(name="stop_loss_pct", type="float", default=2.0, min_value=0.1, max_value=10.0, step=0.1),
            models.StrategyParameter(name="take_profit_pct", type="float", default=4.0, min_value=0.1, max_value=20.0, step=0.1)
        ]
        return models.StrategyInfo(
            id=cls.strategy_id, name=cls.strategy_name,
            description=cls.strategy_description, parameters=parameters
        )