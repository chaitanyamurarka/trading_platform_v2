# app/strategy_engine.py
import pandas as pd
import numpy as np # Add numpy import
from typing import Dict, Any, Type, List, Optional, Tuple, Union
from datetime import datetime, timezone # Ensure datetime and timezone are imported

from .config import logger
from .models import (
    OHLCDataPoint, TradeEntry, EquityDrawdownPoint, 
    BacktestPerformanceMetrics, BacktestResult,
    ChartDataRequest, ChartDataResponse, IndicatorSeries, IndicatorDataPoint, IndicatorConfig, TradeMarker,
    Trade as ModelTrade 
)
from .strategies.base_strategy import BaseStrategy, PortfolioState
from . import models

# --- Import for Numba Path ---
try:
    from .optimizer_engine import run_single_ema_crossover_numba_detailed
    # Import Numba position constants if they are not defined here
    # Assuming they are defined in numba_kernels and we might need to redefine or import
    POSITION_NONE = 0 # Defined in numba_kernels.py
    POSITION_LONG = 1 # Defined in numba_kernels.py
    POSITION_SHORT = -1 # Defined in numba_kernels.py
    NUMBA_PATH_AVAILABLE = True
except ImportError:
    logger.warning(
        "Could not import 'run_single_ema_crossover_numba_detailed' from optimizer_engine. "
        "Numba path for EMA Crossover in strategy_engine will not be available."
    )
    NUMBA_PATH_AVAILABLE = False
    # Define placeholders if import fails, to prevent NameError, though logic will skip Numba path
    def run_single_ema_crossover_numba_detailed(*args, **kwargs):
        raise NotImplementedError("Numba single run function placeholder called due to import error.")
    POSITION_LONG = 1 
    POSITION_SHORT = -1
# --- End Import for Numba Path ---


# --- Function _transform_numba_output_to_backtest_result (as defined in previous step) ---
# Ensure this function is present in this file or correctly imported if moved to a util.
# For brevity, I'll assume it's here as per the previous step.
def _transform_numba_output_to_backtest_result(
    numba_raw_outputs: tuple,
    ohlc_timestamps: pd.DatetimeIndex,
    initial_capital: float,
    strategy_params_used: Dict[str, Any]
) -> models.BacktestResult:
    try:
        (
            final_pnl_arr, total_trades_arr, winning_trades_arr,
            losing_trades_arr, max_drawdown_arr,
            equity_curve_values, fast_ema_series, slow_ema_series,
            trade_entry_indices, trade_exit_indices,
            trade_entry_prices, trade_exit_prices,
            trade_types, trade_pnls,
            actual_trade_count_arr
        ) = numba_raw_outputs
        actual_trade_count = int(actual_trade_count_arr[0])

        net_pnl = float(final_pnl_arr[0])
        net_pnl_pct = (net_pnl / initial_capital) * 100 if initial_capital != 0 else 0
        total_trades = int(total_trades_arr[0])
        winning_trades = int(winning_trades_arr[0])
        losing_trades = int(losing_trades_arr[0])
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
        max_drawdown_pct = float(max_drawdown_arr[0]) * 100

        performance_metrics = models.BacktestPerformanceMetrics(
            net_pnl=round(net_pnl, 2), net_pnl_pct=round(net_pnl_pct, 2),
            total_trades=total_trades, winning_trades=winning_trades, losing_trades=losing_trades,
            win_rate=round(win_rate, 2),
            loss_rate=round(((losing_trades / total_trades) * 100 if total_trades > 0 else 0), 2),
            max_drawdown=round(max_drawdown_pct, 2), max_drawdown_pct=round(max_drawdown_pct, 2)
        )
        trades_list: List[models.TradeEntry] = []
        for i in range(actual_trade_count):
            entry_idx = int(trade_entry_indices[i])
            exit_idx = int(trade_exit_indices[i])
            entry_time_dt = ohlc_timestamps[entry_idx].to_pydatetime()
            exit_time_dt = ohlc_timestamps[exit_idx].to_pydatetime() if exit_idx != -1 and exit_idx < len(ohlc_timestamps) else None
            exit_price_val = float(trade_exit_prices[i]) if not np.isnan(trade_exit_prices[i]) else None
            pnl_val = float(trade_pnls[i]) if not np.isnan(trade_pnls[i]) else None
            trade_type_str = "LONG" if trade_types[i] == POSITION_LONG else "SHORT"
            trades_list.append(models.TradeEntry(
                entry_time=entry_time_dt, exit_time=exit_time_dt, trade_type=trade_type_str,
                quantity=1, entry_price=float(trade_entry_prices[i]),
                exit_price=exit_price_val, pnl=pnl_val
            ))
        equity_curve_points: List[models.EquityDrawdownPoint] = []
        if equity_curve_values.size > 0 and equity_curve_values.size == len(ohlc_timestamps):
            for i_eq in range(len(ohlc_timestamps)):
                equity_curve_points.append(models.EquityDrawdownPoint(
                    time=ohlc_timestamps[i_eq].to_pydatetime(),
                    value=round(float(equity_curve_values[i_eq]), 2)
                ))
        elif equity_curve_values.size > 0:
             logger.warning(f"Numba equity curve size ({equity_curve_values.size}) mismatch with ohlc_timestamps ({len(ohlc_timestamps)}). Skipping equity curve.")
        drawdown_curve_points: List[models.EquityDrawdownPoint] = []
        current_peak_equity = initial_capital
        if equity_curve_points:
            current_peak_equity = equity_curve_points[0].value
            for eq_point in equity_curve_points:
                if eq_point.value > current_peak_equity: current_peak_equity = eq_point.value
                drawdown_val = current_peak_equity - eq_point.value
                drawdown_pct = (drawdown_val / current_peak_equity) * 100 if current_peak_equity > 0 else 0
                drawdown_curve_points.append(models.EquityDrawdownPoint(time=eq_point.time, value=round(drawdown_pct, 2)))
        else:
            if len(ohlc_timestamps) > 0: drawdown_curve_points.append(models.EquityDrawdownPoint(time=ohlc_timestamps[0].to_pydatetime(), value=0))
            else: drawdown_curve_points.append(models.EquityDrawdownPoint(time=datetime.now(timezone.utc), value=0))
        summary_msg = f"Numba Backtest completed. Net PnL: {performance_metrics.net_pnl:.2f}."
        return models.BacktestResult(
            performance_metrics=performance_metrics, trades=trades_list,
            equity_curve=equity_curve_points, drawdown_curve=drawdown_curve_points,
            summary_message=summary_msg
        )
    except Exception as e:
        logger.error(f"Error transforming Numba output: {e}", exc_info=True)
        return models.BacktestResult(error_message=f"Error processing Numba results: {str(e)}")
