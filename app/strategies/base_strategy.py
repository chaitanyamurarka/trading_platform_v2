# app/strategies/base_strategy.py
from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any, List, Optional

from .. import models # For Trade, StrategyInfo, StrategyParameter models
from ..config import logger 

class PortfolioState:
    # ... (PortfolioState class remains IDENTICAL to the last complete version I provided) ...
    # This class is already managing state per-combination and is relatively lightweight.
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
    strategy_description: str = "This is a base class and should not be used directly."

    def __init__(self, shared_ohlc_data: pd.DataFrame, params: Dict[str, Any], portfolio: PortfolioState):
        """
        Args:
            shared_ohlc_data (pd.DataFrame): A reference to the shared, read-only OHLCV data.
                                            The strategy should NOT modify this DataFrame directly.
            params (Dict[str, Any]): Parameters specific to this strategy instance.
            portfolio (PortfolioState): The portfolio state object for this backtest run.
        """
        self.shared_ohlc_data = shared_ohlc_data # Store a REFERENCE, not a copy
        self.params = params
        self.portfolio = portfolio
        
        # _init_indicators might be used to pre-calculate constants or setup small state
        # for incremental indicators, but NOT to create a full self.data copy with indicators.
        self._init_indicators() 

    @abstractmethod
    def _init_indicators(self):
        """
        Initialize any small state needed for on-the-fly indicator calculation.
        Avoid heavy computations or storing large data here.
        Example: Store K for incremental EMA: self.k_fast = 2 / (self.params['fast_ema_period'] + 1)
        """
        pass

    @abstractmethod
    def get_indicator_values(self, bar_index: int) -> Dict[str, Any]:
        """
        Calculates or retrieves necessary indicator values for the given bar_index
        using self.shared_ohlc_data and self.params.
        This is where "on-the-fly" calculation for the current bar happens.
        Returns a dictionary of indicator names to their values for the current context.
        E.g., {"fast_ema": 75.5, "slow_ema": 72.3, "prev_fast_ema": 75.0, ...}
        """
        pass

    @abstractmethod
    def generate_signals(self, bar_index: int, current_ohlc_bar: pd.Series, indicators: Dict[str, Any]) -> Optional[str]:
        """
        Generate "BUY", "SELL", "CLOSE_LONG", "CLOSE_SHORT", or None/HOLD
        based on current_ohlc_bar and the calculated indicators.
        """
        pass

    def process_bar(self, bar_index: int):
        """Processes a single bar: calculates indicators, checks SL/TP, then strategy signals."""
        if bar_index >= len(self.shared_ohlc_data):
            logger.warning(f"bar_index {bar_index} is out of bounds for shared_ohlc_data with length {len(self.shared_ohlc_data)}")
            return

        current_ohlc_bar = self.shared_ohlc_data.iloc[bar_index]
        timestamp = current_ohlc_bar.name 
        action_time = timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp

        # 1. Calculate/Retrieve indicators for the current context (current and previous bars as needed)
        # This now happens before SL/TP checks if SL/TP depend on dynamic indicators.
        # For simplicity, if SL/TP are fixed % from entry, this order is fine.
        # If SL/TP are dynamic (e.g., ATR based), indicators might be needed first.
        # For now, let's assume SL/TP prices are already set in portfolio state.
        
        # Check Stop Loss / Take Profit for existing positions
        if self.portfolio.current_position_qty > 0:
            exit_price_sl_tp = None
            # ... (SL/TP logic identical to previous version, using current_ohlc_bar['low'] and ['high']) ...
            if self.portfolio.current_position_type == "LONG":
                if self.portfolio.stop_loss_price and current_ohlc_bar['low'] <= self.portfolio.stop_loss_price:
                    exit_price_sl_tp = self.portfolio.stop_loss_price
                    logger.info(f"{action_time}: STOP LOSS triggered for LONG at {exit_price_sl_tp:.2f} (Low: {current_ohlc_bar['low']:.2f})")
                elif self.portfolio.take_profit_price and current_ohlc_bar['high'] >= self.portfolio.take_profit_price:
                    exit_price_sl_tp = self.portfolio.take_profit_price
                    logger.info(f"{action_time}: TAKE PROFIT triggered for LONG at {exit_price_sl_tp:.2f} (High: {current_ohlc_bar['high']:.2f})")
            elif self.portfolio.current_position_type == "SHORT":
                if self.portfolio.stop_loss_price and current_ohlc_bar['high'] >= self.portfolio.stop_loss_price:
                    exit_price_sl_tp = self.portfolio.stop_loss_price
                    logger.info(f"{action_time}: STOP LOSS triggered for SHORT at {exit_price_sl_tp:.2f} (High: {current_ohlc_bar['high']:.2f})")
                elif self.portfolio.take_profit_price and current_ohlc_bar['low'] <= self.portfolio.take_profit_price:
                    exit_price_sl_tp = self.portfolio.take_profit_price
                    logger.info(f"{action_time}: TAKE PROFIT triggered for SHORT at {exit_price_sl_tp:.2f} (Low: {current_ohlc_bar['low']:.2f})")
            
            if exit_price_sl_tp is not None:
                self.portfolio.close_position(timestamp, exit_price_sl_tp)
                return 

        # 2. Get current indicator values (on-the-fly)
        indicators = self.get_indicator_values(bar_index)
        if not indicators: # If indicators can't be calculated (e.g., not enough data yet for lookbacks)
            logger.debug(f"Bar {bar_index} ({action_time}): Indicators not available yet.")
            return

        # 3. Generate strategy signals based on OHLC and indicators
        signal = self.generate_signals(bar_index, current_ohlc_bar, indicators)
        
        execution_type = self.params.get("execution_price_type", "close")
        action_price = current_ohlc_bar['open'] if execution_type == "open" else current_ohlc_bar['close']
        
        log_price_type = "OPEN" if execution_type == "open" else "CLOSE"
        if signal: # Only log if there's a non-None signal
            logger.debug(f"Bar {bar_index} ({action_time}): Using {log_price_type} price ({action_price:.2f}) for execution based on signal '{signal}'.")

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
        # ... (remains the same)
        return models.StrategyInfo(
            id=cls.strategy_id, name=cls.strategy_name,
            description=cls.strategy_description, parameters=[]
        )