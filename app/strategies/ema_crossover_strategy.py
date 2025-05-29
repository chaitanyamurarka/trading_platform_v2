# app/strategies/ema_crossover_strategy.py
import pandas as pd
from typing import Dict, Any, List, Optional
# import datetime

from ..models import StrategyParameter, StrategyInfo, IndicatorSeries, IndicatorDataPoint, IndicatorConfig
from .base_strategy import BaseStrategy, PortfolioState
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
                StrategyParameter(name="slow_ema_period", label="Slow EMA Period", type="int", default=20, min_value=10, max_value=500, step=10, description="Period for the slow Exponential Moving Average."),
                StrategyParameter(name="stop_loss_pct", label="Stop Loss %", type="float", 
                                  default=0.0, min_value=0.0, max_value=100.0, step=5.0, 
                                  description="Stop loss percentage from entry price. Set to 0 to disable."),
                StrategyParameter(name="take_profit_pct", label="Take Profit %", type="float", 
                                   default=0.0, min_value=0.0, max_value=100.0, step=5.0, 
                                   description="Take profit percentage from entry price. Set to 0 to disable.")
            ]
        )