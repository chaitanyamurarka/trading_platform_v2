# app/strategy_engine.py
import pandas as pd
from typing import Dict, Any, Type, List
from datetime import datetime # Ensure datetime is imported for pd.Timedelta and equity curve timestamps

from .config import logger
from .models import BacktestResult, BacktestRequest, Trade, OHLCDataPoint
from .strategies.base_strategy import BaseStrategy, PortfolioState

def calculate_performance_metrics(portfolio: PortfolioState, initial_capital: float) -> Dict[str, Any]:
    """
    Calculates performance metrics from the portfolio state.
    """
    # Ensure P&L is calculated for all closed trades if not already
    for trade in portfolio.trades:
        if trade.status == "CLOSED" and trade.pnl is None and \
           trade.exit_price is not None and trade.entry_price is not None: # Added entry_price check
            if trade.trade_type == "LONG":
                trade.pnl = round((trade.exit_price - trade.entry_price) * trade.qty, 2)
            elif trade.trade_type == "SHORT":
                trade.pnl = round((trade.entry_price - trade.exit_price) * trade.qty, 2)
    
    final_equity = portfolio.equity_curve[-1]['equity'] if portfolio.equity_curve else initial_capital
    net_pnl = final_equity - initial_capital
    total_trades = len(portfolio.trades)
    
    winning_trades = len([t for t in portfolio.trades if t.pnl is not None and t.pnl > 0])
    losing_trades = len([t for t in portfolio.trades if t.pnl is not None and t.pnl < 0])
    
    max_dd = 0.0
    peak_equity = initial_capital
    if portfolio.equity_curve: # Calculate drawdown if equity curve exists
        for point in portfolio.equity_curve:
            equity = point['equity']
            if equity > peak_equity:
                peak_equity = equity
            drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
            if drawdown > max_dd:
                max_dd = drawdown
    
    return {
        "net_pnl": round(net_pnl, 2),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round((winning_trades / total_trades * 100), 2) if total_trades > 0 else 0.0,
        "loss_rate": round((losing_trades / total_trades * 100), 2) if total_trades > 0 else 0.0,
        "max_drawdown_pct": round(max_dd * 100, 2), # Storing as pct
        "final_equity": round(final_equity, 2)
        # Sharpe Ratio, Sortino, etc., would require more complex calculations (e.g., daily returns).
    }

async def run_single_backtest(
    historical_data_points: List[OHLCDataPoint],
    strategy_class: Type[BaseStrategy],
    strategy_params: Dict[str, Any],
    backtest_request_details: BacktestRequest, # For context in result
    initial_capital: float = 100000.0
) -> BacktestResult:
    strategy_id_for_logging = strategy_class.strategy_id # Get it once

    logger.info(f"Starting single backtest for '{strategy_id_for_logging}' with params: {strategy_params}, Initial Capital: {initial_capital}")

    if not historical_data_points:
        logger.warning(f"No historical data provided for backtest for '{strategy_id_for_logging}'.")
        return BacktestResult(
            request=backtest_request_details, net_pnl=0, total_trades=0, winning_trades=0, 
            losing_trades=0, max_drawdown=0.0, equity_curve=[], trades=[],
            logs=["Error: No historical data provided for backtest."]
        )

    try:
        ohlc_df = pd.DataFrame([item.model_dump() for item in historical_data_points])
        ohlc_df['time'] = pd.to_datetime(ohlc_df['time'])
        ohlc_df = ohlc_df.set_index('time').sort_index()
        if ohlc_df.empty:
             raise ValueError("OHLC DataFrame is empty after conversion.")
    except Exception as e:
        logger.error(f"Error converting historical data to DataFrame for '{strategy_id_for_logging}': {e}", exc_info=True)
        raise ValueError(f"Invalid historical data format: {e}")

    portfolio = PortfolioState(initial_capital=initial_capital)
    if not ohlc_df.empty:
         portfolio.equity_curve.append({
             "time": (ohlc_df.index[0] - pd.Timedelta(minutes=1)).to_pydatetime(), 
             "equity": initial_capital
         })
    
    try:
        # OLD LINE was likely: strategy_instance = strategy_class(data=ohlc_df, params=strategy_params, portfolio=portfolio)
        strategy_instance = strategy_class(shared_ohlc_data=ohlc_df, params=strategy_params, portfolio=portfolio) # <<<< CORRECTED HERE
    except Exception as e:
        logger.error(f"Error initializing strategy '{strategy_id_for_logging}': {e}", exc_info=True)
        return BacktestResult(
            request=backtest_request_details, net_pnl=0, total_trades=0, winning_trades=0, 
            losing_trades=0, max_drawdown=0.0, equity_curve=portfolio.equity_curve, trades=[],
            logs=[f"Error initializing strategy: {e}"]
        )
    
    logger.info(f"Processing {len(ohlc_df)} bars for backtest for strategy '{strategy_id_for_logging}'...")

    for bar_index in range(len(ohlc_df)):
        try:
            strategy_instance.process_bar(bar_index)
        except Exception as e:
            current_bar_name_for_log = strategy_instance.data.index[bar_index] if bar_index < len(strategy_instance.data) else "UNKNOWN_BAR"
            logger.error(f"Error processing bar {bar_index} ({current_bar_name_for_log}) for strategy '{strategy_id_for_logging}': {e}", exc_info=True)
        
        portfolio.record_equity(ohlc_df.index[bar_index], ohlc_df.iloc[bar_index]['close'])

    if portfolio.current_position_qty > 0 and not ohlc_df.empty:
        last_bar_time = ohlc_df.index[-1]
        last_close_price = ohlc_df.iloc[-1]['close']
        logger.info(f"Closing open EOD position for '{strategy_id_for_logging}' at {last_bar_time} price {last_close_price:.2f}")
        portfolio.close_position(last_bar_time, last_close_price)

    performance_summary = calculate_performance_metrics(portfolio, initial_capital)
    logger.info(f"Backtest completed for '{strategy_id_for_logging}'. PnL: {performance_summary.get('net_pnl', 0.0)}")

    return BacktestResult(
        request=backtest_request_details,
        net_pnl=performance_summary.get("net_pnl", 0.0),
        total_trades=performance_summary.get("total_trades", 0),
        winning_trades=performance_summary.get("winning_trades", 0),
        losing_trades=performance_summary.get("losing_trades", 0),
        max_drawdown=performance_summary.get("max_drawdown_pct", 0.0),
        equity_curve=portfolio.equity_curve,
        trades=portfolio.trades
    )