# --- END OF _transform_numba_output_to_backtest_result ---


# --- perform_backtest_simulation function (as modified in previous step) ---
# Ensure this function is present and correctly uses the Numba path for "ema_crossover"
# and the Python path for others.
async def perform_backtest_simulation(
    historical_data_points: List[models.OHLCDataPoint],
    strategy_class: Type[BaseStrategy],
    strategy_parameters: Dict[str, Any],
    initial_capital: float,
) -> models.BacktestResult:
    if not historical_data_points:
        return models.BacktestResult(error_message="No historical data provided for simulation.")
    try:
        df_data = []
        for p in historical_data_points:
            item_dict = p.model_dump()
            if isinstance(item_dict['time'], int):
                item_dict['time'] = datetime.fromtimestamp(item_dict['time'], tz=timezone.utc)
            df_data.append(item_dict)
        df = pd.DataFrame(df_data)
        if df.empty: return models.BacktestResult(error_message="Historical data is empty after initial conversion.")
        df['time'] = pd.to_datetime(df['time'])
        df = df.set_index('time').sort_index()
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col not in df.columns: df[col] = np.nan
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
        if df.empty: return models.BacktestResult(error_message="Historical data became empty after cleaning (OHLC NaNs).")
    except Exception as e:
        logger.error(f"Error processing historical data for backtest: {e}", exc_info=True)
        return models.BacktestResult(error_message=f"Error processing historical data: {str(e)}")

    if strategy_class.strategy_id == "ema_crossover" and NUMBA_PATH_AVAILABLE:
        logger.info(f"Using NUMBA path for single backtest of EMA Crossover strategy.")
        try:
            execution_price_type = strategy_parameters.get("execution_price_type", "close")
            numba_raw_results = run_single_ema_crossover_numba_detailed(
                historical_data_points=historical_data_points,
                strategy_params=strategy_parameters,
                initial_capital=initial_capital,
                execution_price_type_str=execution_price_type,
                ohlc_data_df_index=df.index 
            )
            backtest_result = _transform_numba_output_to_backtest_result(
                numba_raw_outputs=numba_raw_results, ohlc_timestamps=df.index,
                initial_capital=initial_capital, strategy_params_used=strategy_parameters
            )
            logger.info(f"Numba EMA Crossover backtest completed. Net PnL: {backtest_result.performance_metrics.net_pnl if backtest_result.performance_metrics else 'N/A'}")
            return backtest_result
        except NotImplementedError:
             logger.error("Numba single run function is not implemented/imported for EMA Crossover. Cannot run Numba backtest.")
             return models.BacktestResult(error_message="EMA Crossover requires Numba path, but it's unavailable (Import Error).")
        except Exception as e:
            logger.error(f"Error during NUMBA EMA Crossover backtest: {e}", exc_info=True)
            return models.BacktestResult(error_message=f"Error in Numba EMA Crossover execution: {str(e)}")
    else:
        logger.info(f"Using PYTHON path for single backtest of strategy: {strategy_class.strategy_id}")
        # ... (Your existing Python path logic from PortfolioState init to result formatting) ...
        # This part is copied from your existing working `perform_backtest_simulation` for other strategies
        try:
            portfolio_state = PortfolioState(initial_capital=initial_capital)
            strategy_instance = strategy_class(shared_ohlc_data=df.copy(), params=strategy_parameters, portfolio=portfolio_state)
            if df.empty : return models.BacktestResult(error_message="No data to process for Python backtest.")
            strategy_instance.portfolio.record_equity(df.index[0], df['close'].iloc[0])
            for bar_idx in range(len(df)):
                strategy_instance.process_bar(bar_idx)
                current_bar_timestamp = df.index[bar_idx]; current_bar_close = df['close'].iloc[bar_idx]
                strategy_instance.portfolio.record_equity(current_bar_timestamp, current_bar_close)
            portfolio_trades: List[ModelTrade] = strategy_instance.portfolio.trades
            formatted_trades: List[models.TradeEntry] = []
            for t in portfolio_trades:
                formatted_trades.append(models.TradeEntry(
                    entry_time=t.entry_time, exit_time=t.exit_time, trade_type=t.trade_type,
                    quantity=t.qty, entry_price=t.entry_price, exit_price=t.exit_price, pnl=t.pnl ))
            equity_curve_from_portfolio = strategy_instance.portfolio.equity_curve
            equity_curve_points: List[models.EquityDrawdownPoint] = [ models.EquityDrawdownPoint(time=eq_point["time"], value=eq_point["equity"]) for eq_point in equity_curve_from_portfolio ]
            final_equity_py = equity_curve_points[-1].value if equity_curve_points else initial_capital
            net_pnl_py = final_equity_py - initial_capital
            net_pnl_pct_py = (net_pnl_py / initial_capital) * 100 if initial_capital != 0 else 0
            total_closed_trades_py = len([t for t in formatted_trades if t.exit_time is not None])
            winning_trades_count_py = len([t for t in formatted_trades if t.pnl is not None and t.pnl > 0])
            losing_trades_count_py = len([t for t in formatted_trades if t.pnl is not None and t.pnl < 0])
            win_rate_py = (winning_trades_count_py / total_closed_trades_py) * 100 if total_closed_trades_py > 0 else 0
            drawdown_curve_points_py: List[models.EquityDrawdownPoint] = []
            peak_for_drawdown_py = initial_capital
            if equity_curve_points:
                peak_for_drawdown_py = equity_curve_points[0].value
                for eq_point in equity_curve_points:
                    if eq_point.value > peak_for_drawdown_py: peak_for_drawdown_py = eq_point.value
                    drawdown_value = peak_for_drawdown_py - eq_point.value
                    drawdown_percentage = (drawdown_value / peak_for_drawdown_py) * 100 if peak_for_drawdown_py > 0 else 0
                    drawdown_curve_points_py.append(models.EquityDrawdownPoint(time=eq_point.time, value=drawdown_percentage))
            else:
                 if len(df.index) > 0: drawdown_curve_points_py.append(models.EquityDrawdownPoint(time=df.index[0].to_pydatetime(), value=0))
                 else: drawdown_curve_points_py.append(models.EquityDrawdownPoint(time=datetime.now(timezone.utc), value=0))
            max_drawdown_percentage_py = max(d.value for d in drawdown_curve_points_py) if drawdown_curve_points_py else 0
            performance_metrics_py = models.BacktestPerformanceMetrics(
                net_pnl=round(net_pnl_py, 2), net_pnl_pct=round(net_pnl_pct_py, 2),
                total_trades=total_closed_trades_py, winning_trades=winning_trades_count_py,
                losing_trades=losing_trades_count_py, win_rate=round(win_rate_py, 2),
                loss_rate=round(((losing_trades_count_py / total_closed_trades_py) * 100 if total_closed_trades_py > 0 else 0), 2),
                max_drawdown=round(max_drawdown_percentage_py, 2), max_drawdown_pct=round(max_drawdown_percentage_py, 2) )
            summary_msg_py = f"Python Backtest completed. Net PnL: {performance_metrics_py.net_pnl:.2f}."
            return models.BacktestResult(
                performance_metrics=performance_metrics_py, trades=formatted_trades,
                equity_curve=equity_curve_points, drawdown_curve=drawdown_curve_points_py,
                summary_message=summary_msg_py )
        except Exception as e:
            logger.error(f"Error during PYTHON path backtest for strategy '{strategy_class.strategy_id}': {e}", exc_info=True)
            return models.BacktestResult(error_message=f"Error in Python strategy execution: {str(e)}")

