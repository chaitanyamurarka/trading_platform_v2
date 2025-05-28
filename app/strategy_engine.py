# app/strategy_engine.py
import pandas as pd
from typing import Dict, Any, Type, List, Optional, Tuple, Union
from datetime import datetime, date, timezone # Ensure timezone is imported
import time 
import numpy as np

from .models import OHLCDataPoint, TradeEntry, EquityDrawdownPoint, BacktestPerformanceMetrics, BacktestResult
from .config import logger
from .models import (
    OHLCDataPoint,
    ChartDataRequest, ChartDataResponse, IndicatorSeries, TradeMarker
)
from .models import ( # Assuming these are defined in app/models.py
    OHLCDataPoint,
    TradeEntry, # This is for the BacktestResult
    EquityDrawdownPoint,
    BacktestPerformanceMetrics,
    BacktestResult,
    Trade as ModelTrade # This is the Trade model used by PortfolioState
)
from .strategies.base_strategy import BaseStrategy, PortfolioState # BaseStrategy.get_indicator_series expects pd.DatetimeIndex
from . import models
# app/strategy_engine.py
# ... (existing imports and _transform_numba_output_to_backtest_result function)

# Import the Numba execution wrapper from optimizer_engine
# We might need to adjust import paths or move the wrapper if circular dependencies arise.
# For now, let's assume it can be imported or we can define it here.
# To avoid circular import for now, let's assume run_single_ema_crossover_numba_detailed is accessible
# or we can move it to a common numba_utils.py if this becomes an issue.
# For this step, let's copy its definition into strategy_engine or a shared util.
# To simplify, for now, let's imagine optimizer_engine is importable or restructure later.
try:
    from .optimizer_engine import run_single_ema_crossover_numba_detailed
except ImportError:
    # Fallback or define a placeholder if direct import is an issue due to structure
    # This indicates a potential need for refactoring where shared Numba execution utilities live.
    logger.warning("Could not import run_single_ema_crossover_numba_detailed from optimizer_engine. Numba path for single backtest might not work.")
    def run_single_ema_crossover_numba_detailed(*args, **kwargs): # Placeholder
        raise NotImplementedError("Numba single run function not available.")


