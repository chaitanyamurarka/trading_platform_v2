# app/strategies/ema_crossover_strategy.py
import pandas as pd
from typing import Dict, Any, List, Optional
import datetime

from ..models import StrategyParameter, StrategyInfo, IndicatorSeries, IndicatorDataPoint, IndicatorConfig
from .base_strategy import BaseStrategy, PortfolioState # Assuming PortfolioState is also in base_strategy
from ..config import logger

class EMACrossoverStrategy(BaseStrategy):
    strategy_id = "ema_crossover"
    strategy_name = "EMA Crossover"
    strategy_description = "A simple EMA crossover strategy."

    def __init__(self, shared_ohlc_data: pd.DataFrame, params: Dict[str, Any], portfolio: PortfolioState):
        super().__init__(shared_ohlc_data, params, portfolio)
        # _initialize_strategy_state is called by super().__init__

    @classmethod
    def get_info(cls) -> StrategyInfo:
        return StrategyInfo(
            id=cls.strategy_id,
            name=cls.strategy_name,
            description=cls.strategy_description,
            parameters=[
                StrategyParameter(name="fast_ema_period", label="Fast EMA Period", type="int", default=10, min_value=2, max_value=100, step=1, description="Period for the fast Exponential Moving Average."),
                StrategyParameter(name="slow_ema_period", label="Slow EMA Period", type="int", default=20, min_value=5, max_value=500, step=1, description="Period for the slow Exponential Moving Average."),
                StrategyParameter(name="stop_loss_pct", label="Stop Loss %", type="float", default=0.0, min_value=0.0, max_value=0.0, step=0.1, description="Stop loss percentage from entry price."),
                StrategyParameter(name="take_profit_pct", label="Take Profit %", type="float", default=0.0, min_value=0.0, max_value=0.0, step=0.1, description="Take profit percentage from entry price.")
            ]
        )

    def _initialize_strategy_state(self):
        """Initialize strategy-specific state and parameters."""
        try:
            # Ensure EMA periods are integers
            self.fast_period = int(float(self.params.get("fast_ema_period", self.get_info().parameters[0].default)))
            self.slow_period = int(float(self.params.get("slow_ema_period", self.get_info().parameters[1].default)))
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid EMA period values in params: {self.params}. Error: {e}")
            # Fallback to default integer values from get_info()
            self.fast_period = int(self.get_info().parameters[0].default)
            self.slow_period = int(self.get_info().parameters[1].default)
            # Optionally re-raise or handle more gracefully
            raise ValueError(f"EMA periods must be convertible to positive integers. Check strategy parameters. Error: {e}")


        if not (isinstance(self.fast_period, int) and self.fast_period > 0 and 
                isinstance(self.slow_period, int) and self.slow_period > 0):
            raise ValueError(f"EMA periods must be positive integers. Got fast={self.fast_period} (type: {type(self.fast_period)}), slow={self.slow_period} (type: {type(self.slow_period)})")
        
        if self.fast_period >= self.slow_period:
            raise ValueError(f"Fast EMA period ({self.fast_period}) must be less than Slow EMA period ({self.slow_period}).")

        self.stop_loss_pct = self.params.get("stop_loss_pct", self.get_info().parameters[2].default) / 100.0
        self.take_profit_pct = self.params.get("take_profit_pct", self.get_info().parameters[3].default) / 100.0
        
        # Calculate EMAs on the shared OHLC data
        if not self.shared_ohlc_data.empty:
            self.shared_ohlc_data[f'ema_fast'] = self.shared_ohlc_data['close'].ewm(span=self.fast_period, adjust=False).mean()
            self.shared_ohlc_data[f'ema_slow'] = self.shared_ohlc_data['close'].ewm(span=self.slow_period, adjust=False).mean()
        else:
            # Handle empty data case if necessary, e.g., by initializing columns
            self.shared_ohlc_data[f'ema_fast'] = pd.Series(dtype='float64')
            self.shared_ohlc_data[f'ema_slow'] = pd.Series(dtype='float64')

        logger.info(f"EMA Crossover Strategy initialized with Fast EMA: {self.fast_period}, Slow EMA: {self.slow_period}, SL: {self.stop_loss_pct*100}%, TP: {self.take_profit_pct*100}%")

    def update_indicators_and_generate_signals(self, bar_index: int, current_bar_data: pd.Series) -> Optional[str]:
        """
        Updates indicators (if necessary for this strategy, EMAs are pre-calculated)
        and generates trading signals for the current bar.
        This method is called by the BaseStrategy's process_bar method.
        The current_bar_data argument is required by the BaseStrategy's abstract method.
        """
        # For EMA Crossover, EMAs are calculated once in _initialize_strategy_state
        # for the entire dataset. So, no per-bar update is strictly needed here for the indicators themselves.
        # The current_bar_data is available if needed for other logic.
        return self._generate_signals(bar_index)

    def _generate_signals(self, bar_index: int) -> Optional[str]:
        if bar_index < 1:  # Need at least two bars for a crossover
            return None

        # Access pre-calculated EMAs from the shared DataFrame
        # Ensure columns exist before trying to access iloc, especially if shared_ohlc_data could be empty
        if f'ema_fast' not in self.shared_ohlc_data.columns or f'ema_slow' not in self.shared_ohlc_data.columns:
            logger.warning(f"EMA columns not found in shared_ohlc_data at bar_index {bar_index}. Skipping signal generation.")
            return None
        if len(self.shared_ohlc_data) <= bar_index:
            logger.warning(f"bar_index {bar_index} is out of bounds for shared_ohlc_data with length {len(self.shared_ohlc_data)}. Skipping signal generation.")
            return None

        prev_fast_ema = self.shared_ohlc_data[f'ema_fast'].iloc[bar_index - 1]
        current_fast_ema = self.shared_ohlc_data[f'ema_fast'].iloc[bar_index]
        prev_slow_ema = self.shared_ohlc_data[f'ema_slow'].iloc[bar_index - 1]
        current_slow_ema = self.shared_ohlc_data[f'ema_slow'].iloc[bar_index]

        signal = None
        if prev_fast_ema <= prev_slow_ema and current_fast_ema > current_slow_ema:
            signal = "BUY"
        elif prev_fast_ema >= prev_slow_ema and current_fast_ema < current_slow_ema:
            signal = "SELL"
        
        return signal

    def get_indicator_series(self, ohlc_index: pd.DatetimeIndex) -> List[IndicatorSeries]:
        """
        Returns the indicator data series for charting.
        Aligns indicator data with the provided ohlc_index.
        """
        indicators = []

        # Defensive check: if ohlc_index is a list, try to convert it.
        # This is a workaround for incorrect calling code. The ideal fix is in strategy_engine.py.
        if isinstance(ohlc_index, list):
            logger.warning("ohlc_index in get_indicator_series was a list. Attempting conversion to DatetimeIndex. Please fix calling code in strategy_engine.py.")
            try:
                ohlc_index = pd.DatetimeIndex(ohlc_index)
            except Exception as e:
                logger.error(f"Failed to convert ohlc_index list to DatetimeIndex: {e}")
                return indicators # Cannot proceed if conversion fails

        if f'ema_fast' in self.shared_ohlc_data and f'ema_slow' in self.shared_ohlc_data and \
           not self.shared_ohlc_data[f'ema_fast'].empty and not self.shared_ohlc_data[f'ema_slow'].empty:
            
            # Check if ohlc_index (now ensured to be pd.DatetimeIndex or failed) is empty
            if not isinstance(ohlc_index, pd.DatetimeIndex) or ohlc_index.empty:
                logger.warning("ohlc_index is not a valid DatetimeIndex or is empty in get_indicator_series. Cannot align EMA data.")
                return indicators

            aligned_ema_fast = self.shared_ohlc_data[f'ema_fast'].reindex(ohlc_index).ffill()
            aligned_ema_slow = self.shared_ohlc_data[f'ema_slow'].reindex(ohlc_index).ffill()

            fast_ema_points = [
                IndicatorDataPoint(time=int(ts.timestamp()), value=round(val, 2) if pd.notna(val) else None)
                for ts, val in aligned_ema_fast.items() if pd.notna(ts) 
            ]
            slow_ema_points = [
                IndicatorDataPoint(time=int(ts.timestamp()), value=round(val, 2) if pd.notna(val) else None)
                for ts, val in aligned_ema_slow.items() if pd.notna(ts) 
            ]
            
            indicators.append(IndicatorSeries(
                name=f"Fast EMA ({self.fast_period})",
                data=fast_ema_points,
                config=IndicatorConfig(color="rgba(0, 150, 136, 0.8)", lineWidth=2) 
            ))
            indicators.append(IndicatorSeries(
                name=f"Slow EMA ({self.slow_period})",
                data=slow_ema_points,
                config=IndicatorConfig(color="rgba(255, 82, 82, 0.8)", lineWidth=2) 
            ))
        else:
            logger.warning("EMA data not available or empty in shared_ohlc_data for get_indicator_series.")
        return indicators

    def _get_execution_price(self, bar_index: int) -> float:
        """Determines execution price based on strategy settings ('open' or 'close' of current bar)."""
        if self.execution_price_type == 'open':
            return self.shared_ohlc_data['open'].iloc[bar_index]
        return self.shared_ohlc_data['close'].iloc[bar_index] 

    def _get_current_bar_time(self, bar_index: int) -> datetime:
        return self.shared_ohlc_data.index[bar_index].to_pydatetime()

    def _calculate_stop_loss_price(self, entry_price: float, trade_type: str) -> Optional[float]:
        if self.stop_loss_pct > 0:
            if trade_type == "LONG":
                return entry_price * (1 - self.stop_loss_pct)
            elif trade_type == "SHORT":
                return entry_price * (1 + self.stop_loss_pct)
        return None

    def _calculate_take_profit_price(self, entry_price: float, trade_type: str) -> Optional[float]:
        if self.take_profit_pct > 0:
            if trade_type == "LONG":
                return entry_price * (1 + self.take_profit_pct)
            elif trade_type == "SHORT":
                return entry_price * (1 - self.take_profit_pct)
        return None
