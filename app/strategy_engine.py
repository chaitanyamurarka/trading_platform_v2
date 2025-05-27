# app/strategy_engine.py
import pandas as pd
from typing import Dict, Any, Type, List, Optional, Tuple # Added Optional, Tuple
from datetime import datetime, date # Ensure datetime and date are imported
import time # For chart header

from .config import logger
from .models import (
    BacktestResult, BacktestRequest, Trade, OHLCDataPoint,
    ChartDataRequest, ChartDataResponse, IndicatorSeries, TradeMarker, IndicatorDataPoint
)
from .strategies.base_strategy import BaseStrategy, PortfolioState
# Import STRATEGY_REGISTRY and data_module if they are needed here for chart data generation
# from .main import STRATEGY_REGISTRY # Careful with circular imports
# from . import data_module # Careful with circular imports


def calculate_performance_metrics(
    portfolio: PortfolioState,
    initial_capital: float,
    ohlc_df_for_equity_index: Optional[pd.DataFrame] = None # Used for drawdown calc
) -> Dict[str, Any]:
    """
    Calculates performance metrics from the portfolio state.
    Equity curve in portfolio is based on actual trade times.
    Drawdown curve needs to align with ohlc_df_for_equity_index if provided, or portfolio equity curve.
    """
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

    # Drawdown Calculation
    drawdown_curve_points = []
    max_dd_pct = 0.0
    peak_equity = initial_capital

    # Use portfolio's equity curve for drawdown calculation
    # This curve is recorded at each bar's close or on trade action.
    equity_points_for_dd = portfolio.equity_curve
    if not equity_points_for_dd and ohlc_df_for_equity_index is not None and not ohlc_df_for_equity_index.empty:
        # Fallback if portfolio.equity_curve wasn't populated, but this shouldn't happen if record_equity is called.
        # Construct a simple equity curve based on ohlc data if needed as a last resort.
        logger.warning("Portfolio equity curve empty during metric calculation, attempting fallback if ohlc_df provided.")
        # This part would be complex; ideally portfolio.equity_curve is always populated.
        # For now, we rely on portfolio.equity_curve.
        equity_points_for_dd = [{"time": ohlc_df_for_equity_index.index[0].to_pydatetime(), "equity": initial_capital}]


    for point in equity_points_for_dd:
        current_equity = point['equity']
        dt_timestamp = point['time'] # This should be datetime object

        if current_equity > peak_equity:
            peak_equity = current_equity
        
        drawdown_value = peak_equity - current_equity
        current_drawdown_pct = (drawdown_value / peak_equity * 100) if peak_equity > 0 else 0.0
        
        if current_drawdown_pct > max_dd_pct:
            max_dd_pct = current_drawdown_pct
        
        # Ensure dt_timestamp is a datetime object before calling timestamp()
        time_val_for_curve = int(dt_timestamp.timestamp()) if isinstance(dt_timestamp, datetime) else int(pd.Timestamp(dt_timestamp).timestamp())

        drawdown_curve_points.append({
            "time": time_val_for_curve, # UNIX timestamp
            "value": round(current_drawdown_pct, 2)
        })


    return {
        "net_pnl": round(net_pnl, 2),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round((winning_trades / total_trades * 100), 2) if total_trades > 0 else 0.0,
        "max_drawdown_pct": round(max_dd_pct, 2), # Max drawdown percentage
        "final_equity": round(final_equity_value, 2),
        "equity_curve": portfolio.equity_curve, # Already [{time:datetime, equity:float}]
        "drawdown_curve": drawdown_curve_points # New [{time:int_timestamp, value:float_percentage}]
    }