async def perform_backtest_simulation(
    historical_data_points: List[models.OHLCDataPoint],
    strategy_class: Type[BaseStrategy],
    strategy_parameters: Dict[str, Any],
    initial_capital: float,
) -> models.BacktestResult:
    
    if not historical_data_points:
        return models.BacktestResult(error_message="No historical data provided for simulation.")

    # --- Prepare DataFrame (common for both paths) ---
    try:
        # Using model_dump for pydantic v2, or .dict() for v1
        df_data = []
        for p in historical_data_points:
            item_dict = p.model_dump()
            # Ensure time is datetime, convert if it's int timestamp
            if isinstance(item_dict['time'], int):
                item_dict['time'] = datetime.fromtimestamp(item_dict['time'], tz=timezone.utc)
            df_data.append(item_dict)

        df = pd.DataFrame(df_data)
        if df.empty:
             return models.BacktestResult(error_message="Historical data is empty after initial conversion.")
        df['time'] = pd.to_datetime(df['time'])
        df = df.set_index('time').sort_index() # Ensure sort by time
        
        for col in ['open', 'high', 'low', 'close', 'volume']: # Ensure essential columns exist
            if col not in df.columns:
                 df[col] = np.nan # Add missing columns as NaN to avoid KeyError later
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Drop rows where essential OHLC are NaN after conversion
        df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
        if df.empty:
            return models.BacktestResult(error_message="Historical data became empty after cleaning (OHLC NaNs).")
    except Exception as e:
        logger.error(f"Error processing historical data for backtest: {e}", exc_info=True)
        return models.BacktestResult(error_message=f"Error processing historical data: {str(e)}")

    # --- MODIFIED SECTION: Dispatch to Numba or Python ---
    if strategy_class.strategy_id == "ema_crossover":
        logger.info(f"Using NUMBA path for single backtest of EMA Crossover strategy.")
        try:
            # execution_price_type should be part of strategy_parameters
            # BaseStrategy default for execution_price_type is 'close'
            execution_price_type = strategy_parameters.get("execution_price_type", "close")

            # Pass the original historical_data_points list, the wrapper will make a DF from it.
            # Pass df.index for timestamp mapping.
            numba_raw_results = run_single_ema_crossover_numba_detailed(
                historical_data_points=historical_data_points, # Pass the original list
                strategy_params=strategy_parameters,
                initial_capital=initial_capital,
                execution_price_type_str=execution_price_type,
                ohlc_data_df_index=df.index # Pass the DatetimeIndex from the processed df
            )
            
            # Transform Numba output to BacktestResult
            # Pass the DatetimeIndex of the df used by Numba for accurate timestamp mapping
            backtest_result = _transform_numba_output_to_backtest_result(
                numba_raw_outputs=numba_raw_results,
                ohlc_timestamps=df.index, 
                initial_capital=initial_capital,
                strategy_params_used=strategy_parameters
            )
            logger.info(f"Numba EMA Crossover backtest completed. Net PnL: {backtest_result.performance_metrics.net_pnl if backtest_result.performance_metrics else 'N/A'}")
            return backtest_result
            
        except NotImplementedError: # If run_single_ema_crossover_numba_detailed was not imported
             logger.error("Numba single run function is not implemented/imported. Falling back to Python path if available, or erroring.")
             # Decide: either error out, or fall back to Python path (which would mean no consistency)
             # Forcing Numba for consistency if strategy_id is ema_crossover:
             return models.BacktestResult(error_message="EMA Crossover requires Numba path, but it's unavailable.")
        except Exception as e:
            logger.error(f"Error during NUMBA EMA Crossover backtest: {e}", exc_info=True)
            return models.BacktestResult(error_message=f"Error in Numba EMA Crossover execution: {str(e)}")
    else:
        # --- Existing Python-based strategy execution path ---
        logger.info(f"Using PYTHON path for single backtest of strategy: {strategy_class.strategy_id}")
        # ... (the rest of your existing Python backtesting logic starting from PortfolioState init)
        # Ensure this part uses the `df` created at the beginning of this function.
        try:
            portfolio_state = PortfolioState(initial_capital=initial_capital)
        except Exception as e: # Should not happen if initial_capital is float
            logger.error(f"Error initializing PortfolioState for Python backtest: {e}", exc_info=True)
            return models.BacktestResult(error_message=f"Error initializing portfolio state: {str(e)}")

        try:
            strategy_instance = strategy_class(
                shared_ohlc_data=df.copy(), # Pass the cleaned and indexed df
                params=strategy_parameters,
                portfolio=portfolio_state
            )
        except Exception as e:
            logger.error(f"Error initializing strategy '{strategy_class.get_info().name}' for Python backtest: {e}", exc_info=True)
            return models.BacktestResult(error_message=f"Error initializing strategy '{strategy_class.get_info().name}': {str(e)}")

        if df.empty : # Should have been caught earlier
             return models.BacktestResult(error_message="No data to process for Python backtest.")
        try:
            strategy_instance.portfolio.record_equity(df.index[0], df['close'].iloc[0])
        except IndexError:
            logger.error("Python backtest: DataFrame is empty, cannot record initial equity.")
            return models.BacktestResult(error_message="Cannot record initial equity for Python backtest, data empty.")

        for bar_idx in range(len(df)):
            try:
                strategy_instance.process_bar(bar_idx)
                current_bar_timestamp = df.index[bar_idx]
                current_bar_close = df['close'].iloc[bar_idx]
                strategy_instance.portfolio.record_equity(current_bar_timestamp, current_bar_close)
            except Exception as e:
                logger.error(f"Error during Python simulation at bar {bar_idx} ({df.index[bar_idx]}): {e}", exc_info=True)
                return models.BacktestResult(error_message=f"Error during Python simulation at bar {bar_idx} ({df.index[bar_idx]}): {str(e)}")
        
        # --- Extract and Format Results for Python Path (existing logic) ---
        # (This part of your function remains the same, make sure it uses the correct df and portfolio_state)
        portfolio_trades: List[ModelTrade] = strategy_instance.portfolio.trades
        formatted_trades: List[models.TradeEntry] = []
        for t in portfolio_trades:
            formatted_trades.append(models.TradeEntry(
                entry_time=t.entry_time, exit_time=t.exit_time, trade_type=t.trade_type,
                quantity=t.qty, entry_price=t.entry_price, exit_price=t.exit_price, pnl=t.pnl
            ))

        equity_curve_from_portfolio = strategy_instance.portfolio.equity_curve
        equity_curve_points: List[models.EquityDrawdownPoint] = [
            models.EquityDrawdownPoint(time=eq_point["time"], value=eq_point["equity"])
            for eq_point in equity_curve_from_portfolio
        ]
        # ... (rest of your existing Python path result formatting and metric calculation) ...
        # Ensure it culminates in returning a models.BacktestResult
        final_equity_py = equity_curve_points[-1].value if equity_curve_points else initial_capital
        net_pnl_py = final_equity_py - initial_capital
        net_pnl_pct_py = (net_pnl_py / initial_capital) * 100 if initial_capital != 0 else 0
        total_closed_trades_py = len([t for t in formatted_trades if t.exit_time is not None])
        winning_trades_count_py = len([t for t in formatted_trades if t.pnl is not None and t.pnl > 0])
        losing_trades_count_py = len([t for t in formatted_trades if t.pnl is not None and t.pnl < 0])
        win_rate_py = (winning_trades_count_py / total_closed_trades_py) * 100 if total_closed_trades_py > 0 else 0
        
        drawdown_curve_points_py: List[models.EquityDrawdownPoint] = [] # Recalculate for Python path
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
            max_drawdown=round(max_drawdown_percentage_py, 2), 
            max_drawdown_pct=round(max_drawdown_percentage_py, 2)
        )
        summary_msg_py = f"Python Backtest completed. Net PnL: {performance_metrics_py.net_pnl:.2f} ({performance_metrics_py.net_pnl_pct:.2f}%). Trades: {performance_metrics_py.total_trades}."
        
        return models.BacktestResult(
            performance_metrics=performance_metrics_py,
            trades=formatted_trades,
            equity_curve=equity_curve_points,
            drawdown_curve=drawdown_curve_points_py,
            summary_message=summary_msg_py
        )

