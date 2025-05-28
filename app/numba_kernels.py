# app/numba_kernels.py
import numpy as np
import numba

# Define constants for Numba loop status
POSITION_NONE = 0
POSITION_LONG = 1
POSITION_SHORT = -1

# Max trades to pre-allocate for detailed output
MAX_TRADES_FOR_DETAILED_OUTPUT = 2000

@numba.njit(nogil=True, fastmath=True)
def run_ema_crossover_optimization_numba(
    # Data arrays (1D)
    open_prices: np.ndarray,
    high_prices: np.ndarray,
    low_prices: np.ndarray,
    close_prices: np.ndarray,
    
    # Parameter arrays (1D, one entry per combination)
    fast_ema_periods: np.ndarray, 
    slow_ema_periods: np.ndarray, 
    stop_loss_pcts: np.ndarray,
    take_profit_pcts: np.ndarray,
    execution_price_types: np.ndarray,

    initial_capital: float,
    n_combinations: int,
    n_candles: int,
    detailed_output_requested: bool = False
) -> tuple:
    # --- Existing summary metric arrays ---
    cash_arr = np.full(n_combinations, initial_capital, dtype=np.float64)
    position_arr = np.full(n_combinations, POSITION_NONE, dtype=np.int64) 
    entry_price_arr = np.zeros(n_combinations, dtype=np.float64)
    
    current_fast_ema_arr = np.zeros(n_combinations, dtype=np.float64)
    prev_fast_ema_arr = np.zeros(n_combinations, dtype=np.float64)
    current_slow_ema_arr = np.zeros(n_combinations, dtype=np.float64)
    prev_slow_ema_arr = np.zeros(n_combinations, dtype=np.float64)

    sl_price_arr = np.zeros(n_combinations, dtype=np.float64)
    tp_price_arr = np.zeros(n_combinations, dtype=np.float64)

    final_pnl_arr = np.zeros(n_combinations, dtype=np.float64)
    total_trades_arr = np.zeros(n_combinations, dtype=np.int64)
    winning_trades_arr = np.zeros(n_combinations, dtype=np.int64)
    losing_trades_arr = np.zeros(n_combinations, dtype=np.int64)
    
    equity_arr = np.full(n_combinations, initial_capital, dtype=np.float64)
    peak_equity_arr = np.full(n_combinations, initial_capital, dtype=np.float64)
    max_drawdown_arr = np.zeros(n_combinations, dtype=np.float64)

    k_fast_arr = 2.0 / (fast_ema_periods.astype(np.float64) + 1.0)
    k_slow_arr = 2.0 / (slow_ema_periods.astype(np.float64) + 1.0)

    # --- Arrays for detailed output ---
    # Initialize them whether they are filled or not, to ensure consistent return types.
    
    # For equity curve (k=0)
    # If detailed output is requested for a single combination, size is n_candles, otherwise 0.
    equity_curve_size = n_candles if detailed_output_requested and n_combinations == 1 else 0
    equity_curve_values_k0 = np.empty(equity_curve_size, dtype=np.float64)
    
    # For EMA series (k=0)
    fast_ema_series_k0 = np.empty(equity_curve_size, dtype=np.float64) # Same size as equity curve
    slow_ema_series_k0 = np.empty(equity_curve_size, dtype=np.float64) # Same size as equity curve

    # For trade logging (k=0)
    trade_array_size = MAX_TRADES_FOR_DETAILED_OUTPUT if detailed_output_requested and n_combinations == 1 else 0
    trade_count_k0 = 0 # This will remain 0 if not used.
    
    trade_entry_bar_indices_k0 = np.empty(trade_array_size, dtype=np.int64)
    trade_exit_bar_indices_k0 = np.empty(trade_array_size, dtype=np.int64)
    trade_entry_prices_k0 = np.empty(trade_array_size, dtype=np.float64)
    trade_exit_prices_k0 = np.empty(trade_array_size, dtype=np.float64)
    trade_types_k0 = np.empty(trade_array_size, dtype=np.int64)
    trade_pnls_k0 = np.empty(trade_array_size, dtype=np.float64)
    
    entry_bar_idx_k0 = -1 

    # --- Main Loop ---
    for i in range(n_candles):
        current_open = open_prices[i]
        current_high = high_prices[i]
        current_low = low_prices[i]
        current_close = close_prices[i]

        for k in range(n_combinations):
            # EMA Calculation
            if i > 0: pass 
            if prev_fast_ema_arr[k] == 0.0: current_fast_ema_arr[k] = current_close
            else: current_fast_ema_arr[k] = (current_close * k_fast_arr[k]) + (prev_fast_ema_arr[k] * (1.0 - k_fast_arr[k]))
            if prev_slow_ema_arr[k] == 0.0: current_slow_ema_arr[k] = current_close
            else: current_slow_ema_arr[k] = (current_close * k_slow_arr[k]) + (prev_slow_ema_arr[k] * (1.0 - k_slow_arr[k]))

            if detailed_output_requested and k == 0 and n_combinations == 1:
                if i < equity_curve_size: # Ensure within bounds if n_candles > 0
                    fast_ema_series_k0[i] = current_fast_ema_arr[k]
                    slow_ema_series_k0[i] = current_slow_ema_arr[k]

            if i < 1: # Warm-up
                current_unrealized_pnl_k = 0.0
                equity_arr[k] = cash_arr[k] + current_unrealized_pnl_k
                if equity_arr[k] > peak_equity_arr[k]: peak_equity_arr[k] = equity_arr[k]
                current_dd_k = (peak_equity_arr[k] - equity_arr[k]) / peak_equity_arr[k] if peak_equity_arr[k] > 0.0 else 0.0
                if current_dd_k > max_drawdown_arr[k]: max_drawdown_arr[k] = current_dd_k
                
                if detailed_output_requested and k == 0 and n_combinations == 1:
                    if i < equity_curve_size: equity_curve_values_k0[i] = equity_arr[k]

                prev_fast_ema_arr[k] = current_fast_ema_arr[k]
                prev_slow_ema_arr[k] = current_slow_ema_arr[k]
                continue

            action_taken_this_bar = False
            exec_price = current_open if execution_price_types[k] == 1 else current_close

            # SL/TP Checks
            if position_arr[k] != POSITION_NONE:
                pnl_k = 0.0
                exit_price_sl_tp = 0.0
                closed_by_sl_tp = False
                current_trade_idx_for_log = trade_count_k0 -1 # Assuming trade_count_k0 was incremented at entry

                if position_arr[k] == POSITION_LONG:
                    if sl_price_arr[k] > 0.0 and current_low <= sl_price_arr[k]:
                        exit_price_sl_tp = sl_price_arr[k]; closed_by_sl_tp = True
                    elif tp_price_arr[k] > 0.0 and current_high >= tp_price_arr[k]:
                        exit_price_sl_tp = tp_price_arr[k]; closed_by_sl_tp = True
                    if closed_by_sl_tp: pnl_k = exit_price_sl_tp - entry_price_arr[k]
                
                elif position_arr[k] == POSITION_SHORT:
                    if sl_price_arr[k] > 0.0 and current_high >= sl_price_arr[k]:
                        exit_price_sl_tp = sl_price_arr[k]; closed_by_sl_tp = True
                    elif tp_price_arr[k] > 0.0 and current_low <= tp_price_arr[k]:
                        exit_price_sl_tp = tp_price_arr[k]; closed_by_sl_tp = True
                    if closed_by_sl_tp: pnl_k = entry_price_arr[k] - exit_price_sl_tp
                
                if closed_by_sl_tp:
                    cash_arr[k] += pnl_k
                    if pnl_k > 0.0: winning_trades_arr[k] += 1
                    elif pnl_k < 0.0: losing_trades_arr[k] += 1
                    
                    if detailed_output_requested and k == 0 and n_combinations == 1 and current_trade_idx_for_log >= 0 and current_trade_idx_for_log < MAX_TRADES_FOR_DETAILED_OUTPUT : # Check index bounds
                        trade_exit_bar_indices_k0[current_trade_idx_for_log] = i 
                        trade_exit_prices_k0[current_trade_idx_for_log] = exit_price_sl_tp
                        trade_pnls_k0[current_trade_idx_for_log] = pnl_k
                    
                    position_arr[k] = POSITION_NONE; entry_price_arr[k] = 0.0
                    sl_price_arr[k] = 0.0; tp_price_arr[k] = 0.0
                    action_taken_this_bar = True
                    if k == 0: entry_bar_idx_k0 = -1

            # Crossover Signal Logic
            if not action_taken_this_bar:
                is_bullish_crossover = prev_fast_ema_arr[k] <= prev_slow_ema_arr[k] and current_fast_ema_arr[k] > current_slow_ema_arr[k]
                is_bearish_crossover = prev_fast_ema_arr[k] >= prev_slow_ema_arr[k] and current_fast_ema_arr[k] < current_slow_ema_arr[k]
                current_trade_idx_for_log_on_signal_close = trade_count_k0 -1


                if is_bullish_crossover:
                    if position_arr[k] == POSITION_SHORT: 
                        pnl_k = entry_price_arr[k] - exec_price
                        cash_arr[k] += pnl_k
                        if pnl_k > 0.0: winning_trades_arr[k] += 1
                        elif pnl_k < 0.0: losing_trades_arr[k] += 1
                        if detailed_output_requested and k == 0 and n_combinations == 1 and current_trade_idx_for_log_on_signal_close >=0 and current_trade_idx_for_log_on_signal_close < MAX_TRADES_FOR_DETAILED_OUTPUT:
                            trade_exit_bar_indices_k0[current_trade_idx_for_log_on_signal_close] = i
                            trade_exit_prices_k0[current_trade_idx_for_log_on_signal_close] = exec_price
                            trade_pnls_k0[current_trade_idx_for_log_on_signal_close] = pnl_k
                        position_arr[k] = POSITION_NONE; entry_price_arr[k] = 0.0; sl_price_arr[k] = 0.0; tp_price_arr[k] = 0.0
                        if k == 0: entry_bar_idx_k0 = -1
                    
                    if position_arr[k] == POSITION_NONE: 
                        position_arr[k] = POSITION_LONG; entry_price_arr[k] = exec_price
                        total_trades_arr[k] += 1
                        if stop_loss_pcts[k] > 0.0: sl_price_arr[k] = exec_price * (1.0 - stop_loss_pcts[k])
                        if take_profit_pcts[k] > 0.0: tp_price_arr[k] = exec_price * (1.0 + take_profit_pcts[k])
                        action_taken_this_bar = True
                        if detailed_output_requested and k == 0 and n_combinations == 1 and trade_count_k0 < MAX_TRADES_FOR_DETAILED_OUTPUT:
                            trade_entry_bar_indices_k0[trade_count_k0] = i
                            trade_entry_prices_k0[trade_count_k0] = exec_price
                            trade_types_k0[trade_count_k0] = POSITION_LONG
                            trade_exit_bar_indices_k0[trade_count_k0] = -1 
                            trade_exit_prices_k0[trade_count_k0] = np.nan 
                            trade_pnls_k0[trade_count_k0] = np.nan 
                            entry_bar_idx_k0 = i
                            trade_count_k0 += 1

                elif is_bearish_crossover: 
                    if position_arr[k] == POSITION_LONG: 
                        pnl_k = exec_price - entry_price_arr[k]
                        cash_arr[k] += pnl_k
                        if pnl_k > 0.0: winning_trades_arr[k] += 1
                        elif pnl_k < 0.0: losing_trades_arr[k] += 1
                        if detailed_output_requested and k == 0 and n_combinations == 1 and current_trade_idx_for_log_on_signal_close >=0 and current_trade_idx_for_log_on_signal_close < MAX_TRADES_FOR_DETAILED_OUTPUT:
                            trade_exit_bar_indices_k0[current_trade_idx_for_log_on_signal_close] = i
                            trade_exit_prices_k0[current_trade_idx_for_log_on_signal_close] = exec_price
                            trade_pnls_k0[current_trade_idx_for_log_on_signal_close] = pnl_k
                        position_arr[k] = POSITION_NONE; entry_price_arr[k] = 0.0; sl_price_arr[k] = 0.0; tp_price_arr[k] = 0.0
                        if k == 0: entry_bar_idx_k0 = -1

                    if position_arr[k] == POSITION_NONE: 
                        position_arr[k] = POSITION_SHORT; entry_price_arr[k] = exec_price
                        total_trades_arr[k] += 1
                        if stop_loss_pcts[k] > 0.0: sl_price_arr[k] = exec_price * (1.0 + stop_loss_pcts[k])
                        if take_profit_pcts[k] > 0.0: tp_price_arr[k] = exec_price * (1.0 - take_profit_pcts[k])
                        action_taken_this_bar = True
                        if detailed_output_requested and k == 0 and n_combinations == 1 and trade_count_k0 < MAX_TRADES_FOR_DETAILED_OUTPUT:
                            trade_entry_bar_indices_k0[trade_count_k0] = i
                            trade_entry_prices_k0[trade_count_k0] = exec_price
                            trade_types_k0[trade_count_k0] = POSITION_SHORT
                            trade_exit_bar_indices_k0[trade_count_k0] = -1 
                            trade_exit_prices_k0[trade_count_k0] = np.nan
                            trade_pnls_k0[trade_count_k0] = np.nan
                            entry_bar_idx_k0 = i
                            trade_count_k0 += 1
            
            # Update Equity Curve
            current_unrealized_pnl_k = 0.0
            if position_arr[k] == POSITION_LONG: current_unrealized_pnl_k = current_close - entry_price_arr[k]
            elif position_arr[k] == POSITION_SHORT: current_unrealized_pnl_k = entry_price_arr[k] - current_close
            equity_arr[k] = cash_arr[k] + current_unrealized_pnl_k

            if equity_arr[k] > peak_equity_arr[k]: peak_equity_arr[k] = equity_arr[k]
            current_dd_k = (peak_equity_arr[k] - equity_arr[k]) / peak_equity_arr[k] if peak_equity_arr[k] > 0.0 else 0.0
            if current_dd_k > max_drawdown_arr[k]: max_drawdown_arr[k] = current_dd_k

            if detailed_output_requested and k == 0 and n_combinations == 1:
                if i < equity_curve_size: equity_curve_values_k0[i] = equity_arr[k]

            prev_fast_ema_arr[k] = current_fast_ema_arr[k]
            prev_slow_ema_arr[k] = current_slow_ema_arr[k]

    # Final PNL Calculation
    last_close_price = close_prices[n_candles - 1] if n_candles > 0 else 0.0
    for k_final in range(n_combinations):
        realized_pnl_sum = cash_arr[k_final] - initial_capital
        unrealized_pnl_at_close = 0.0
        if position_arr[k_final] == POSITION_LONG: unrealized_pnl_at_close = last_close_price - entry_price_arr[k_final]
        elif position_arr[k_final] == POSITION_SHORT: unrealized_pnl_at_close = entry_price_arr[k_final] - last_close_price
        final_pnl_arr[k_final] = realized_pnl_sum + unrealized_pnl_at_close

        if detailed_output_requested and k_final == 0 and n_combinations == 1 and \
           position_arr[k_final] != POSITION_NONE and trade_count_k0 > 0:
            # Check if the last trade recorded is still open
            last_trade_index = trade_count_k0 - 1
            if last_trade_index >=0 and last_trade_index < MAX_TRADES_FOR_DETAILED_OUTPUT and trade_exit_bar_indices_k0[last_trade_index] == -1:
                trade_exit_bar_indices_k0[last_trade_index] = n_candles - 1
                trade_exit_prices_k0[last_trade_index] = last_close_price
                trade_pnls_k0[last_trade_index] = unrealized_pnl_at_close

    # --- Always return the full tuple structure ---
    # If detailed output was not requested, the detailed arrays will be empty (size 0)
    # as initialized if equity_curve_size or trade_array_size was 0.
    
    # Slice trade arrays to actual count for the detailed case
    if detailed_output_requested and n_combinations == 1:
        actual_trades_entry_bar_indices = trade_entry_bar_indices_k0[:trade_count_k0]
        actual_trades_exit_bar_indices = trade_exit_bar_indices_k0[:trade_count_k0]
        actual_trades_entry_prices = trade_entry_prices_k0[:trade_count_k0]
        actual_trades_exit_prices = trade_exit_prices_k0[:trade_count_k0]
        actual_trades_types = trade_types_k0[:trade_count_k0]
        actual_trades_pnls = trade_pnls_k0[:trade_count_k0]
        trade_count_k0_arr = np.array([trade_count_k0], dtype=np.int64)
    else:
        # Create empty arrays of correct type for the detailed slots if not used
        actual_trades_entry_bar_indices = np.empty(0, dtype=np.int64)
        actual_trades_exit_bar_indices = np.empty(0, dtype=np.int64)
        actual_trades_entry_prices = np.empty(0, dtype=np.float64)
        actual_trades_exit_prices = np.empty(0, dtype=np.float64)
        actual_trades_types = np.empty(0, dtype=np.int64)
        actual_trades_pnls = np.empty(0, dtype=np.float64)
        trade_count_k0_arr = np.array([0], dtype=np.int64) # Placeholder if not detailed

    return (
        final_pnl_arr, 
        total_trades_arr, 
        winning_trades_arr, 
        losing_trades_arr, 
        max_drawdown_arr,
        equity_curve_values_k0, # Will be size n_candles or 0
        fast_ema_series_k0,     # Will be size n_candles or 0
        slow_ema_series_k0,     # Will be size n_candles or 0
        actual_trades_entry_bar_indices, # Potentially sliced or empty
        actual_trades_exit_bar_indices,  # Potentially sliced or empty
        actual_trades_entry_prices,      # Potentially sliced or empty
        actual_trades_exit_prices,       # Potentially sliced or empty
        actual_trades_types,             # Potentially sliced or empty
        actual_trades_pnls,              # Potentially sliced or empty
        trade_count_k0_arr               # Contains actual trade_count_k0 or 0
    )