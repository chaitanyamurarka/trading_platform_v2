# app/numba_kernels.py
import numpy as np
import numba
from numba import cuda

# Define constants for Numba loop status
POSITION_NONE = 0
POSITION_LONG = 1
POSITION_SHORT = -1

# Max trades to pre-allocate for detailed output
MAX_TRADES_FOR_DETAILED_OUTPUT = 2000

@cuda.jit
def ema_crossover_kernel(
    # Data arrays (1D) - device arrays
    open_prices_global: np.ndarray,
    high_prices_global: np.ndarray,
    low_prices_global: np.ndarray,
    close_prices_global: np.ndarray,

    # Parameter arrays (1D, one entry per combination) - device arrays
    fast_ema_periods_global: np.ndarray,
    slow_ema_periods_global: np.ndarray,
    stop_loss_pcts_global: np.ndarray,
    take_profit_pcts_global: np.ndarray,
    execution_price_types_global: np.ndarray,

    initial_capital: float,
    n_candles: int,
    detailed_output_requested: bool,

    # Output arrays - device arrays
    # These are pre-initialized on host and results written back by kernel
    cash_arr_global: np.ndarray,
    position_arr_global: np.ndarray, # Stores final position, if needed. Local var used for processing.
    entry_price_arr_global: np.ndarray, # Stores final entry price, if needed. Local var used.
    sl_price_arr_global: np.ndarray, # Stores final SL, if needed. Local var used.
    tp_price_arr_global: np.ndarray, # Stores final TP, if needed. Local var used.

    final_pnl_arr_global: np.ndarray,
    total_trades_arr_global: np.ndarray,
    winning_trades_arr_global: np.ndarray,
    losing_trades_arr_global: np.ndarray,
    
    # For equity and drawdown calculations per combination
    equity_arr_global: np.ndarray, # Stores final equity. Local var used for processing.
    peak_equity_arr_global: np.ndarray, # Stores final peak equity. Local var used.
    max_drawdown_arr_global: np.ndarray, # This is a primary output

    # Pre-calculated EMA smoothing factors
    k_fast_arr_global: np.ndarray,
    k_slow_arr_global: np.ndarray,

    # Detailed output arrays for k=0 (if requested) - device arrays
    equity_curve_values_k0_global: np.ndarray,
    fast_ema_series_k0_global: np.ndarray,
    slow_ema_series_k0_global: np.ndarray,
    trade_entry_bar_indices_k0_global: np.ndarray,
    trade_exit_bar_indices_k0_global: np.ndarray,
    trade_entry_prices_k0_global: np.ndarray,
    trade_exit_prices_k0_global: np.ndarray,
    trade_types_k0_global: np.ndarray,
    trade_pnls_k0_global: np.ndarray,
    trade_count_k0_val_arr_global: np.ndarray # 1-element array to store trade_count_k0
):
    k = cuda.grid(1) # Get the unique ID for this thread, corresponding to 'k'

    # Ensure thread is within bounds of combinations
    if k >= fast_ema_periods_global.shape[0]:
        return

    # --- Parameters for this specific combination 'k' ---
    # fast_ema_period = fast_ema_periods_global[k] # Not directly used if k_fast/slow are precomputed
    # slow_ema_period = slow_ema_periods_global[k]
    stop_loss_pct = stop_loss_pcts_global[k]
    take_profit_pct = take_profit_pcts_global[k]
    execution_price_type = execution_price_types_global[k]
    kf = k_fast_arr_global[k]
    ks = k_slow_arr_global[k]

    # --- Local state variables for this thread (combination k) ---
    cash_k = initial_capital
    position_k = POSITION_NONE
    entry_price_k = 0.0
    sl_price_k = 0.0
    tp_price_k = 0.0

    current_fast_ema_k = 0.0
    prev_fast_ema_k = 0.0 # Initialized to 0, first EMA will be current_close
    current_slow_ema_k = 0.0
    prev_slow_ema_k = 0.0 # Initialized to 0, first EMA will be current_close

    total_trades_k = 0
    winning_trades_k = 0
    losing_trades_k = 0

    equity_k = initial_capital
    peak_equity_k = initial_capital
    max_drawdown_k = 0.0

    # Detailed output specific variables, only used if k == 0
    local_trade_count_k0 = 0
    # entry_bar_idx_k0_local = -1 # Not strictly needed as a stateful variable in kernel logic

    # --- Main Loop over candles for this thread ---
    for i in range(n_candles):
        current_open = open_prices_global[i]
        current_high = high_prices_global[i]
        current_low = low_prices_global[i]
        current_close = close_prices_global[i]

        # EMA Calculation
        if i == 0: # Initialize EMAs on the first candle
            current_fast_ema_k = current_close
            current_slow_ema_k = current_close
        else:
            # prev_fast_ema_k and prev_slow_ema_k hold values from end of previous iteration i-1
            current_fast_ema_k = (current_close * kf) + (prev_fast_ema_k * (1.0 - kf))
            current_slow_ema_k = (current_close * ks) + (prev_slow_ema_k * (1.0 - ks))

        if detailed_output_requested and k == 0:
            # Check if detailed arrays have been allocated (size > 0)
            if equity_curve_values_k0_global.shape[0] > 0 and i < equity_curve_values_k0_global.shape[0]:
                fast_ema_series_k0_global[i] = current_fast_ema_k
                slow_ema_series_k0_global[i] = current_slow_ema_k

        # Warm-up period (first candle, i=0)
        if i < 1:
            current_unrealized_pnl_val = 0.0 # For clarity
            equity_k = cash_k + current_unrealized_pnl_val
            if equity_k > peak_equity_k:
                peak_equity_k = equity_k
            
            # Ensure peak_equity_k is not zero before division
            current_dd_val = 0.0
            if peak_equity_k > 0.0:
                current_dd_val = (peak_equity_k - equity_k) / peak_equity_k
            
            if current_dd_val > max_drawdown_k:
                max_drawdown_k = current_dd_val
            
            if detailed_output_requested and k == 0:
                if equity_curve_values_k0_global.shape[0] > 0 and i < equity_curve_values_k0_global.shape[0]:
                    equity_curve_values_k0_global[i] = equity_k

            prev_fast_ema_k = current_fast_ema_k
            prev_slow_ema_k = current_slow_ema_k
            continue # Skip trading logic for the very first candle

        action_taken_this_bar = False
        exec_price = current_open if execution_price_type == 1 else current_close

        # SL/TP Checks
        if position_k != POSITION_NONE:
            pnl_val = 0.0
            exit_price_sl_tp = 0.0
            closed_by_sl_tp = False
            current_trade_idx_for_log = local_trade_count_k0 -1 # For k=0 detailed log

            if position_k == POSITION_LONG:
                if sl_price_k > 0.0 and current_low <= sl_price_k:
                    exit_price_sl_tp = sl_price_k; closed_by_sl_tp = True
                elif tp_price_k > 0.0 and current_high >= tp_price_k:
                    exit_price_sl_tp = tp_price_k; closed_by_sl_tp = True
                if closed_by_sl_tp: pnl_val = exit_price_sl_tp - entry_price_k
            
            elif position_k == POSITION_SHORT:
                if sl_price_k > 0.0 and current_high >= sl_price_k:
                    exit_price_sl_tp = sl_price_k; closed_by_sl_tp = True
                elif tp_price_k > 0.0 and current_low <= tp_price_k:
                    exit_price_sl_tp = tp_price_k; closed_by_sl_tp = True
                if closed_by_sl_tp: pnl_val = entry_price_k - exit_price_sl_tp
            
            if closed_by_sl_tp:
                cash_k += pnl_val
                if pnl_val > 0.0: winning_trades_k += 1
                elif pnl_val < 0.0: losing_trades_k += 1
                
                if detailed_output_requested and k == 0:
                    if trade_entry_bar_indices_k0_global.shape[0] > 0 and \
                       current_trade_idx_for_log >= 0 and \
                       current_trade_idx_for_log < trade_entry_bar_indices_k0_global.shape[0]:
                        trade_exit_bar_indices_k0_global[current_trade_idx_for_log] = i
                        trade_exit_prices_k0_global[current_trade_idx_for_log] = exit_price_sl_tp
                        trade_pnls_k0_global[current_trade_idx_for_log] = pnl_val
                
                position_k = POSITION_NONE; entry_price_k = 0.0
                sl_price_k = 0.0; tp_price_k = 0.0
                action_taken_this_bar = True

        # Crossover Signal Logic
        if not action_taken_this_bar:
            # Ensure EMAs from previous bar are valid (non-zero) before checking crossover
            # This prevents false signals at the start if EMAs are still zero.
            # prev_fast_ema_k and prev_slow_ema_k are from candle i-1
            # current_fast_ema_k and current_slow_ema_k are for current candle i
            is_bullish_crossover = (prev_fast_ema_k != 0.0 or prev_slow_ema_k != 0.0) and \
                                   prev_fast_ema_k <= prev_slow_ema_k and \
                                   current_fast_ema_k > current_slow_ema_k
            is_bearish_crossover = (prev_fast_ema_k != 0.0 or prev_slow_ema_k != 0.0) and \
                                   prev_fast_ema_k >= prev_slow_ema_k and \
                                   current_fast_ema_k < current_slow_ema_k
            current_trade_idx_for_log_on_signal_close = local_trade_count_k0 - 1 # For k=0 detailed log

            if is_bullish_crossover:
                if position_k == POSITION_SHORT: # Close short position
                    pnl_val = entry_price_k - exec_price
                    cash_k += pnl_val
                    if pnl_val > 0.0: winning_trades_k += 1
                    elif pnl_val < 0.0: losing_trades_k += 1
                    if detailed_output_requested and k == 0:
                        if trade_entry_bar_indices_k0_global.shape[0] > 0 and \
                           current_trade_idx_for_log_on_signal_close >= 0 and \
                           current_trade_idx_for_log_on_signal_close < trade_entry_bar_indices_k0_global.shape[0]:
                            trade_exit_bar_indices_k0_global[current_trade_idx_for_log_on_signal_close] = i
                            trade_exit_prices_k0_global[current_trade_idx_for_log_on_signal_close] = exec_price
                            trade_pnls_k0_global[current_trade_idx_for_log_on_signal_close] = pnl_val
                    position_k = POSITION_NONE; entry_price_k = 0.0; sl_price_k = 0.0; tp_price_k = 0.0
                
                if position_k == POSITION_NONE: # Open long position
                    position_k = POSITION_LONG; entry_price_k = exec_price
                    total_trades_k += 1
                    if stop_loss_pct > 0.0: sl_price_k = exec_price * (1.0 - stop_loss_pct)
                    if take_profit_pct > 0.0: tp_price_k = exec_price * (1.0 + take_profit_pct)
                    # action_taken_this_bar = True # Not needed here, structure implies it
                    if detailed_output_requested and k == 0:
                        if trade_entry_bar_indices_k0_global.shape[0] > 0 and \
                           local_trade_count_k0 < trade_entry_bar_indices_k0_global.shape[0]:
                            trade_entry_bar_indices_k0_global[local_trade_count_k0] = i
                            trade_entry_prices_k0_global[local_trade_count_k0] = exec_price
                            trade_types_k0_global[local_trade_count_k0] = POSITION_LONG
                            trade_exit_bar_indices_k0_global[local_trade_count_k0] = -1 # Mark as open
                            trade_exit_prices_k0_global[local_trade_count_k0] = np.nan
                            trade_pnls_k0_global[local_trade_count_k0] = np.nan
                            local_trade_count_k0 += 1
            
            elif is_bearish_crossover:
                if position_k == POSITION_LONG: # Close long position
                    pnl_val = exec_price - entry_price_k
                    cash_k += pnl_val
                    if pnl_val > 0.0: winning_trades_k += 1
                    elif pnl_val < 0.0: losing_trades_k += 1
                    if detailed_output_requested and k == 0:
                        if trade_entry_bar_indices_k0_global.shape[0] > 0 and \
                           current_trade_idx_for_log_on_signal_close >= 0 and \
                           current_trade_idx_for_log_on_signal_close < trade_entry_bar_indices_k0_global.shape[0]:
                            trade_exit_bar_indices_k0_global[current_trade_idx_for_log_on_signal_close] = i
                            trade_exit_prices_k0_global[current_trade_idx_for_log_on_signal_close] = exec_price
                            trade_pnls_k0_global[current_trade_idx_for_log_on_signal_close] = pnl_val
                    position_k = POSITION_NONE; entry_price_k = 0.0; sl_price_k = 0.0; tp_price_k = 0.0

                if position_k == POSITION_NONE: # Open short position
                    position_k = POSITION_SHORT; entry_price_k = exec_price
                    total_trades_k += 1
                    if stop_loss_pct > 0.0: sl_price_k = exec_price * (1.0 + stop_loss_pct)
                    if take_profit_pct > 0.0: tp_price_k = exec_price * (1.0 - take_profit_pct)
                    # action_taken_this_bar = True
                    if detailed_output_requested and k == 0:
                        if trade_entry_bar_indices_k0_global.shape[0] > 0 and \
                           local_trade_count_k0 < trade_entry_bar_indices_k0_global.shape[0]:
                            trade_entry_bar_indices_k0_global[local_trade_count_k0] = i
                            trade_entry_prices_k0_global[local_trade_count_k0] = exec_price
                            trade_types_k0_global[local_trade_count_k0] = POSITION_SHORT
                            trade_exit_bar_indices_k0_global[local_trade_count_k0] = -1 # Mark as open
                            trade_exit_prices_k0_global[local_trade_count_k0] = np.nan
                            trade_pnls_k0_global[local_trade_count_k0] = np.nan
                            local_trade_count_k0 += 1
        
        # Update Equity Curve for this combination k
        current_unrealized_pnl_val = 0.0
        if position_k == POSITION_LONG: current_unrealized_pnl_val = current_close - entry_price_k
        elif position_k == POSITION_SHORT: current_unrealized_pnl_val = entry_price_k - current_close
        equity_k = cash_k + current_unrealized_pnl_val

        if equity_k > peak_equity_k: peak_equity_k = equity_k
        
        current_dd_val = 0.0
        if peak_equity_k > 0.0: # Avoid division by zero
             current_dd_val = (peak_equity_k - equity_k) / peak_equity_k
        if current_dd_val > max_drawdown_k: max_drawdown_k = current_dd_val

        if detailed_output_requested and k == 0:
            if equity_curve_values_k0_global.shape[0] > 0 and i < equity_curve_values_k0_global.shape[0]:
                equity_curve_values_k0_global[i] = equity_k
        
        # Update previous EMA values for the next iteration (candle i+1)
        prev_fast_ema_k = current_fast_ema_k
        prev_slow_ema_k = current_slow_ema_k
    # --- End of candles loop for thread k ---

    # Final PNL Calculation for thread k
    last_close_price = close_prices_global[n_candles - 1] if n_candles > 0 else 0.0
    realized_pnl_sum_k = cash_k - initial_capital
    unrealized_pnl_at_close_k = 0.0
    if position_k == POSITION_LONG: unrealized_pnl_at_close_k = last_close_price - entry_price_k
    elif position_k == POSITION_SHORT: unrealized_pnl_at_close_k = entry_price_k - last_close_price
    
    final_pnl_arr_global[k] = realized_pnl_sum_k + unrealized_pnl_at_close_k

    # Write back other summary stats for thread k to global device arrays
    total_trades_arr_global[k] = total_trades_k
    winning_trades_arr_global[k] = winning_trades_k
    losing_trades_arr_global[k] = losing_trades_k
    max_drawdown_arr_global[k] = max_drawdown_k

    # Optionally write back final state if needed for other purposes
    cash_arr_global[k] = cash_k 
    position_arr_global[k] = position_k
    entry_price_arr_global[k] = entry_price_k
    sl_price_arr_global[k] = sl_price_k
    tp_price_arr_global[k] = tp_price_k
    equity_arr_global[k] = equity_k
    peak_equity_arr_global[k] = peak_equity_k


    # Handle last open trade for detailed output if k == 0
    if detailed_output_requested and k == 0:
        trade_count_k0_val_arr_global[0] = local_trade_count_k0 # Store the final count for k=0
        if position_k != POSITION_NONE and local_trade_count_k0 > 0:
            last_trade_idx_for_log = local_trade_count_k0 - 1
            if trade_entry_bar_indices_k0_global.shape[0] > 0 and \
               last_trade_idx_for_log >= 0 and \
               last_trade_idx_for_log < trade_entry_bar_indices_k0_global.shape[0] and \
               trade_exit_bar_indices_k0_global[last_trade_idx_for_log] == -1: # If marked as open
                trade_exit_bar_indices_k0_global[last_trade_idx_for_log] = n_candles - 1 # Exit at last bar
                trade_exit_prices_k0_global[last_trade_idx_for_log] = last_close_price
                trade_pnls_k0_global[last_trade_idx_for_log] = unrealized_pnl_at_close_k