# Ensure POSITION_LONG and POSITION_SHORT are defined if not imported from numba_kernels,
# or pass string types from Numba and handle them. For _transform_numba_output_to_backtest_result:
POSITION_LONG = 1 # From numba_kernels
POSITION_SHORT = -1 # From numba_kernels
# --- END OF perform_backtest_simulation MODIFICATION ---

def calculate_performance_metrics(
    portfolio: PortfolioState,
    initial_capital: float,
    ohlc_df_for_equity_index: Optional[pd.DataFrame] = None 
) -> Dict[str, Any]:
    for trade in portfolio.trades:
        if trade.status == "CLOSED" and trade.pnl is None and \
           trade.exit_price is not None and trade.entry_price is not None:
            if trade.trade_type == "LONG":
                trade.pnl = round((trade.exit_price - trade.entry_price) * trade.qty, 2)
            elif trade.trade_type == "SHORT":
                trade.pnl = round((trade.entry_price - trade.exit_price) * trade.qty, 2)

    final_equity_value = portfolio.equity_curve[-1]['equity'] if portfolio.equity_curve else initial_capital
    net_pnl = final_equity_value - initial_capital
    total_trades = len(portfolio.trades)

    winning_trades_list = [t for t in portfolio.trades if t.pnl is not None and t.pnl > 0]
    losing_trades_list = [t for t in portfolio.trades if t.pnl is not None and t.pnl < 0]
    winning_trades = len(winning_trades_list)
    losing_trades = len(losing_trades_list)

    drawdown_curve_points = []
    max_dd_pct = 0.0
    peak_equity = initial_capital
    equity_points_for_dd = portfolio.equity_curve 

    if not equity_points_for_dd and ohlc_df_for_equity_index is not None and not ohlc_df_for_equity_index.empty:
        logger.warning("Portfolio equity curve empty during metric calculation, attempting fallback if ohlc_df provided.")
        equity_points_for_dd = [{"time": ohlc_df_for_equity_index.index[0].to_pydatetime(), "equity": initial_capital}]


    for point in equity_points_for_dd:
        current_equity = point['equity']
        dt_timestamp_utc: datetime = point['time'] # Expected to be UTC-aware datetime

        if current_equity > peak_equity:
            peak_equity = current_equity
        
        drawdown_value = peak_equity - current_equity
        current_drawdown_pct = (drawdown_value / peak_equity * 100) if peak_equity > 0 else 0.0
        
        if current_drawdown_pct > max_dd_pct:
            max_dd_pct = current_drawdown_pct
        
        time_val_for_curve = int(dt_timestamp_utc.timestamp()) # UTC timestamp

        drawdown_curve_points.append({
            "time": time_val_for_curve, 
            "value": round(current_drawdown_pct, 2)
        })
    
    equity_curve_for_response = []
    for point in portfolio.equity_curve:
        dt_obj_utc = point['time'] 
        equity_curve_for_response.append({
            "time": int(dt_obj_utc.timestamp()), 
            "equity": point['equity']
        })

    return {
        "net_pnl": round(net_pnl, 2),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round((winning_trades / total_trades * 100), 2) if total_trades > 0 else 0.0,
        "max_drawdown_pct": round(max_dd_pct, 2),
        "final_equity": round(final_equity_value, 2),
        "equity_curve": equity_curve_for_response, 
        "drawdown_curve": drawdown_curve_points
    }

