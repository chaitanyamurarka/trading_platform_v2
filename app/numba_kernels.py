# app/numba_kernels.py
import numpy as np
import numba

# Define constants for Numba loop status
POSITION_NONE = 0
POSITION_LONG = 1
POSITION_SHORT = -1 # Enabled for short selling

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
    stop_loss_pcts: np.ndarray,   # Already as decimal, e.g., 0.02 for 2%
    take_profit_pcts: np.ndarray, # Already as decimal, e.g., 0.04 for 4%
    execution_price_types: np.ndarray, # 0 for close, 1 for open

    initial_capital: float,
    n_combinations: int,
    n_candles: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Numba-jitted function for EMA crossover backtests across multiple parameter combinations.
    Includes logic for both long and short trades.
    Returns: final_pnl_arr, total_trades_arr, winning_trades_arr, losing_trades_arr, max_drawdown_arr
    """

    # cash_arr now represents initial_capital + sum_of_realized_pnl
    cash_arr = np.full(n_combinations, initial_capital, dtype=np.float64)
    position_arr = np.full(n_combinations, POSITION_NONE, dtype=np.int64) 
    entry_price_arr = np.zeros(n_combinations, dtype=np.float64)
    
    current_fast_ema_arr = np.zeros(n_combinations, dtype=np.float64)
    prev_fast_ema_arr = np.zeros(n_combinations, dtype=np.float64)

    current_slow_ema_arr = np.zeros(n_combinations, dtype=np.float64)
    prev_slow_ema_arr = np.zeros(n_combinations, dtype=np.float64)

    sl_price_arr = np.zeros(n_combinations, dtype=np.float64)
    tp_price_arr = np.zeros(n_combinations, dtype=np.float64)

    # final_pnl_arr will store the total PNL (realized + unrealized from any final open position)
    final_pnl_arr = np.zeros(n_combinations, dtype=np.float64)
    total_trades_arr = np.zeros(n_combinations, dtype=np.int64)
    winning_trades_arr = np.zeros(n_combinations, dtype=np.int64)
    losing_trades_arr = np.zeros(n_combinations, dtype=np.int64)
    
    equity_arr = np.full(n_combinations, initial_capital, dtype=np.float64)
    peak_equity_arr = np.full(n_combinations, initial_capital, dtype=np.float64)
    max_drawdown_arr = np.zeros(n_combinations, dtype=np.float64)

    k_fast_arr = 2.0 / (fast_ema_periods.astype(np.float64) + 1.0)
    k_slow_arr = 2.0 / (slow_ema_periods.astype(np.float64) + 1.0)

    for i in range(n_candles):
        current_open = open_prices[i]
        current_high = high_prices[i]
        current_low = low_prices[i]
        current_close = close_prices[i]

        for k in range(n_combinations):
            # 1. Update EMAs incrementally
            # Store EMA of bar i-1 before calculating EMA for bar i
            if i > 0: # prev_ema already holds EMA[i-1] if i > 0
                pass
            
            # Calculate EMA for current bar i
            if prev_fast_ema_arr[k] == 0.0: # Seed EMA on first pass or if it's reset
                current_fast_ema_arr[k] = current_close
            else:
                current_fast_ema_arr[k] = (current_close * k_fast_arr[k]) + \
                                          (prev_fast_ema_arr[k] * (1.0 - k_fast_arr[k]))
            
            if prev_slow_ema_arr[k] == 0.0: # Seed EMA
                current_slow_ema_arr[k] = current_close
            else:
                current_slow_ema_arr[k] = (current_close * k_slow_arr[k]) + \
                                          (prev_slow_ema_arr[k] * (1.0 - k_slow_arr[k]))

            # --- Signal Generation and Execution Logic ---
            # Warm-up: Need at least one previous bar's EMAs to compare for a crossover
            if i < 1:
                # Update equity curve even during warm-up
                current_unrealized_pnl_k = 0.0
                if position_arr[k] == POSITION_LONG:
                    current_unrealized_pnl_k = current_close - entry_price_arr[k]
                elif position_arr[k] == POSITION_SHORT:
                    current_unrealized_pnl_k = entry_price_arr[k] - current_close
                equity_arr[k] = (cash_arr[k] - initial_capital) + initial_capital + current_unrealized_pnl_k # cash_arr[k] = IC + realized_pnl

                if equity_arr[k] > peak_equity_arr[k]:
                    peak_equity_arr[k] = equity_arr[k]
                current_dd_k = (peak_equity_arr[k] - equity_arr[k]) / peak_equity_arr[k] if peak_equity_arr[k] > 0.0 else 0.0
                if current_dd_k > max_drawdown_arr[k]:
                    max_drawdown_arr[k] = current_dd_k
                
                # Update prev_ema for next iteration before continue
                prev_fast_ema_arr[k] = current_fast_ema_arr[k]
                prev_slow_ema_arr[k] = current_slow_ema_arr[k]
                continue

            action_taken_this_bar = False
            exec_price = current_open if execution_price_types[k] == 1 else current_close

            # 2. Check Stop-Loss / Take-Profit for existing positions
            if position_arr[k] != POSITION_NONE:
                pnl_k = 0.0
                exit_price_sl_tp = 0.0
                closed_by_sl_tp = False

                if position_arr[k] == POSITION_LONG:
                    if sl_price_arr[k] > 1e-9 and current_low <= sl_price_arr[k]:
                        exit_price_sl_tp = sl_price_arr[k] # Exit at SL price
                        closed_by_sl_tp = True
                    elif tp_price_arr[k] > 1e-9 and current_high >= tp_price_arr[k]:
                        exit_price_sl_tp = tp_price_arr[k] # Exit at TP price
                        closed_by_sl_tp = True
                    
                    if closed_by_sl_tp:
                        pnl_k = exit_price_sl_tp - entry_price_arr[k]
                
                elif position_arr[k] == POSITION_SHORT:
                    if sl_price_arr[k] > 1e-9 and current_high >= sl_price_arr[k]:
                        exit_price_sl_tp = sl_price_arr[k]
                        closed_by_sl_tp = True
                    elif tp_price_arr[k] > 1e-9 and current_low <= tp_price_arr[k]:
                        exit_price_sl_tp = tp_price_arr[k]
                        closed_by_sl_tp = True

                    if closed_by_sl_tp:
                        pnl_k = entry_price_arr[k] - exit_price_sl_tp
                
                if closed_by_sl_tp:
                    cash_arr[k] += pnl_k
                    if pnl_k > 1e-9: winning_trades_arr[k] += 1
                    elif pnl_k < -1e-9: losing_trades_arr[k] += 1
                    
                    position_arr[k] = POSITION_NONE
                    entry_price_arr[k] = 0.0
                    sl_price_arr[k] = 0.0
                    tp_price_arr[k] = 0.0
                    action_taken_this_bar = True

            # 3. Check Crossover Signals (if not closed by SL/TP)
            if not action_taken_this_bar:
                # prev_ema_arr holds EMA[i-1], current_ema_arr holds EMA[i]
                is_bullish_crossover = prev_fast_ema_arr[k] <= prev_slow_ema_arr[k] and \
                                       current_fast_ema_arr[k] > current_slow_ema_arr[k]
                is_bearish_crossover = prev_fast_ema_arr[k] >= prev_slow_ema_arr[k] and \
                                       current_fast_ema_arr[k] < current_slow_ema_arr[k]

                # Apply signals based on BaseStrategy logic (close-and-reverse)
                if is_bullish_crossover: # "BUY" signal
                    if position_arr[k] == POSITION_SHORT: # Close short first
                        pnl_k = entry_price_arr[k] - exec_price # PNL from closing short
                        cash_arr[k] += pnl_k
                        if pnl_k > 1e-9: winning_trades_arr[k] += 1
                        elif pnl_k < -1e-9: losing_trades_arr[k] += 1
                        # total_trades_arr already counted for the short entry
                        position_arr[k] = POSITION_NONE # Reset before new trade
                        entry_price_arr[k] = 0.0
                        sl_price_arr[k] = 0.0
                        tp_price_arr[k] = 0.0
                    
                    if position_arr[k] == POSITION_NONE: # Enter long
                        position_arr[k] = POSITION_LONG
                        entry_price_arr[k] = exec_price
                        total_trades_arr[k] += 1
                        if stop_loss_pcts[k] > 1e-9:
                            sl_price_arr[k] = exec_price * (1.0 - stop_loss_pcts[k])
                        if take_profit_pcts[k] > 1e-9:
                            tp_price_arr[k] = exec_price * (1.0 + take_profit_pcts[k])
                    action_taken_this_bar = True

                elif is_bearish_crossover: # "SELL" signal
                    if position_arr[k] == POSITION_LONG: # Close long first
                        pnl_k = exec_price - entry_price_arr[k] # PNL from closing long
                        cash_arr[k] += pnl_k
                        if pnl_k > 1e-9: winning_trades_arr[k] += 1
                        elif pnl_k < -1e-9: losing_trades_arr[k] += 1
                        # total_trades_arr already counted for the long entry
                        position_arr[k] = POSITION_NONE # Reset before new trade
                        entry_price_arr[k] = 0.0
                        sl_price_arr[k] = 0.0
                        tp_price_arr[k] = 0.0

                    if position_arr[k] == POSITION_NONE: # Enter short
                        position_arr[k] = POSITION_SHORT
                        entry_price_arr[k] = exec_price
                        total_trades_arr[k] += 1
                        if stop_loss_pcts[k] > 1e-9:
                            sl_price_arr[k] = exec_price * (1.0 + stop_loss_pcts[k])
                        if take_profit_pcts[k] > 1e-9:
                            tp_price_arr[k] = exec_price * (1.0 - take_profit_pcts[k])
                    action_taken_this_bar = True
            
            # 4. Update Equity Curve
            current_unrealized_pnl_k = 0.0
            if position_arr[k] == POSITION_LONG:
                current_unrealized_pnl_k = current_close - entry_price_arr[k]
            elif position_arr[k] == POSITION_SHORT:
                current_unrealized_pnl_k = entry_price_arr[k] - current_close
            
            # cash_arr[k] is (initial_capital + realized_pnl_so_far)
            equity_arr[k] = cash_arr[k] + current_unrealized_pnl_k

            if equity_arr[k] > peak_equity_arr[k]:
                peak_equity_arr[k] = equity_arr[k]
            current_dd_k = (peak_equity_arr[k] - equity_arr[k]) / peak_equity_arr[k] if peak_equity_arr[k] > 0.0 else 0.0
            if current_dd_k > max_drawdown_arr[k]:
                max_drawdown_arr[k] = current_dd_k

            # IMPORTANT: Update prev_ema_arr for the next candle's calculation
            prev_fast_ema_arr[k] = current_fast_ema_arr[k]
            prev_slow_ema_arr[k] = current_slow_ema_arr[k]

    # 5. Final PNL Calculation (after all candles)
    last_close_price = close_prices[n_candles - 1] if n_candles > 0 else 0.0
    for k_final in range(n_combinations):
        realized_pnl_sum = cash_arr[k_final] - initial_capital
        unrealized_pnl_at_close = 0.0
        
        if position_arr[k_final] == POSITION_LONG:
            unrealized_pnl_at_close = last_close_price - entry_price_arr[k_final]
        elif position_arr[k_final] == POSITION_SHORT:
            unrealized_pnl_at_close = entry_price_arr[k_final] - last_close_price
            
        final_pnl_arr[k_final] = realized_pnl_sum + unrealized_pnl_at_close

    return final_pnl_arr, total_trades_arr, winning_trades_arr, losing_trades_arr, max_drawdown_arr