# app/strategies/base_strategy.py
from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any, List, Optional

from .. import models 
from ..config import logger 

class PortfolioState:
    # This class remains IDENTICAL to the last full version I provided.
    # No changes needed here for this refactor.
    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital
        self.current_cash = initial_capital
        self.current_position_qty = 0
        self.current_position_avg_price = 0.0
        self.current_position_type = None # "LONG" or "SHORT"
        self.trades: List[models.Trade] = []
        self.equity_curve: List[Dict[str, Any]] = [] 
        self.open_trade: Optional[models.Trade] = None
        self.stop_loss_price: Optional[float] = None
        self.take_profit_price: Optional[float] = None

    def record_equity(self, timestamp: pd.Timestamp, current_market_price: float):
        current_value = self.current_cash
        if self.current_position_qty > 0:
            if self.current_position_type == "LONG":
                current_value += self.current_position_qty * current_market_price
            elif self.current_position_type == "SHORT":
                unrealized_pnl = (self.current_position_avg_price - current_market_price) * self.current_position_qty
                current_value += unrealized_pnl 
        self.equity_curve.append({"time": timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp, 
                                  "equity": round(current_value, 2)})

    def _reset_sl_tp(self):
        self.stop_loss_price = None
        self.take_profit_price = None

    def _update_sl_tp(self, entry_price: float, position_type: str, 
                      stop_loss_pct: Optional[float], take_profit_pct: Optional[float]):
        if position_type == "LONG":
            if stop_loss_pct: self.stop_loss_price = round(entry_price * (1 - stop_loss_pct / 100), 2)
            if take_profit_pct: self.take_profit_price = round(entry_price * (1 + take_profit_pct / 100), 2)
        elif position_type == "SHORT":
            if stop_loss_pct: self.stop_loss_price = round(entry_price * (1 + stop_loss_pct / 100), 2)
            if take_profit_pct: self.take_profit_price = round(entry_price * (1 - take_profit_pct / 100), 2)

    def buy(self, timestamp: pd.Timestamp, price: float, qty: int = 1, 
            stop_loss_pct: Optional[float] = None, take_profit_pct: Optional[float] = None):
        action_time = timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp
        if self.current_position_type == "SHORT":
            logger.info(f"{action_time}: Closing existing SHORT position before buying.")
            self.close_position(timestamp, price) 
        
        cost = price * qty
        if self.current_position_type == "LONG": 
            new_total_qty = self.current_position_qty + qty
            new_avg_price = ((self.current_position_avg_price * self.current_position_qty) + (price * qty)) / new_total_qty
            self.current_position_avg_price = round(new_avg_price, 2)
            self.current_position_qty = new_total_qty
            self._update_sl_tp(self.current_position_avg_price, "LONG", stop_loss_pct, take_profit_pct)
            logger.debug(f"{action_time}: Added to LONG {qty} @ {price:.2f}. New Avg Price: {self.current_position_avg_price:.2f}, Qty: {self.current_position_qty}. SL: {self.stop_loss_price}, TP: {self.take_profit_price}")
        else: 
            self.current_position_avg_price = price
            self.current_position_qty = qty
            self.current_position_type = "LONG"
            self.open_trade = models.Trade(entry_time=action_time, entry_price=price, trade_type="LONG", qty=qty, status="OPEN")
            self._update_sl_tp(price, "LONG", stop_loss_pct, take_profit_pct)
            logger.info(f"{action_time}: Opened NEW LONG {qty} @ {price:.2f}. SL: {self.stop_loss_price}, TP: {self.take_profit_price}")
        self.current_cash -= cost

    def sell(self, timestamp: pd.Timestamp, price: float, qty: int = 1,
             stop_loss_pct: Optional[float] = None, take_profit_pct: Optional[float] = None):
        action_time = timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp
        if self.current_position_type == "LONG":
            logger.info(f"{action_time}: Closing existing LONG position before selling short.")
            self.close_position(timestamp, price)
        if self.current_position_type == "SHORT":
            new_total_qty = self.current_position_qty + qty
            new_avg_price = ((self.current_position_avg_price * self.current_position_qty) + (price * qty)) / new_total_qty
            self.current_position_avg_price = round(new_avg_price, 2)
            self.current_position_qty = new_total_qty
            self._update_sl_tp(self.current_position_avg_price, "SHORT", stop_loss_pct, take_profit_pct)
            logger.debug(f"{action_time}: Added to SHORT {qty} @ {price:.2f}. New Avg Price: {self.current_position_avg_price:.2f}, Qty: {self.current_position_qty}. SL: {self.stop_loss_price}, TP: {self.take_profit_price}")
        else: 
            self.current_position_avg_price = price
            self.current_position_qty = qty
            self.current_position_type = "SHORT"
            self.open_trade = models.Trade(entry_time=action_time, entry_price=price, trade_type="SHORT", qty=qty, status="OPEN")
            self._update_sl_tp(price, "SHORT", stop_loss_pct, take_profit_pct)
            logger.info(f"{action_time}: Opened NEW SHORT {qty} @ {price:.2f}. SL: {self.stop_loss_price}, TP: {self.take_profit_price}")

    def close_position(self, timestamp: pd.Timestamp, price: float):
        action_time = timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp
        if self.current_position_qty == 0 or not self.open_trade:
            logger.debug(f"{action_time}: Attempted to close position, but no open position or open_trade found.")
            return
        pnl = 0.0
        trade_type_closed = self.current_position_type
        qty_closed = self.current_position_qty
        if self.current_position_type == "LONG":
            self.current_cash += qty_closed * price
            pnl = (price - self.open_trade.entry_price) * qty_closed
        elif self.current_position_type == "SHORT":
            pnl = (self.open_trade.entry_price - price) * qty_closed
            self.current_cash += pnl
        self.open_trade.exit_time = action_time
        self.open_trade.exit_price = price
        self.open_trade.pnl = round(pnl, 2)
        self.open_trade.status = "CLOSED"
        self.trades.append(self.open_trade.model_copy(deep=True))
        logger.info(f"{action_time}: CLOSED {trade_type_closed} Pos ({qty_closed} units) @ {price:.2f}. PnL: {pnl:.2f}. Cash: {self.current_cash:.2f}")
        self.current_position_qty = 0
        self.current_position_avg_price = 0.0
        self.current_position_type = None
        self.open_trade = None
        self._reset_sl_tp()