async def generate_chart_data(
    chart_request: ChartDataRequest,
    historical_data_points: List[OHLCDataPoint], 
    strategy_class: Optional[Type[BaseStrategy]] = None, 
    token_trading_symbol: str = "N/A" 
) -> ChartDataResponse:
    logger.info(f"Generating chart data for {chart_request.exchange}:{chart_request.token}, Strategy: {chart_request.strategy_id}")

    if not historical_data_points:
        logger.warning("No historical data for chart generation.")
        return ChartDataResponse(
            ohlc_data=[], indicator_data=[], trade_markers=[],
            chart_header_info=f"{chart_request.exchange}:{token_trading_symbol} ({chart_request.timeframe}) - No Data",
            timeframe_actual=chart_request.timeframe
        )

    # chart_ohlc_data will be List[Dict] where time is UTC timestamp
    # OHLCDataPoint model has time: datetime. The response model for ChartDataResponse
    # should specify if ohlc_data items have time as int (timestamp) or string (ISO).
    # For consistency with indicators and markers, let's make it a list of dicts with int timestamps.
    chart_ohlc_data_list: List[Dict[str, Union[int, float, None]]] = []
    ohlc_dicts_for_df = []

    for dp in historical_data_points: # dp.time is UTC-aware datetime
        dt_time_utc = dp.time 
        
        chart_ohlc_data_list.append({
            "time": int(dt_time_utc.timestamp()), # UTC timestamp
            "open": dp.open, "high": dp.high, "low": dp.low, "close": dp.close, 
            "volume": dp.volume, "oi": dp.oi
        })

        ohlc_dict = dp.model_dump() 
        ohlc_dict['time'] = dt_time_utc 
        ohlc_dicts_for_df.append(ohlc_dict)

    ohlc_df = pd.DataFrame(ohlc_dicts_for_df)
    if not ohlc_df.empty:
        ohlc_df['time'] = pd.to_datetime(ohlc_df['time']) 
        ohlc_df = ohlc_df.set_index('time').sort_index()
    else:
        logger.warning("OHLC DataFrame is empty for chart generation.")
        return ChartDataResponse(
            ohlc_data=[], indicator_data=[], trade_markers=[], # Use empty list for ohlc_data
            chart_header_info=f"{chart_request.exchange}:{token_trading_symbol} ({chart_request.timeframe}) - Data Error",
            timeframe_actual=chart_request.timeframe
        )

    indicator_series_list: List[IndicatorSeries] = [] 
    trade_markers_list: List[TradeMarker] = [] 
    strategy_name_for_header = "None"

    if strategy_class and chart_request.strategy_id:
        strategy_name_for_header = strategy_class.strategy_name
        temp_portfolio = PortfolioState(initial_capital=100000)
        current_strategy_params = chart_request.strategy_params if chart_request.strategy_params else {}
        current_strategy_params['execution_price_type'] = current_strategy_params.get('execution_price_type', 'close')
        
        typed_params = current_strategy_params.copy()
        if strategy_class: # Check added
            strategy_info = strategy_class.get_info()
            for p_info in strategy_info.parameters:
                param_name = p_info.name
                if param_name in typed_params and typed_params[param_name] is not None:
                    try:
                        if p_info.type == 'int':
                            typed_params[param_name] = int(float(typed_params[param_name]))
                        elif p_info.type == 'float':
                            typed_params[param_name] = float(typed_params[param_name])
                    except ValueError:
                        logger.warning(f"Could not correctly type cast param '{param_name}' with value '{typed_params[param_name]}' to type '{p_info.type}'")
        
        try:
            strategy_instance = strategy_class(shared_ohlc_data=ohlc_df, params=typed_params, portfolio=temp_portfolio)
            logger.info(f"Initialized strategy {chart_request.strategy_id} with params: {typed_params} for chart generation.")
        except Exception as e:
            logger.error(f"Error initializing strategy {chart_request.strategy_id} for chart: {e}", exc_info=True)
            strategy_name_for_header = f"{strategy_class.strategy_name} (Error)"
        else:
            for bar_idx in range(len(ohlc_df)):
                strategy_instance.process_bar(bar_idx) 

            # *** CORRECTED LINE BELOW ***
            # Pass ohlc_df.index (which is a pd.DatetimeIndex) directly
            # The strategy's get_indicator_series should handle pd.DatetimeIndex
            # and its IndicatorDataPoint.time should be UTC epoch int timestamp.
            indicator_series_list = strategy_instance.get_indicator_series(ohlc_df.index)

            for trade in temp_portfolio.trades:
                if trade.entry_time: # trade.entry_time is UTC-aware datetime
                    trade_markers_list.append(TradeMarker(
                        time=int(trade.entry_time.timestamp()), # UTC timestamp
                        position="belowBar" if trade.trade_type == "LONG" else "aboveBar",
                        color="green" if trade.trade_type == "LONG" else "red",
                        shape="arrowUp" if trade.trade_type == "LONG" else "arrowDown",
                        text=f"{trade.trade_type} Entry"
                    ))
                if trade.exit_time: # trade.exit_time is UTC-aware datetime
                    trade_markers_list.append(TradeMarker(
                        time=int(trade.exit_time.timestamp()), # UTC timestamp
                        position="aboveBar" if trade.trade_type == "LONG" else "belowBar",
                        color="orange",
                        shape="square",
                        text=f"{trade.trade_type} Exit"
                    ))
    
    param_str_parts = []
    if chart_request.strategy_params:
        fml = chart_request.strategy_params.get('fast_ma_length', chart_request.strategy_params.get('fast_ema_period'))
        sml = chart_request.strategy_params.get('slow_ma_length', chart_request.strategy_params.get('slow_ema_period'))
        if fml is not None: param_str_parts.append(str(fml))
        if sml is not None: param_str_parts.append(str(sml))
    param_str = ",".join(param_str_parts)
    header_strategy_part = f"{strategy_name_for_header} ({param_str})" if param_str else strategy_name_for_header
    chart_header = f"{chart_request.exchange.upper()}:{token_trading_symbol} ({chart_request.timeframe}) - {header_strategy_part}"
    
    return ChartDataResponse(
        ohlc_data=chart_ohlc_data_list, # List of Dicts with UTC timestamps
        indicator_data=indicator_series_list, 
        trade_markers=trade_markers_list, 
        chart_header_info=chart_header,
        timeframe_actual=chart_request.timeframe
    )