def run_ema_crossover_optimization_numba( # Name kept as per user request
    # Data arrays (1D)
    open_prices: np.ndarray, high_prices: np.ndarray, low_prices: np.ndarray, close_prices: np.ndarray,
    # Parameter arrays (1D, one entry per combination)
    fast_ema_periods: np.ndarray, slow_ema_periods: np.ndarray,
    stop_loss_pcts: np.ndarray, take_profit_pcts: np.ndarray,
    execution_price_types: np.ndarray,
    initial_capital: float, n_combinations: int, n_candles: int,
    detailed_output_requested: bool = False
) -> tuple:

    # --- Prepare Host-side Output Arrays (will be filled by copying from device) ---
    final_pnl_arr_host = np.zeros(n_combinations, dtype=np.float64)
    total_trades_arr_host = np.zeros(n_combinations, dtype=np.int64)
    winning_trades_arr_host = np.zeros(n_combinations, dtype=np.int64)
    losing_trades_arr_host = np.zeros(n_combinations, dtype=np.int64)
    max_drawdown_arr_host = np.zeros(n_combinations, dtype=np.float64)
    
    # Host arrays for state that kernel might update (optional, mainly for final state if needed outside PnL)
    cash_arr_host = np.full(n_combinations, initial_capital, dtype=np.float64)
    position_arr_host = np.full(n_combinations, POSITION_NONE, dtype=np.int64)
    entry_price_arr_host = np.zeros(n_combinations, dtype=np.float64)
    sl_price_arr_host = np.zeros(n_combinations, dtype=np.float64)
    tp_price_arr_host = np.zeros(n_combinations, dtype=np.float64)
    equity_arr_host = np.full(n_combinations, initial_capital, dtype=np.float64)
    peak_equity_arr_host = np.full(n_combinations, initial_capital, dtype=np.float64)


    k_fast_arr_host = 2.0 / (fast_ema_periods.astype(np.float64) + 1.0)
    k_slow_arr_host = 2.0 / (slow_ema_periods.astype(np.float64) + 1.0)

    # --- Detailed Output Arrays (Host side pre-allocation) ---
    equity_curve_size = n_candles if detailed_output_requested and n_combinations == 1 else 0
    equity_curve_values_k0_host = np.empty(equity_curve_size, dtype=np.float64)
    fast_ema_series_k0_host = np.empty(equity_curve_size, dtype=np.float64)
    slow_ema_series_k0_host = np.empty(equity_curve_size, dtype=np.float64)

    trade_array_size = MAX_TRADES_FOR_DETAILED_OUTPUT if detailed_output_requested and n_combinations == 1 else 0
    trade_entry_bar_indices_k0_host = np.empty(trade_array_size, dtype=np.int64)
    trade_exit_bar_indices_k0_host = np.empty(trade_array_size, dtype=np.int64)
    trade_entry_prices_k0_host = np.empty(trade_array_size, dtype=np.float64)
    trade_exit_prices_k0_host = np.empty(trade_array_size, dtype=np.float64)
    trade_types_k0_host = np.empty(trade_array_size, dtype=np.int64)
    trade_pnls_k0_host = np.empty(trade_array_size, dtype=np.float64)
    # For single counter trade_count_k0
    trade_count_k0_val_arr_host = np.array([0], dtype=np.int64)

    # --- Transfer data to GPU ---
    d_open_prices = cuda.to_device(open_prices)
    d_high_prices = cuda.to_device(high_prices)
    d_low_prices = cuda.to_device(low_prices)
    d_close_prices = cuda.to_device(close_prices)

    d_fast_ema_periods = cuda.to_device(fast_ema_periods)
    d_slow_ema_periods = cuda.to_device(slow_ema_periods)
    d_stop_loss_pcts = cuda.to_device(stop_loss_pcts)
    d_take_profit_pcts = cuda.to_device(take_profit_pcts)
    d_execution_price_types = cuda.to_device(execution_price_types)
    d_k_fast_arr = cuda.to_device(k_fast_arr_host)
    d_k_slow_arr = cuda.to_device(k_slow_arr_host)

    # Device arrays for outputs and intermediate states modified by kernel
    d_cash_arr = cuda.to_device(cash_arr_host)
    d_position_arr = cuda.to_device(position_arr_host)
    d_entry_price_arr = cuda.to_device(entry_price_arr_host)
    d_sl_price_arr = cuda.to_device(sl_price_arr_host)
    d_tp_price_arr = cuda.to_device(tp_price_arr_host)
    
    d_final_pnl_arr = cuda.to_device(final_pnl_arr_host) # Kernel will fill this
    d_total_trades_arr = cuda.to_device(total_trades_arr_host)
    d_winning_trades_arr = cuda.to_device(winning_trades_arr_host)
    d_losing_trades_arr = cuda.to_device(losing_trades_arr_host)
    d_equity_arr = cuda.to_device(equity_arr_host)
    d_peak_equity_arr = cuda.to_device(peak_equity_arr_host)
    d_max_drawdown_arr = cuda.to_device(max_drawdown_arr_host)


    # Detailed Output Arrays (Device)
    d_equity_curve_values_k0 = cuda.to_device(equity_curve_values_k0_host)
    d_fast_ema_series_k0 = cuda.to_device(fast_ema_series_k0_host)
    d_slow_ema_series_k0 = cuda.to_device(slow_ema_series_k0_host)
    d_trade_entry_bar_indices_k0 = cuda.to_device(trade_entry_bar_indices_k0_host)
    d_trade_exit_bar_indices_k0 = cuda.to_device(trade_exit_bar_indices_k0_host)
    d_trade_entry_prices_k0 = cuda.to_device(trade_entry_prices_k0_host)
    d_trade_exit_prices_k0 = cuda.to_device(trade_exit_prices_k0_host)
    d_trade_types_k0 = cuda.to_device(trade_types_k0_host)
    d_trade_pnls_k0 = cuda.to_device(trade_pnls_k0_host)
    d_trade_count_k0_val_arr = cuda.to_device(trade_count_k0_val_arr_host)

    # --- Kernel launch configuration ---
    threads_per_block = 256 # Typical value, can be tuned (e.g., 128, 256, 512)
    blocks_per_grid = (n_combinations + (threads_per_block - 1)) // threads_per_block

    # --- Launch Kernel ---
    ema_crossover_kernel[blocks_per_grid, threads_per_block](
        d_open_prices, d_high_prices, d_low_prices, d_close_prices,
        d_fast_ema_periods, d_slow_ema_periods,
        d_stop_loss_pcts, d_take_profit_pcts, d_execution_price_types,
        initial_capital, n_candles,
        detailed_output_requested,

        d_cash_arr, d_position_arr, d_entry_price_arr,
        d_sl_price_arr, d_tp_price_arr,
        d_final_pnl_arr, d_total_trades_arr,
        d_winning_trades_arr, d_losing_trades_arr,
        d_equity_arr, d_peak_equity_arr, d_max_drawdown_arr,
        d_k_fast_arr, d_k_slow_arr,

        d_equity_curve_values_k0,
        d_fast_ema_series_k0, d_slow_ema_series_k0,
        d_trade_entry_bar_indices_k0, d_trade_exit_bar_indices_k0,
        d_trade_entry_prices_k0, d_trade_exit_prices_k0,
        d_trade_types_k0, d_trade_pnls_k0,
        d_trade_count_k0_val_arr
    )
    cuda.synchronize() # Wait for kernel to complete

    # --- Copy results back from GPU to CPU ---
    final_pnl_arr = d_final_pnl_arr.copy_to_host()
    total_trades_arr = d_total_trades_arr.copy_to_host()
    winning_trades_arr = d_winning_trades_arr.copy_to_host()
    losing_trades_arr = d_losing_trades_arr.copy_to_host()
    max_drawdown_arr = d_max_drawdown_arr.copy_to_host()

    # For detailed output
    if detailed_output_requested and n_combinations == 1:
        equity_curve_values_k0 = d_equity_curve_values_k0.copy_to_host()
        fast_ema_series_k0 = d_fast_ema_series_k0.copy_to_host()
        slow_ema_series_k0 = d_slow_ema_series_k0.copy_to_host()

        # Retrieve the actual trade count for k=0 from the device
        trade_count_k0_val_arr_host = d_trade_count_k0_val_arr.copy_to_host()
        trade_count_k0 = trade_count_k0_val_arr_host[0]

        # Slice trade arrays to actual count
        actual_trades_entry_bar_indices = d_trade_entry_bar_indices_k0.copy_to_host()[:trade_count_k0]
        actual_trades_exit_bar_indices = d_trade_exit_bar_indices_k0.copy_to_host()[:trade_count_k0]
        actual_trades_entry_prices = d_trade_entry_prices_k0.copy_to_host()[:trade_count_k0]
        actual_trades_exit_prices = d_trade_exit_prices_k0.copy_to_host()[:trade_count_k0]
        actual_trades_types = d_trade_types_k0.copy_to_host()[:trade_count_k0]
        actual_trades_pnls = d_trade_pnls_k0.copy_to_host()[:trade_count_k0]
        # Return the count in an array as per original structure
        trade_count_k0_arr_ret = np.array([trade_count_k0], dtype=np.int64)
    else:
        # Use the empty host arrays (initialized with size 0 if conditions not met)
        equity_curve_values_k0 = equity_curve_values_k0_host
        fast_ema_series_k0 = fast_ema_series_k0_host
        slow_ema_series_k0 = slow_ema_series_k0_host

        actual_trades_entry_bar_indices = np.empty(0, dtype=np.int64)
        actual_trades_exit_bar_indices = np.empty(0, dtype=np.int64)
        actual_trades_entry_prices = np.empty(0, dtype=np.float64)
        actual_trades_exit_prices = np.empty(0, dtype=np.float64)
        actual_trades_types = np.empty(0, dtype=np.int64)
        actual_trades_pnls = np.empty(0, dtype=np.float64)
        trade_count_k0_arr_ret = np.array([0], dtype=np.int64) # Placeholder

    return (
        final_pnl_arr, total_trades_arr, winning_trades_arr, losing_trades_arr, max_drawdown_arr,
        equity_curve_values_k0, fast_ema_series_k0, slow_ema_series_k0,
        actual_trades_entry_bar_indices, actual_trades_exit_bar_indices,
        actual_trades_entry_prices, actual_trades_exit_prices,
        actual_trades_types, actual_trades_pnls,
        trade_count_k0_arr_ret
    )