class BaseStrategy(ABC):
    strategy_id: str = "base_strategy" 
    strategy_name: str = "Base Strategy"
    strategy_description: str = "Base class for strategies with on-the-fly indicator calculation."

    def __init__(self, shared_ohlc_data: pd.DataFrame, params: Dict[str, Any], portfolio: PortfolioState):
        self.shared_ohlc_data = shared_ohlc_data # Reference to shared OHLC data
        self.params = params
        self.portfolio = portfolio
        
        # Initialize any state needed for incremental indicators or strategy logic
        self._initialize_strategy_state()

    @abstractmethod
    def _initialize_strategy_state(self):
        """
        Initialize strategy-specific state, such as last known indicator values for incremental calculation,
        or pre-calculate constants like EMA multipliers (K).
        This method should be lightweight.
        """
        pass

    @abstractmethod
    def update_indicators_and_generate_signals(self, bar_index: int, current_ohlc_bar: pd.Series) -> Optional[str]:
        """
        This method will now be responsible for:
        1. Updating/calculating necessary indicator values for the current bar (incrementally or on a small lookback).
        2. Using these indicators and the current_ohlc_bar to generate a trading signal.
        Returns: "BUY", "SELL", "CLOSE_LONG", "CLOSE_SHORT", or None.
        """
        pass

    def process_bar(self, bar_index: int):
        if bar_index >= len(self.shared_ohlc_data):
            logger.warning(f"'{self.strategy_id}': bar_index {bar_index} out of bounds for data len {len(self.shared_ohlc_data)}")
            return

        current_ohlc_bar = self.shared_ohlc_data.iloc[bar_index]
        timestamp = current_ohlc_bar.name 
        action_time = timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp

        # 1. Check Stop Loss / Take Profit (remains similar)
        if self.portfolio.current_position_qty > 0:
            exit_price_sl_tp = None
            if self.portfolio.current_position_type == "LONG":
                if self.portfolio.stop_loss_price and current_ohlc_bar['low'] <= self.portfolio.stop_loss_price:
                    exit_price_sl_tp = self.portfolio.stop_loss_price
                    logger.info(f"{action_time}: STOP LOSS for LONG at {exit_price_sl_tp:.2f} (Low: {current_ohlc_bar['low']:.2f})")
                elif self.portfolio.take_profit_price and current_ohlc_bar['high'] >= self.portfolio.take_profit_price:
                    exit_price_sl_tp = self.portfolio.take_profit_price
                    logger.info(f"{action_time}: TAKE PROFIT for LONG at {exit_price_sl_tp:.2f} (High: {current_ohlc_bar['high']:.2f})")
            elif self.portfolio.current_position_type == "SHORT":
                if self.portfolio.stop_loss_price and current_ohlc_bar['high'] >= self.portfolio.stop_loss_price:
                    exit_price_sl_tp = self.portfolio.stop_loss_price
                    logger.info(f"{action_time}: STOP LOSS for SHORT at {exit_price_sl_tp:.2f} (High: {current_ohlc_bar['high']:.2f})")
                elif self.portfolio.take_profit_price and current_ohlc_bar['low'] <= self.portfolio.take_profit_price:
                    exit_price_sl_tp = self.portfolio.take_profit_price
                    logger.info(f"{action_time}: TAKE PROFIT for SHORT at {exit_price_sl_tp:.2f} (Low: {current_ohlc_bar['low']:.2f})")
            
            if exit_price_sl_tp is not None:
                self.portfolio.close_position(timestamp, exit_price_sl_tp)
                return 

        # 2. Update indicators and generate strategy signal for the current bar
        signal = self.update_indicators_and_generate_signals(bar_index, current_ohlc_bar)
        
        execution_type = self.params.get("execution_price_type", "close") # From BacktestRequest
        action_price = current_ohlc_bar['open'] if execution_type == "open" else current_ohlc_bar['close']
        
        log_price_type = "OPEN" if execution_type == "open" else "CLOSE"
        if signal:
            logger.debug(f"Bar {bar_index} ({action_time}) for '{self.strategy_id}': Using {log_price_type} price ({action_price:.2f}) for execution on signal '{signal}'.")

        if signal == "BUY":
            self.portfolio.buy(timestamp, action_price, 
                               stop_loss_pct=self.params.get("stop_loss_pct"), 
                               take_profit_pct=self.params.get("take_profit_pct"))
        elif signal == "SELL": 
            self.portfolio.sell(timestamp, action_price,
                                stop_loss_pct=self.params.get("stop_loss_pct"), 
                                take_profit_pct=self.params.get("take_profit_pct"))
        elif signal == "CLOSE_LONG" and self.portfolio.current_position_type == "LONG":
            self.portfolio.close_position(timestamp, action_price)
        elif signal == "CLOSE_SHORT" and self.portfolio.current_position_type == "SHORT":
            self.portfolio.close_position(timestamp, action_price)

    @classmethod
    def get_info(cls) -> models.StrategyInfo:
        return models.StrategyInfo(
            id=cls.strategy_id, name=cls.strategy_name,
            description=cls.strategy_description, parameters=[]
        )