async def run_single_backtest(
    historical_data_points: List[OHLCDataPoint],
    strategy_class: Type[BaseStrategy],
    strategy_params: Dict[str, Any],
    backtest_request_details: BacktestRequest,
    initial_capital: float = 100000.0
) -> BacktestResult:
    strategy_id_for_logging = strategy_class.strategy_id
    logger.info(f"Starting single backtest for '{strategy_id_for_logging}' with params: {strategy_params}, Capital: {initial_capital}")

    if not historical_data_points:
        logger.warning(f"No historical data for backtest '{strategy_id_for_logging}'.")
        return BacktestResult(
            request=backtest_request_details, net_pnl=0, total_trades=0, winning_trades=0,
            losing_trades=0, max_drawdown=0.0, equity_curve=[], trades=[],
            drawdown_curve=[], logs=["Error: No historical data provided."]
        )

    try:
        # Ensure time is datetime object for pd.DataFrame
        ohlc_dicts = []
        for item in historical_data_points:
            item_dict = item.model_dump()
            if isinstance(item.time, int): # Convert timestamp to datetime if necessary
                item_dict['time'] = datetime.fromtimestamp(item.time)
            ohlc_dicts.append(item_dict)

        ohlc_df = pd.DataFrame(ohlc_dicts)
        ohlc_df['time'] = pd.to_datetime(ohlc_df['time'])
        ohlc_df = ohlc_df.set_index('time').sort_index()
        if ohlc_df.empty:
            raise ValueError("OHLC DataFrame is empty after conversion.")
    except Exception as e:
        logger.error(f"Error converting data for '{strategy_id_for_logging}': {e}", exc_info=True)
        raise ValueError(f"Invalid historical data format: {e}")

    portfolio = PortfolioState(initial_capital=initial_capital)
    # Initial equity point
    if not ohlc_df.empty:
        portfolio.equity_curve.append({
            "time": (ohlc_df.index[0] - pd.Timedelta(minutes=1)).to_pydatetime(), # Before first bar
            "equity": initial_capital
        })
    else: # Handle case of empty ohlc_df for portfolio initialization
        portfolio.equity_curve.append({
             "time": datetime.now() - pd.Timedelta(minutes=1), # Placeholder time
             "equity": initial_capital
        })


    try:
        # Ensure all necessary params for strategy are present, with defaults from get_info if not in strategy_params
        strategy_info = strategy_class.get_info()
        default_params_from_info = {p.name: p.default for p in strategy_info.parameters}
        # Merge runtime params, giving them precedence
        final_strategy_params = {**default_params_from_info, **strategy_params}
        final_strategy_params['execution_price_type'] = backtest_request_details.execution_price_type # Pass execution type

        strategy_instance = strategy_class(shared_ohlc_data=ohlc_df, params=final_strategy_params, portfolio=portfolio)
    except Exception as e:
        logger.error(f"Error initializing strategy '{strategy_id_for_logging}': {e}", exc_info=True)
        # Populate with what we have
        metrics = calculate_performance_metrics(portfolio, initial_capital, ohlc_df)
        return BacktestResult(
            request=backtest_request_details,
            net_pnl=metrics.get("net_pnl", 0.0), total_trades=metrics.get("total_trades", 0),
            winning_trades=metrics.get("winning_trades", 0), losing_trades=metrics.get("losing_trades", 0),
            max_drawdown=metrics.get("max_drawdown_pct", 0.0),
            equity_curve=metrics.get("equity_curve", []),
            drawdown_curve=metrics.get("drawdown_curve", []),
            trades=portfolio.trades, logs=[f"Error initializing strategy: {e}"]
        )

    # logger.info(f"Processing {len(ohlc_df)} bars for backtest for strategy '{strategy_id_for_logging}'...")
    for bar_index in range(len(ohlc_df)):
        strategy_instance.process_bar(bar_index)
        # Record equity after each bar based on its close price.
        # SL/TP might close position mid-bar, process_bar handles that.
        # Portfolio.record_equity should be called to reflect the equity at the bar's close.
        # If a trade was closed by SL/TP, cash would have changed.
        # If position is still open, its value changes with market price.
        current_close_price = ohlc_df.iloc[bar_index]['close']
        portfolio.record_equity(ohlc_df.index[bar_index], current_close_price)


    if portfolio.current_position_qty > 0 and not ohlc_df.empty:
        last_bar_time = ohlc_df.index[-1]
        last_close_price = ohlc_df.iloc[-1]['close']
        # logger.info(f"Closing EOD position for '{strategy_id_for_logging}' at {last_bar_time} price {last_close_price:.2f}")
        portfolio.close_position(last_bar_time, last_close_price)
        portfolio.record_equity(last_bar_time, last_close_price) # Record final equity after closing EOD

    performance_summary = calculate_performance_metrics(portfolio, initial_capital, ohlc_df)
    logger.info(f"Backtest for '{strategy_id_for_logging}' done. PnL: {performance_summary.get('net_pnl', 0.0)}")

    # Convert datetime in equity curve to UNIX timestamps for JSON if needed by model, but model expects datetime
    # For BacktestResult, model equity_curve is List[Dict[str, Any]] which implies datetime object is fine.
    # Drawdown curve from calculate_performance_metrics already has time as UNIX timestamp.

    return BacktestResult(
        request=backtest_request_details,
        net_pnl=performance_summary.get("net_pnl", 0.0),
        total_trades=performance_summary.get("total_trades", 0),
        winning_trades=performance_summary.get("winning_trades", 0),
        losing_trades=performance_summary.get("losing_trades", 0),
        max_drawdown=performance_summary.get("max_drawdown_pct", 0.0),
        equity_curve=performance_summary.get("equity_curve", []),
        drawdown_curve=performance_summary.get("drawdown_curve", []),
        trades=portfolio.trades,
        logs=None # Add logs if any captured
    )