# --- NEW FUNCTION: Transform Numba output to BacktestResult ---
def _transform_numba_output_to_backtest_result(
    numba_raw_outputs: tuple,
    ohlc_timestamps: pd.DatetimeIndex, # Timestamps for mapping bar indices
    initial_capital: float,
    strategy_params_used: Dict[str, Any] # For logging/reference
) -> models.BacktestResult:
    """
    Transforms the raw output arrays from a single Numba backtest run
    into a models.BacktestResult object.
    """
    try:
        # Unpack the 15-element tuple from Numba
        (
            final_pnl_arr, total_trades_arr, winning_trades_arr,
            losing_trades_arr, max_drawdown_arr,
            equity_curve_values, fast_ema_series, slow_ema_series,
            trade_entry_indices, trade_exit_indices,
            trade_entry_prices, trade_exit_prices,
            trade_types, trade_pnls,
            actual_trade_count_arr # This is an array with one element: the count
        ) = numba_raw_outputs

        actual_trade_count = int(actual_trade_count_arr[0])

        # --- Performance Metrics ---
        net_pnl = float(final_pnl_arr[0]) # Result for the first (and only) combination
        net_pnl_pct = (net_pnl / initial_capital) * 100 if initial_capital != 0 else 0
        total_trades = int(total_trades_arr[0])
        winning_trades = int(winning_trades_arr[0])
        losing_trades = int(losing_trades_arr[0])
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
        max_drawdown_pct = float(max_drawdown_arr[0]) * 100 # Numba returns decimal

        performance_metrics = models.BacktestPerformanceMetrics(
            net_pnl=round(net_pnl, 2),
            net_pnl_pct=round(net_pnl_pct, 2),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=round(win_rate, 2),
            loss_rate=round(((losing_trades / total_trades) * 100 if total_trades > 0 else 0), 2),
            max_drawdown=round(max_drawdown_pct, 2), # Storing as percentage
            max_drawdown_pct=round(max_drawdown_pct, 2),
            # Add other metrics if Numba kernel is enhanced further
        )

        # --- Trades List ---
        trades_list: List[models.TradeEntry] = []
        for i in range(actual_trade_count):
            entry_idx = int(trade_entry_indices[i])
            exit_idx = int(trade_exit_indices[i])

            entry_time_dt = ohlc_timestamps[entry_idx].to_pydatetime()
            # Numba uses -1 for not exited yet, or np.nan for price/pnl if still open
            # We ensured open trades at end are "closed" against last bar in Numba for PNL calc
            exit_time_dt = ohlc_timestamps[exit_idx].to_pydatetime() if exit_idx != -1 and exit_idx < len(ohlc_timestamps) else None
            
            exit_price_val = float(trade_exit_prices[i]) if not np.isnan(trade_exit_prices[i]) else None
            pnl_val = float(trade_pnls[i]) if not np.isnan(trade_pnls[i]) else None
            
            trade_type_str = "LONG" if trade_types[i] == POSITION_LONG else "SHORT" # POSITION_LONG/SHORT are from numba_kernels

            trades_list.append(models.TradeEntry(
                entry_time=entry_time_dt,
                exit_time=exit_time_dt,
                trade_type=trade_type_str, # This needs to match TradeEntry model ("LONG", "SHORT")
                quantity=1, # Assuming quantity is 1 for now, Numba kernel uses this implicitly
                entry_price=float(trade_entry_prices[i]),
                exit_price=exit_price_val,
                pnl=pnl_val
            ))
            
        # --- Equity Curve ---
        equity_curve_points: List[models.EquityDrawdownPoint] = []
        if equity_curve_values.size > 0 and equity_curve_values.size == len(ohlc_timestamps):
            for i in range(len(ohlc_timestamps)):
                equity_curve_points.append(models.EquityDrawdownPoint(
                    time=ohlc_timestamps[i].to_pydatetime(),
                    value=round(float(equity_curve_values[i]), 2)
                ))
        elif equity_curve_values.size > 0 : # Mismatch in size, log warning
             logger.warning(f"Numba equity curve size ({equity_curve_values.size}) mismatch with ohlc_timestamps ({len(ohlc_timestamps)}). Skipping equity curve.")


        # --- Drawdown Curve (calculated from equity curve) ---
        drawdown_curve_points: List[models.EquityDrawdownPoint] = []
        current_peak_equity = initial_capital
        if equity_curve_points:
            current_peak_equity = equity_curve_points[0].value
            for eq_point in equity_curve_points:
                if eq_point.value > current_peak_equity:
                    current_peak_equity = eq_point.value
                drawdown_val = current_peak_equity - eq_point.value
                drawdown_pct = (drawdown_val / current_peak_equity) * 100 if current_peak_equity > 0 else 0
                drawdown_curve_points.append(models.EquityDrawdownPoint(
                    time=eq_point.time,
                    value=round(drawdown_pct, 2)
                ))
        else: # Handle case where equity curve might be empty
            if len(ohlc_timestamps) > 0: # Add a single point if we have timestamps
                 drawdown_curve_points.append(models.EquityDrawdownPoint(time=ohlc_timestamps[0].to_pydatetime(), value=0))
            else: # Truly no data
                 drawdown_curve_points.append(models.EquityDrawdownPoint(time=datetime.now(timezone.utc), value=0))


        summary_msg = f"Numba Backtest completed. Net PnL: {performance_metrics.net_pnl:.2f} ({performance_metrics.net_pnl_pct:.2f}%). Trades: {performance_metrics.total_trades}."

        return models.BacktestResult(
            performance_metrics=performance_metrics,
            trades=trades_list,
            equity_curve=equity_curve_points,
            drawdown_curve=drawdown_curve_points,
            summary_message=summary_msg
        )
    except Exception as e:
        logger.error(f"Error transforming Numba output: {e}", exc_info=True)
        return models.BacktestResult(error_message=f"Error processing Numba results: {str(e)}")