# --- MODIFICATION FOR generate_chart_data ---
async def generate_chart_data(
    chart_request: ChartDataRequest,
    historical_data_points: List[OHLCDataPoint], 
    strategy_class: Optional[Type[BaseStrategy]] = None, 
    token_trading_symbol: str = "N/A" 
) -> ChartDataResponse:
    logger.info(f"Generating chart data for {chart_request.exchange}:{chart_request.token}, Strategy: {chart_request.strategy_id}")

    if not historical_data_points: # Should be List[OHLCDataPoint]
        logger.warning("No historical data for chart generation.")
        return ChartDataResponse(
            ohlc_data=[], indicator_data=[], trade_markers=[],
            chart_header_info=f"{chart_request.exchange}:{token_trading_symbol} ({chart_request.timeframe}) - No Data",
            timeframe_actual=chart_request.timeframe
        )

    chart_ohlc_data_list: List[Dict[str, Union[int, float, None]]] = []
    ohlc_dicts_for_df = []

    for dp_obj in historical_data_points: # dp_obj is OHLCDataPoint
        # Ensure dp_obj.time is datetime
        time_val = dp_obj.time
        if isinstance(dp_obj.time, int): # If it's a timestamp, convert to datetime
            time_val = datetime.fromtimestamp(dp_obj.time, tz=timezone.utc)

        chart_ohlc_data_list.append({
            "time": int(time_val.timestamp()), 
            "open": dp_obj.open, "high": dp_obj.high, "low": dp_obj.low, "close": dp_obj.close, 
            "volume": dp_obj.volume, "oi": dp_obj.oi
        })
        # For DataFrame, keep time as datetime object
        temp_dict = dp_obj.model_dump()
        temp_dict['time'] = time_val 
        ohlc_dicts_for_df.append(temp_dict)
    
    ohlc_df = pd.DataFrame(ohlc_dicts_for_df)
    if not ohlc_df.empty:
        ohlc_df['time'] = pd.to_datetime(ohlc_df['time'])
        ohlc_df = ohlc_df.set_index('time').sort_index()
    else:
        logger.warning("OHLC DataFrame is empty for chart generation.")
        return ChartDataResponse(
            ohlc_data=[], indicator_data=[], trade_markers=[],
            chart_header_info=f"{chart_request.exchange}:{token_trading_symbol} ({chart_request.timeframe}) - Data Error",
            timeframe_actual=chart_request.timeframe
        )

    indicator_series_list: List[IndicatorSeries] = [] 
    trade_markers_list: List[TradeMarker] = [] 
    strategy_name_for_header = "None"
    current_strategy_params = chart_request.strategy_params if chart_request.strategy_params else {}


    if strategy_class and chart_request.strategy_id == "ema_crossover" and NUMBA_PATH_AVAILABLE:
        logger.info(f"Using NUMBA path for chart data (Indicators & Markers) for EMA Crossover strategy.")
        strategy_name_for_header = strategy_class.strategy_name # "EMA Crossover"
        try:
            execution_price_type = current_strategy_params.get("execution_price_type", "close")
            
            numba_raw_outputs = run_single_ema_crossover_numba_detailed(
                historical_data_points=historical_data_points, # Original List[OHLCDataPoint]
                strategy_params=current_strategy_params,
                initial_capital=100000, # Dummy capital, PnL/equity not primary for chart indicators
                execution_price_type_str=execution_price_type,
                ohlc_data_df_index=ohlc_df.index # DatetimeIndex from the ohlc_df
            )
            
            (
                _final_pnl_arr, _total_trades_arr, _winning_trades_arr,
                _losing_trades_arr, _max_drawdown_arr,
                _equity_curve_values, # Not directly used for chart indicators/markers here
                fast_ema_values, slow_ema_values, # EMA series
                trade_entry_indices, trade_exit_indices,
                trade_entry_prices, trade_exit_prices,
                trade_types, _trade_pnls, # PNL not used for markers, but type/price are
                actual_trade_count_arr
            ) = numba_raw_outputs
            
            actual_trade_count = int(actual_trade_count_arr[0])

            # Transform Fast EMA series for chart
            if fast_ema_values.size > 0 and fast_ema_values.size == len(ohlc_df.index):
                fast_ema_points = [
                    IndicatorDataPoint(time=int(ohlc_df.index[i].timestamp()), 
                                       value=round(float(fast_ema_values[i]), 2) if not np.isnan(fast_ema_values[i]) else None)
                    for i in range(len(ohlc_df.index))
                ]
                f_period = current_strategy_params.get("fast_ema_period", strategy_class.get_info().parameters[0].default if strategy_class else "N/A")
                indicator_series_list.append(IndicatorSeries(
                    name=f"Fast EMA ({f_period})", data=fast_ema_points,
                    config=IndicatorConfig(color="rgba(0, 150, 136, 0.8)", lineWidth=2)
                ))

            # Transform Slow EMA series for chart
            if slow_ema_values.size > 0 and slow_ema_values.size == len(ohlc_df.index):
                slow_ema_points = [
                    IndicatorDataPoint(time=int(ohlc_df.index[i].timestamp()), 
                                       value=round(float(slow_ema_values[i]), 2) if not np.isnan(slow_ema_values[i]) else None)
                    for i in range(len(ohlc_df.index))
                ]
                s_period = current_strategy_params.get("slow_ema_period", strategy_class.get_info().parameters[1].default if strategy_class else "N/A")
                indicator_series_list.append(IndicatorSeries(
                    name=f"Slow EMA ({s_period})", data=slow_ema_points,
                    config=IndicatorConfig(color="rgba(255, 82, 82, 0.8)", lineWidth=2)
                ))
            
            # Transform Trades to Markers
            for i_trade in range(actual_trade_count):
                entry_idx = int(trade_entry_indices[i_trade])
                exit_idx = int(trade_exit_indices[i_trade])
                trade_type_int = int(trade_types[i_trade])

                if entry_idx < 0 or entry_idx >= len(ohlc_df.index): continue # Basic bounds check

                entry_time_dt_for_marker = ohlc_df.index[entry_idx].to_pydatetime()
                entry_price_for_marker = float(trade_entry_prices[i_trade])
                trade_type_str_for_marker = "LONG" if trade_type_int == POSITION_LONG else "SHORT"

                trade_markers_list.append(TradeMarker(
                    time=int(entry_time_dt_for_marker.timestamp()),
                    position="belowBar" if trade_type_str_for_marker == "LONG" else "aboveBar",
                    color="green" if trade_type_str_for_marker == "LONG" else "red",
                    shape="arrowUp" if trade_type_str_for_marker == "LONG" else "arrowDown",
                    text=f"{trade_type_str_for_marker} @ {entry_price_for_marker:.2f}"
                ))

                if exit_idx != -1 and exit_idx < len(ohlc_df.index): # Check if trade was closed
                    exit_time_dt_for_marker = ohlc_df.index[exit_idx].to_pydatetime()
                    exit_price_for_marker = float(trade_exit_prices[i_trade]) if not np.isnan(trade_exit_prices[i_trade]) else entry_price_for_marker # Fallback for text

                    trade_markers_list.append(TradeMarker(
                        time=int(exit_time_dt_for_marker.timestamp()),
                        position="aboveBar" if trade_type_str_for_marker == "LONG" else "belowBar",
                        color="orange", 
                        shape="square",
                        text=f"Exit @ {exit_price_for_marker:.2f}"
                    ))
        except NotImplementedError:
            logger.error("Numba chart data generation path is not available due to import error.")
            strategy_name_for_header = f"{strategy_class.strategy_name} (Numba Path Error)"
        except Exception as e:
            logger.error(f"Error during NUMBA EMA Crossover chart data generation: {e}", exc_info=True)
            strategy_name_for_header = f"{strategy_class.strategy_name} (Numba Chart Error)"
            # Optionally, clear indicators and markers if Numba path failed catastrophically
            # indicator_series_list = [] 
            # trade_markers_list = []

    elif strategy_class and chart_request.strategy_id: # Existing Python path for other strategies
        strategy_name_for_header = strategy_class.strategy_name
        temp_portfolio = PortfolioState(initial_capital=100000) 
        current_strategy_params['execution_price_type'] = current_strategy_params.get('execution_price_type', 'close')
        
        typed_params = current_strategy_params.copy()
        if strategy_class:
            strategy_info = strategy_class.get_info()
            for p_info in strategy_info.parameters:
                param_name = p_info.name
                if param_name in typed_params and typed_params[param_name] is not None:
                    try:
                        if p_info.type == 'int': typed_params[param_name] = int(float(typed_params[param_name]))
                        elif p_info.type == 'float': typed_params[param_name] = float(typed_params[param_name])
                    except ValueError: logger.warning(f"Could not type cast param '{param_name}' for Python strategy chart")
        
        try:
            # Ensure ohlc_df is passed, not historical_data_points list
            strategy_instance = strategy_class(shared_ohlc_data=ohlc_df.copy(), params=typed_params, portfolio=temp_portfolio)
            indicator_series_list = strategy_instance.get_indicator_series(ohlc_df.index)

            if hasattr(strategy_instance, 'process_bar'):
                for bar_idx in range(len(ohlc_df)):
                    strategy_instance.process_bar(bar_idx)
                for trade in temp_portfolio.trades:
                    if trade.entry_time:
                        trade_markers_list.append(TradeMarker(
                            time=int(trade.entry_time.timestamp()),
                            position="belowBar" if trade.trade_type == "LONG" else "aboveBar",
                            color="green" if trade.trade_type == "LONG" else "red",
                            shape="arrowUp" if trade.trade_type == "LONG" else "arrowDown",
                            text=f"{trade.trade_type} @ {trade.entry_price:.2f}"
                        ))
                    if trade.exit_time:
                        trade_markers_list.append(TradeMarker(
                            time=int(trade.exit_time.timestamp()),
                            position="aboveBar" if trade.trade_type == "LONG" else "belowBar",
                            color="orange", shape="square",
                            text=f"Exit @ {trade.exit_price:.2f}"
                        ))
        except Exception as e:
            logger.error(f"Error processing Python strategy '{chart_request.strategy_id}' for chart: {e}", exc_info=True)
            strategy_name_for_header = f"{strategy_name_for_header} (Error)"
    
    param_str_parts = []
    # Use current_strategy_params for header consistently
    if current_strategy_params and strategy_class and chart_request.strategy_id == "ema_crossover": # Only for EMA crossover
        f_period_val = current_strategy_params.get('fast_ema_period', strategy_class.get_info().parameters[0].default)
        s_period_val = current_strategy_params.get('slow_ema_period', strategy_class.get_info().parameters[1].default)
        if f_period_val is not None: param_str_parts.append(str(f_period_val))
        if s_period_val is not None: param_str_parts.append(str(s_period_val))
    elif current_strategy_params and strategy_class : # For other python strategies, general param display
         for p_info in strategy_class.get_info().parameters:
             if p_info.name in current_strategy_params:
                 param_str_parts.append(f"{p_info.label or p_info.name}: {current_strategy_params[p_info.name]}")


    param_str = ", ".join(param_str_parts)
    header_strategy_part = f"{strategy_name_for_header} ({param_str})" if param_str and strategy_name_for_header != "None" else strategy_name_for_header
    chart_header = f"{chart_request.exchange.upper()}:{token_trading_symbol} ({chart_request.timeframe}) - {header_strategy_part}"
    
    return ChartDataResponse(
        ohlc_data=chart_ohlc_data_list, # List of Dicts with UTC timestamps
        indicator_data=indicator_series_list, 
        trade_markers=trade_markers_list, 
        chart_header_info=chart_header,
        timeframe_actual=chart_request.timeframe
    )

# --- END OF generate_chart_data MODIFICATION ---