async def generate_chart_data(
    chart_request: ChartDataRequest,
    historical_data_points: List[OHLCDataPoint], # Raw from data_module
    strategy_class: Optional[Type[BaseStrategy]] = None, # From STRATEGY_REGISTRY
    token_trading_symbol: str = "N/A" # For header
) -> ChartDataResponse:
    logger.info(f"Generating chart data for {chart_request.exchange}:{chart_request.token}, Strategy: {chart_request.strategy_id}")

    if not historical_data_points:
        logger.warning("No historical data for chart generation.")
        return ChartDataResponse(
            ohlc_data=[], indicator_data=[], trade_markers=[],
            chart_header_info=f"{chart_request.exchange}:{token_trading_symbol} ({chart_request.timeframe}) - No Data",
            timeframe_actual=chart_request.timeframe
        )

    # 1. Prepare OHLC data (ensure time is UNIX timestamp for response)
    chart_ohlc_data: List[OHLCDataPoint] = []
    ohlc_dicts_for_df = []
    for dp in historical_data_points:
        dt_time = dp.time
        if isinstance(dp.time, int): # if already a timestamp
            dt_time = datetime.fromtimestamp(dp.time)
        
        chart_ohlc_data.append(OHLCDataPoint(
            time=int(dt_time.timestamp()), # Convert to UNIX timestamp
            open=dp.open, high=dp.high, low=dp.low, close=dp.close, volume=dp.volume, oi=dp.oi
        ))
        # For DataFrame, keep datetime object
        ohlc_dict = dp.model_dump()
        ohlc_dict['time'] = dt_time
        ohlc_dicts_for_df.append(ohlc_dict)

    ohlc_df = pd.DataFrame(ohlc_dicts_for_df)
    if not ohlc_df.empty:
        ohlc_df['time'] = pd.to_datetime(ohlc_df['time'])
        ohlc_df = ohlc_df.set_index('time').sort_index()
    else:
        logger.warning("OHLC DataFrame is empty for chart generation.")
        # Still return what we have, which might be empty ohlc_data
        return ChartDataResponse(
            ohlc_data=chart_ohlc_data, indicator_data=[], trade_markers=[],
            chart_header_info=f"{chart_request.exchange}:{token_trading_symbol} ({chart_request.timeframe}) - Data Error",
            timeframe_actual=chart_request.timeframe
        )


    indicator_series_list: List[IndicatorSeries] = []
    trade_markers_list: List[TradeMarker] = []
    strategy_name_for_header = "None"

    if strategy_class and chart_request.strategy_id:
        strategy_name_for_header = strategy_class.strategy_name
        # Use a dummy portfolio for generating signals & indicators, not for actual PnL tracking here
        # Initial capital doesn't matter much for just getting indicator lines and signals
        temp_portfolio = PortfolioState(initial_capital=100000)

        # Prepare strategy parameters
        # The UI sends params like "fast_ma_length", strategy expects "fast_ema_period"
        # We need to map them or ensure consistency. EMA crossover strategy was updated to accept both.
        current_strategy_params = chart_request.strategy_params if chart_request.strategy_params else {}
        
        # Add execution_price_type for strategy, default to 'close' for charting signals
        current_strategy_params['execution_price_type'] = current_strategy_params.get('execution_price_type', 'close')


        try:
            strategy_instance = strategy_class(shared_ohlc_data=ohlc_df, params=current_strategy_params, portfolio=temp_portfolio)
            logger.info(f"Initialized strategy {chart_request.strategy_id} with params: {current_strategy_params} for chart generation.")
        except Exception as e:
            logger.error(f"Error initializing strategy {chart_request.strategy_id} for chart: {e}", exc_info=True)
            # Proceed without strategy data if init fails
            strategy_name_for_header = f"{strategy_class.strategy_name} (Error)"
        else:
            # Run process_bar to calculate indicators and generate signals
            for bar_idx in range(len(ohlc_df)):
                strategy_instance.process_bar(bar_idx) # This will populate internal indicator lists and generate signals

            # Retrieve indicator data from the strategy instance
            # Timestamps for indicators should align with ohlc_df.index
            indicator_series_list = strategy_instance.get_indicator_series(list(ohlc_df.index))

            # Convert trades from portfolio into markers
            for trade in temp_portfolio.trades:
                if trade.entry_time:
                    trade_markers_list.append(TradeMarker(
                        time=int(trade.entry_time.timestamp()),
                        position="belowBar" if trade.trade_type == "LONG" else "aboveBar",
                        color="green" if trade.trade_type == "LONG" else "red",
                        shape="arrowUp" if trade.trade_type == "LONG" else "arrowDown",
                        text=f"{trade.trade_type} Entry"
                    ))
                if trade.exit_time: # Could be None if position open at end of data
                    trade_markers_list.append(TradeMarker(
                        time=int(trade.exit_time.timestamp()),
                        position="aboveBar" if trade.trade_type == "LONG" else "belowBar", # Opposite for exit
                        color="orange", # Exit color
                        shape="square",
                        text=f"{trade.trade_type} Exit"
                    ))
    
    # Construct header
    param_str_parts = []
    if chart_request.strategy_params:
        # Show relevant params for EMA crossover
        fml = chart_request.strategy_params.get('fast_ma_length', chart_request.strategy_params.get('fast_ema_period'))
        sml = chart_request.strategy_params.get('slow_ma_length', chart_request.strategy_params.get('slow_ema_period'))
        if fml is not None: param_str_parts.append(str(fml))
        if sml is not None: param_str_parts.append(str(sml))
    param_str = ",".join(param_str_parts)
    header_strategy_part = f"{strategy_name_for_header} ({param_str})" if param_str else strategy_name_for_header
    
    chart_header = f"{chart_request.exchange.upper()}:{token_trading_symbol} ({chart_request.timeframe}) - {header_strategy_part}"


    return ChartDataResponse(
        ohlc_data=chart_ohlc_data,
        indicator_data=indicator_series_list,
        trade_markers=trade_markers_list,
        chart_header_info=chart_header,
        timeframe_actual=chart_request.timeframe # Assuming it's the same as requested
    )