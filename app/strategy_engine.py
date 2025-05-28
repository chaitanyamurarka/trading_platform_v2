# app/strategy_engine.py
import pandas as pd
from typing import Dict, Any, Type, List, Optional, Tuple, Union
from datetime import datetime, date, timezone # Ensure timezone is imported
import time 

from .config import logger
from .models import (
    OHLCDataPoint,
    ChartDataRequest, ChartDataResponse, IndicatorSeries, TradeMarker
)
from .strategies.base_strategy import BaseStrategy, PortfolioState # BaseStrategy.get_indicator_series expects pd.DatetimeIndex


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