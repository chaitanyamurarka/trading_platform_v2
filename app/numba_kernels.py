# app/numba_kernels.py
import numpy as np
import numba

# Define constants for Numba loop status
POSITION_NONE = 0
POSITION_LONG = 1
# POSITION_SHORT = -1 # Enable if you implement short selling in Numba

@numba.njit(nogil=True, fastmath=True) # Added fastmath for potential minor speedup
def run_ema_crossover_optimization_numba(
    # Data arrays (1D)
    open_prices: np.ndarray,
    high_prices: np.ndarray,
    low_prices: np.ndarray,
    close_prices: np.ndarray,
    
    # Parameter arrays (1D, one entry per combination)
    fast_ema_periods: np.ndarray, 
    slow_ema_periods: np.ndarray, 
    stop_loss_pcts: np.ndarray,   # Already as decimal, e.g., 0.02 for 2%
    take_profit_pcts: np.ndarray, # Already as decimal, e.g., 0.04 for 4%
    execution_price_types: np.ndarray, # 0 for close, 1 for open

    initial_capital: float,
    n_combinations: int,
    n_candles: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Numba-jitted function for EMA crossover backtests across multiple parameter combinations.
    Returns: final_pnl_arr, total_trades_arr, winning_trades_arr, losing_trades_arr, max_drawdown_arr
    """

    cash_arr = np.full(n_combinations, initial_capital, dtype=np.float64)
    position_arr = np.zeros(n_combinations, dtype=np.int64) 
    entry_price_arr = np.zeros(n_combinations, dtype=np.float64)
    
    current_fast_ema_arr = np.zeros(n_combinations, dtype=np.float64)
    prev_fast_ema_arr = np.zeros(n_combinations, dtype=np.float64)
    prev2_fast_ema_arr = np.zeros(n_combinations, dtype=np.float64)

    current_slow_ema_arr = np.zeros(n_combinations, dtype=np.float64)
    prev_slow_ema_arr = np.zeros(n_combinations, dtype=np.float64)
    prev2_slow_ema_arr = np.zeros(n_combinations, dtype=np.float64)

    sl_price_arr = np.zeros(n_combinations, dtype=np.float64)
    tp_price_arr = np.zeros(n_combinations, dtype=np.float64)

    final_pnl_arr = np.zeros(n_combinations, dtype=np.float64)
    total_trades_arr = np.zeros(n_combinations, dtype=np.int64)
    winning_trades_arr = np.zeros(n_combinations, dtype=np.int64)
    losing_trades_arr = np.zeros(n_combinations, dtype=np.int64)
    
    equity_arr = np.full(n_combinations, initial_capital, dtype=np.float64)
    peak_equity_arr = np.full(n_combinations, initial_capital, dtype=np.float64)
    max_drawdown_arr = np.zeros(n_combinations, dtype=np.float64)

    k_fast_arr = np.zeros(n_combinations, dtype=np.float64)
    k_slow_arr = np.zeros(n_combinations, dtype=np.float64)
    for k_idx in range(n_combinations):
        k_fast_arr[k_idx] = 2.0 / (float(fast_ema_periods[k_idx]) + 1.0)
        k_slow_arr[k_idx] = 2.0 / (float(slow_ema_periods[k_idx]) + 1.0)

    for i in range(n_candles):
        current_open = open_prices[i]
        current_high = high_prices[i]
        current_low = low_prices[i]
        current_close = close_prices[i]

        for k in range(n_combinations):
            # 1. Update EMAs incrementally
            prev2_fast_ema_arr[k] = prev_fast_ema_arr[k]
            prev_fast_ema_arr[k] = current_fast_ema_arr[k]
            
            prev2_slow_ema_arr[k] = prev_slow_ema_arr[k]
            prev_slow_ema_arr[k] = current_slow_ema_arr[k]

            if prev_fast_ema_arr[k] == 0.0: # Seed on first valid previous EMA
                current_fast_ema_arr[k] = current_close
            else:
                current_fast_ema_arr[k] = (current_close * k_fast_arr[k]) + \
                                          (prev_fast_ema_arr[k] * (1.0 - k_fast_arr[k]))
            
            if prev_slow_ema_arr[k] == 0.0: # Seed on first valid previous EMA
                current_slow_ema_arr[k] = current_close
            else:
                current_slow_ema_arr[k] = (current_close * k_slow_arr[k]) + \
                                          (prev_slow_ema_arr[k] * (1.0 - k_slow_arr[k]))
            
            # Warm-up check: Need valid prev2 values
            # Initial values of prev2_ema_arr are 0. Only proceed if they have been updated.
            if i < 2 or prev2_fast_ema_arr[k] == 0.0 or prev2_slow_ema_arr[k] == 0.0:
                if position_arr[k] == POSITION_LONG: equity_arr[k] = cash_arr[k] + current_close
                else: equity_arr[k] = cash_arr[k]
                if equity_arr[k] > peak_equity_arr[k]: peak_equity_arr[k] = equity_arr[k]
                current_dd = (peak_equity_arr[k] - equity_arr[k]) / peak_equity_arr[k] if peak_equity_arr[k] > 0.0 else 0.0
                if current_dd > max_drawdown_arr[k]: max_drawdown_arr[k] = current_dd
                continue

            action_taken_by_sl_tp = False
            if position_arr[k] == POSITION_LONG:
                pnl = 0.0 # Initialize pnl for the current potential trade closure
                trade_closed_this_bar = False
                exit_price = 0.0

                if sl_price_arr[k] > 1e-9 and current_low <= sl_price_arr[k]: # SL hit
                    exit_price = sl_price_arr[k]
                    trade_closed_this_bar = True
                elif tp_price_arr[k] > 1e-9 and current_high >= tp_price_arr[k]: # TP hit
                    exit_price = tp_price_arr[k]
                    trade_closed_this_bar = True
                
                if trade_closed_this_bar:
                    pnl = exit_price - entry_price_arr[k]
                    cash_arr[k] += exit_price 
                    if pnl > 0.00001: winning_trades_arr[k] += 1
                    elif pnl < -0.00001: losing_trades_arr[k] += 1 
                    position_arr[k] = POSITION_NONE
                    action_taken_by_sl_tp = True
            
            if action_taken_by_sl_tp:
                sl_price_arr[k] = 0.0 
                tp_price_arr[k] = 0.0
                entry_price_arr[k] = 0.0
                equity_arr[k] = cash_arr[k]
                if equity_arr[k] > peak_equity_arr[k]: peak_equity_arr[k] = equity_arr[k]
                current_dd = (peak_equity_arr[k] - equity_arr[k]) / peak_equity_arr[k] if peak_equity_arr[k] > 0.0 else 0.0
                if current_dd > max_drawdown_arr[k]: max_drawdown_arr[k] = current_dd
                continue 

            is_bullish_crossover = prev2_fast_ema_arr[k] <= prev2_slow_ema_arr[k] and \
                                   prev_fast_ema_arr[k] > prev_slow_ema_arr[k]
            is_bearish_crossover = prev2_fast_ema_arr[k] >= prev2_slow_ema_arr[k] and \
                                   prev_fast_ema_arr[k] < prev_slow_ema_arr[k]

            exec_price = current_open if execution_price_types[k] == 1 else current_close

            if position_arr[k] == POSITION_NONE:
                if is_bullish_crossover: 
                    position_arr[k] = POSITION_LONG
                    entry_price_arr[k] = exec_price
                    cash_arr[k] -= exec_price 
                    total_trades_arr[k] += 1
                    if stop_loss_pcts[k] > 1e-9:
                        sl_price_arr[k] = exec_price * (1.0 - stop_loss_pcts[k])
                    if take_profit_pcts[k] > 1e-9:
                        tp_price_arr[k] = exec_price * (1.0 + take_profit_pcts[k])
            elif position_arr[k] == POSITION_LONG:
                if is_bearish_crossover: 
                    pnl = exec_price - entry_price_arr[k]
                    cash_arr[k] += exec_price 
                    if pnl > 0.00001: winning_trades_arr[k] += 1
                    elif pnl < -0.00001: losing_trades_arr[k] += 1
                    position_arr[k] = POSITION_NONE
                    sl_price_arr[k] = 0.0 
                    tp_price_arr[k] = 0.0
                    entry_price_arr[k] = 0.0
            
            if position_arr[k] == POSITION_LONG:
                equity_arr[k] = cash_arr[k] + current_close 
            else: 
                equity_arr[k] = cash_arr[k]
            if equity_arr[k] > peak_equity_arr[k]: peak_equity_arr[k] = equity_arr[k]
            current_dd = (peak_equity_arr[k] - equity_arr[k]) / peak_equity_arr[k] if peak_equity_arr[k] > 0.0 else 0.0
            if current_dd > max_drawdown_arr[k]: max_drawdown_arr[k] = current_dd
            
    last_close_price = close_prices[n_candles - 1] if n_candles > 0 else 0.0
    for k in range(n_combinations):
        if position_arr[k] == POSITION_LONG:
            cash_arr[k] += last_close_price 
        final_pnl_arr[k] = cash_arr[k] - initial_capital

    return final_pnl_arr, total_trades_arr, winning_trades_arr, losing_trades_arr, max_drawdown_arr