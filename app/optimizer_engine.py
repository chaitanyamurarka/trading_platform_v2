# app/optimizer_engine.py
import pandas as pd
import itertools
import uuid
from datetime import datetime,timezone
from typing import Dict, Any, List, Type, Optional, Tuple # Added Tuple
import time
import numpy as np
import json # Added for cache key generation
import hashlib # Added for potential cache key hashing (optional)

from fastapi import BackgroundTasks # Ensure this is imported

from .config import logger
from . import models # Assuming models.py is in the same directory or correctly pathed
from .strategies.base_strategy import BaseStrategy
# from .strategies.ema_crossover_strategy import EMACrossoverStrategy # Not directly used here, but strategy_class is BaseStrategy
from .numba_kernels import run_ema_crossover_optimization_numba # If used

# In-memory stores for job status and results
_optimization_jobs: Dict[str, models.OptimizationJobStatus] = {}
_optimization_results: Dict[str, List[models.OptimizationResultEntry]] = {}
_optimization_cache: Dict[str, List[models.OptimizationResultEntry]] = {} # Added cache storage

# Helper function to create a canonical representation of parameter ranges for cache key
def _canonical_parameter_ranges_for_cache(parameter_ranges: List[models.OptimizationParameterRange]) -> List[Dict[str, Any]]:
    if not parameter_ranges:
        return []
    # Sort by name to ensure order doesn't affect the key, and convert to dicts
    # Ensure values are consistently typed for JSON serialization (e.g., float for numeric)
    processed_ranges = []
    for p_range in parameter_ranges:
        p_dict = p_range.model_dump()
        try:
            p_dict['start_value'] = float(p_dict['start_value'])
            p_dict['end_value'] = float(p_dict['end_value'])
            p_dict['step'] = float(p_dict['step']) if p_dict['step'] is not None else 1.0
        except (ValueError, TypeError):
            # If conversion fails, use original string representation for these specific fields
            # This might happen if strategy allows non-numeric parameters directly as strings
            pass # Keep original values if they are not meant to be numeric
        processed_ranges.append(p_dict)

    sorted_ranges = sorted(processed_ranges, key=lambda p: p['name'])
    return sorted_ranges

def _generate_cache_key(request: models.OptimizationRequest) -> str:
    """Generates a unique cache key for an OptimizationRequest."""
    canonical_ranges = _canonical_parameter_ranges_for_cache(request.parameter_ranges)

    key_data = {
        "exchange": request.exchange,
        "token": request.token,
        "start_date": request.start_date.isoformat() if request.start_date else None,
        "end_date": request.end_date.isoformat() if request.end_date else None,
        "timeframe": request.timeframe,
        "strategy_id": request.strategy_id,
        "parameter_ranges": canonical_ranges,
        "initial_capital": float(request.initial_capital) if request.initial_capital is not None else None,
        "execution_price_type": request.execution_price_type
    }
    # Serialize to a canonical JSON string
    key_string = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
    
    # Using the string itself as key for simplicity in in-memory cache.
    # For external/persistent caches, hashing (e.g., SHA256) is recommended.
    # return hashlib.sha256(key_string.encode('utf-8')).hexdigest()
    return key_string


def _generate_parameter_combinations(
    parameter_ranges: List[models.OptimizationParameterRange],
    strategy_class: Type[BaseStrategy] # Added for fetching defaults
) -> List[Dict[str, Any]]:
    if not parameter_ranges:
        # If no ranges, try to use strategy defaults (if any)
        if strategy_class:
            strategy_info = strategy_class.get_info()
            default_params = {p.name: p.default for p in strategy_info.parameters if p.default is not None}
            if default_params:
                logger.info(f"No parameter ranges provided for optimization, using strategy defaults: {default_params}")
                return [default_params]
        logger.info("No parameter ranges and no strategy defaults found, returning empty combination.")
        return [{}] # Return one empty dict to signify one run with defaults or no params

    param_values_list = []
    param_names = []

    for p_range in parameter_ranges:
        param_names.append(p_range.name)
        current_values = []
        # Ensure start, end, step are numeric if possible
        try:
            p_start = float(p_range.start_value)
            p_end = float(p_range.end_value)
            p_step = float(p_range.step) if p_range.step is not None else 1.0 # Default step to 1 if not provided for numeric
        except (ValueError, TypeError):
            logger.warning(f"Parameter {p_range.name} has non-numeric range values. Using start_value as the only option: {p_range.start_value}")
            # If values are not meant to be numeric (e.g. string choices), p_range.start_value might be a list
            # or we treat it as a single choice. For this function's logic, we'll assume it's a single choice if not numeric here.
            if isinstance(p_range.start_value, list): # Handle if start_value itself is a list of choices
                 current_values = p_range.start_value
            else:
                 current_values = [p_range.start_value]
            param_values_list.append(current_values)
            continue


        is_int_range = all(isinstance(x, (int, float)) and float(x) == int(x) for x in [p_start, p_end, p_step] if x is not None)


        if is_int_range and p_step != 0:
            p_step_int = int(p_step)
            # Ensure step direction matches range direction
            if p_start > p_end and p_step_int > 0: p_step_int = -p_step_int
            if p_start < p_end and p_step_int < 0: p_step_int = abs(p_step_int)

            if p_step_int > 0:
                current_values = list(range(int(p_start), int(p_end) + 1, p_step_int))
            elif p_step_int < 0:
                current_values = list(range(int(p_start), int(p_end) - 1, p_step_int))
            else: # step is 0
                 current_values = [int(p_start)]

            if not current_values and p_start == p_end : current_values = [int(p_start)]
            
            if p_step_int < 0 and int(p_end) <= p_start:
                temp_vals = []
                val = int(p_start)
                while val >= int(p_end):
                    temp_vals.append(val)
                    val += p_step_int
                # Ensure unique and correctly ordered if range function missed some
                current_values = sorted(list(set(current_values + temp_vals)), reverse=True)


        elif p_step != 0: # Float range
            if p_start > p_end and p_step > 0: p_step = -p_step
            if p_start < p_end and p_step < 0: p_step = abs(p_step)

            val = p_start
            # Using np.arange for float steps can be more robust for precision
            # However, be cautious with inclusivity of the end point.
            # A common way is to iterate and check condition
            epsilon = abs(p_step * 0.001) if p_step !=0 else 1e-9 # Epsilon relative to step size

            if p_step > 0: # Increasing
                while val <= p_end + epsilon: # Add epsilon to include p_end in typical float scenarios
                    current_values.append(round(val, 8)) # Round to manage float precision issues
                    val += p_step
            elif p_step < 0: # Decreasing
                while val >= p_end - epsilon: # Subtract epsilon
                    current_values.append(round(val, 8))
                    val += p_step
            else: # step is 0
                current_values = [round(p_start, 8)]
        else: # p_step is 0
            current_values = [round(p_start, 8)]

        if not current_values and abs(p_start - p_end) < 1e-9 : # Handle case where start == end
            current_values = [round(p_start, 8)]
        
        # Fallback to p_start if current_values is empty for some reason (should be rare with above logic)
        param_values_list.append(current_values if current_values else [float(p_start) if isinstance(p_start, (int,float)) else p_start])


    if not param_values_list: return [{}]

    combinations_tuples = list(itertools.product(*param_values_list))
    combinations_dicts = [dict(zip(param_names, combo)) for combo in combinations_tuples]

    valid_combinations = []
    if strategy_class and strategy_class.strategy_id == "ema_crossover":
        for combo in combinations_dicts:
            fast_param_name = next((p_name for p_name in ['fast_ema_period', 'fast_ma_length'] if p_name in combo), None)
            slow_param_name = next((p_name for p_name in ['slow_ema_period', 'slow_ma_length'] if p_name in combo), None)

            if fast_param_name and slow_param_name:
                try:
                    if float(combo[fast_param_name]) < float(combo[slow_param_name]):
                        valid_combinations.append(combo)
                except ValueError:
                    valid_combinations.append(combo) # Should not happen if params are numeric
            else:
                valid_combinations.append(combo)
    else:
        valid_combinations = combinations_dicts

    logger.info(f"Generated {len(valid_combinations)} valid parameter combinations for '{strategy_class.strategy_id if strategy_class else 'Unknown Strategy'}'.")
    return valid_combinations if valid_combinations else [{}]


async def _execute_optimization_task(
    job_id: str,
    request: models.OptimizationRequest, # Pass the original request
    historical_data_points: List[models.OHLCDataPoint],
    strategy_class: Type[BaseStrategy],
    parameter_combinations: List[Dict[str, Any]]
):
    job_status_obj = _optimization_jobs.get(job_id)
    if not job_status_obj:
        logger.error(f"Optimization job {job_id} not found at start of task.")
        return
    if job_status_obj.status == "CANCELLED":
        logger.info(f"Optimization job {job_id} was cancelled before starting execution.")
        return

    job_status_obj.status = "RUNNING"
    job_status_obj.start_time = datetime.utcnow()
    job_status_obj.progress = 0.0
    job_status_obj.current_iteration = 0
    logger.info(f"Opt. job {job_id} for '{strategy_class.strategy_id}', {len(parameter_combinations)} combos. Status: RUNNING")

    if not historical_data_points:
        job_status_obj.status = "FAILED"; job_status_obj.message = "No historical data."; job_status_obj.end_time = datetime.utcnow(); return
    if not parameter_combinations or (len(parameter_combinations) == 1 and not parameter_combinations[0]): # Check if combinations list is effectively empty
        job_status_obj.status = "FAILED"; job_status_obj.message = "No parameter combinations generated (e.g., all were invalid or ranges were empty)."; job_status_obj.end_time = datetime.utcnow(); return

    use_numba_kernel = strategy_class.strategy_id == "ema_crossover"
    if use_numba_kernel:
        first_combo = parameter_combinations[0]
        required_numba_params = ['fast_ema_period', 'slow_ema_period', 'stop_loss_pct', 'take_profit_pct']
        param_name_map = {'fast_ma_length': 'fast_ema_period', 'slow_ma_length': 'slow_ema_period'}
        strategy_info_defaults = {p.name: p.default for p in strategy_class.get_info().parameters}
        mapped_combinations = []
        for combo in parameter_combinations:
            mapped_combo = {}
            all_params_found = True
            for req_param in required_numba_params:
                val = combo.get(req_param)
                if val is None:
                    for ui_name, internal_name in param_name_map.items():
                        if internal_name == req_param and ui_name in combo:
                            val = combo[ui_name]; break
                if val is None: val = strategy_info_defaults.get(req_param)
                if val is None:
                    logger.error(f"Numba kernel for {strategy_class.strategy_id} requires '{req_param}' in combo {combo} or defaults.")
                    use_numba_kernel = False; all_params_found = False; break
                mapped_combo[req_param] = val
            if not all_params_found: break
            mapped_combinations.append(mapped_combo)
        if use_numba_kernel:
            parameter_combinations = mapped_combinations
            logger.info(f"Parameters mapped for Numba kernel for job {job_id}.")

    if use_numba_kernel:
        logger.info(f"Using Numba-accelerated optimization for job {job_id}")
        try:
            ohlc_dicts_for_df_numba = [{'time': datetime.fromtimestamp(item.time) if isinstance(item.time, int) else item.time,
                                        'open': item.open, 'high': item.high, 'low': item.low, 'close': item.close, 'volume': item.volume}
                                       for item in historical_data_points]
            ohlc_df_numba = pd.DataFrame(ohlc_dicts_for_df_numba)
            ohlc_df_numba['time'] = pd.to_datetime(ohlc_df_numba['time'])
            ohlc_df_numba = ohlc_df_numba.set_index('time').sort_index()
            if ohlc_df_numba.empty: raise ValueError("OHLC DataFrame is empty for Numba.")

            open_p = ohlc_df_numba['open'].to_numpy(dtype=np.float64)
            high_p = ohlc_df_numba['high'].to_numpy(dtype=np.float64)
            low_p = ohlc_df_numba['low'].to_numpy(dtype=np.float64)
            close_p = ohlc_df_numba['close'].to_numpy(dtype=np.float64)
            n_candles = len(ohlc_df_numba)
            n_combinations = len(parameter_combinations)

            fast_emas = np.array([c['fast_ema_period'] for c in parameter_combinations], dtype=np.int64)
            slow_emas = np.array([c['slow_ema_period'] for c in parameter_combinations], dtype=np.int64)
            stop_losses = np.array([float(c.get('stop_loss_pct', 0.0)) / 100.0 for c in parameter_combinations], dtype=np.float64)
            take_profits = np.array([float(c.get('take_profit_pct', 0.0)) / 100.0 for c in parameter_combinations], dtype=np.float64)
            exec_price_type_int = 1 if request.execution_price_type == "open" else 0
            execution_price_types = np.full(n_combinations, exec_price_type_int, dtype=np.int64)

            start_run_time = time.time()
            (
                final_pnl_arr, total_trades_arr, winning_trades_arr, 
                losing_trades_arr, max_drawdown_arr,
                _equity_curve_k0, _fast_ema_k0, _slow_ema_k0,
                _trade_entry_idx_k0, _trade_exit_idx_k0,
                _trade_entry_px_k0, _trade_exit_px_k0,
                _trade_types_k0, _trade_pnls_k0, _actual_trade_count_k0
            ) = run_ema_crossover_optimization_numba(
                open_p, high_p, low_p, close_p, fast_emas, slow_emas, stop_losses, take_profits,
                execution_price_types, request.initial_capital, n_combinations, n_candles
            )
            total_run_time = time.time() - start_run_time
            logger.info(f"Numba kernel for job {job_id} completed in {total_run_time:.2f}s.")

            job_results_list: List[models.OptimizationResultEntry] = []
            for k in range(n_combinations):
                if _optimization_jobs[job_id].status == "CANCELLED":
                    logger.info(f"Optimization job {job_id} cancelled during Numba result processing.")
                    return
                params_for_this_run = parameter_combinations[k] 
                original_params_for_result = {} 

                perf_metrics = {
                    "net_pnl": round(float(final_pnl_arr[k]), 2), "total_trades": int(total_trades_arr[k]),
                    "winning_trades": int(winning_trades_arr[k]), "losing_trades": int(losing_trades_arr[k]),
                    "win_rate": round((float(winning_trades_arr[k]) / float(total_trades_arr[k]) * 100.0) if total_trades_arr[k] > 0 else 0.0, 2),
                    "max_drawdown_pct": round(float(max_drawdown_arr[k]) * 100.0, 2),
                    "final_equity": round(request.initial_capital + float(final_pnl_arr[k]), 2)
                }
                job_results_list.append(models.OptimizationResultEntry(parameters=params_for_this_run, performance_metrics=perf_metrics))
                job_status_obj.current_iteration = k + 1
                job_status_obj.progress = (k + 1) / n_combinations

            _optimization_results[job_id] = job_results_list
            job_status_obj.status = "COMPLETED"
            job_status_obj.progress = 1.0
            job_status_obj.message = f"Numba optimization completed: {len(job_results_list)} results in {total_run_time:.2f}s."
        except Exception as e:
            logger.error(f"Error during Numba optimization for job {job_id}: {e}", exc_info=True)
            job_status_obj.status = "FAILED"; job_status_obj.message = f"Numba execution error: {str(e)}"; job_status_obj.end_time = datetime.utcnow(); return
    else:
        logger.info(f"Using iterative Python backtests for job {job_id} (Strategy: {strategy_class.strategy_id})")
        all_results: List[models.OptimizationResultEntry] = []
        total_combinations = len(parameter_combinations)
        for i, params_combo in enumerate(parameter_combinations):
            if _optimization_jobs[job_id].status == "CANCELLED":
                logger.info(f"Optimization job {job_id} cancelled at iteration {i}.")
                return
            job_status_obj.current_iteration = i + 1
            job_status_obj.progress = (i + 1) / total_combinations
            perf_metrics_iter = {"net_pnl": 0, "total_trades": 0, "winning_trades": 0, "losing_trades":0, "max_drawdown_pct": 0, "final_equity": request.initial_capital, "status": "placeholder_python_backtest"}
            if strategy_class.strategy_id != "ema_crossover":
                logger.warning(f"Job {job_id}: Iterative Python backtest executed for combo {i+1}. Performance calculation placeholder used.")
            all_results.append(models.OptimizationResultEntry(parameters=params_combo, performance_metrics=perf_metrics_iter))
        _optimization_results[job_id] = all_results
        job_status_obj.status = "COMPLETED"
        job_status_obj.progress = 1.0
        job_status_obj.message = f"Iterative Python optimization completed: {len(all_results)} results (using placeholders)."


    job_status_obj.end_time = datetime.utcnow()
    
    duration_message = ""
    if hasattr(job_status_obj, 'start_time') and job_status_obj.start_time:
        duration = job_status_obj.end_time - job_status_obj.start_time
        duration_message = f"Total optimization task duration: {duration}."
    else:
        duration_message = "Total optimization task duration: N/A (task did not reach running phase or start_time was not recorded)."

    if job_status_obj.status == "COMPLETED":
        logger.info(f"Optimization job {job_id} finished successfully. {duration_message} Results stored: {len(_optimization_results.get(job_id, []))}. Original message: {job_status_obj.message}")
        
        cache_key = _generate_cache_key(request) 
        _optimization_cache[cache_key] = _optimization_results[job_id]
        logger.info(f"Optimization results for job {job_id} (key: {cache_key}) stored in cache.")
    
    elif job_status_obj.status == "FAILED":
        logger.error(f"Optimization job {job_id} finished with status: FAILED. {duration_message} Message: {job_status_obj.message}")
    
    elif job_status_obj.status == "CANCELLED":
        logger.info(f"Optimization job {job_id} was CANCELLED. {duration_message} Message: {job_status_obj.message if job_status_obj.message else 'Cancellation processed.'}")
    
    else: 
        logger.info(f"Optimization job {job_id} finished with status: {job_status_obj.status}. {duration_message} Message: {job_status_obj.message if job_status_obj.message else 'Status details not set.'}")


# Helper function to estimate memory 
def _estimate_optimization_memory(
    historical_data_points: List[models.OHLCDataPoint],
    parameter_combinations: List[Dict[str, Any]],
    strategy_class: Type[BaseStrategy],
    initial_capital: float,
    request: models.OptimizationRequest 
) -> Dict[str, float]:
    """Estimates memory usage for the optimization task in MB."""
    mem_estimates_mb = {}
    bytes_to_mb = 1 / (1024 * 1024)
    float64_size = 8  # bytes
    int64_size = 8    # bytes
    MAX_TRADES_FOR_DETAILED_OUTPUT = 2000 # from numba_kernels.py

    num_data_points = len(historical_data_points)
    approx_ohlc_object_size_bytes = 150 
    list_of_objects_mem_bytes = num_data_points * approx_ohlc_object_size_bytes
    mem_estimates_mb['historical_data_python_list_approx_mb'] = list_of_objects_mem_bytes * bytes_to_mb

    if num_data_points > 0:
        temp_df_data = []
        for p in historical_data_points:
            # item_dict = p.model_dump() # Not needed if accessing attributes directly
            time_val = p.time
            if isinstance(p.time, int): # Ensure time is datetime
                time_val = datetime.fromtimestamp(p.time, tz=timezone.utc)
            # Construct dict for DataFrame to ensure all expected columns are present for estimation
            item_dict_for_df = {
                'time': time_val, 
                'open': p.open, 'high': p.high, 'low': p.low, 'close': p.close, 
                'volume': p.volume if hasattr(p, 'volume') else 0.0, # Handle if volume is optional
                'oi': p.oi if hasattr(p, 'oi') and p.oi is not None else 0.0 # Handle if oi is optional or None
            }
            temp_df_data.append(item_dict_for_df)
        
        if temp_df_data:
            temp_df = pd.DataFrame(temp_df_data)
            if not temp_df.empty:
                temp_df['time'] = pd.to_datetime(temp_df['time'], errors='coerce')
                try: # Attempt to set index, skip if problematic (e.g. all times are NaT)
                    if not temp_df['time'].isnull().all(): # Only set index if time column is usable
                         temp_df = temp_df.set_index('time')
                except Exception as e_idx: 
                    logger.debug(f"Could not set 'time' as index during memory estimation: {e_idx}")
                    pass 
                
                # Ensure numeric conversion for relevant columns
                for col in ['open', 'high', 'low', 'close', 'volume', 'oi']:
                    if col not in temp_df.columns: temp_df[col] = 0.0 # Add if missing, with default
                    temp_df[col] = pd.to_numeric(temp_df[col], errors='coerce')
                
                df_mem_bytes = temp_df.memory_usage(deep=True).sum()
                mem_estimates_mb['historical_data_pandas_df_mb'] = df_mem_bytes * bytes_to_mb
            else:
                mem_estimates_mb['historical_data_pandas_df_mb'] = 0.0
        else:
            mem_estimates_mb['historical_data_pandas_df_mb'] = 0.0
    else:
        mem_estimates_mb['historical_data_pandas_df_mb'] = 0.0

    n_combinations_val = 0
    if parameter_combinations:
        if len(parameter_combinations) == 1 and not parameter_combinations[0]: # Handles [{}] case
            n_combinations_val = 1
        elif not parameter_combinations: # Handles [] case
             n_combinations_val = 0
        else:
            n_combinations_val = len(parameter_combinations)
    
    n_candles_val = num_data_points

    if strategy_class.strategy_id == "ema_crossover":
        numba_arrays_mem_bytes = 0
        # Input OHLC NumPy arrays (open_p, high_p, low_p, close_p)
        numba_arrays_mem_bytes += 4 * n_candles_val * float64_size
        # Parameter arrays
        numba_arrays_mem_bytes += 3 * n_combinations_val * int64_size # fast_ema_periods, slow_ema_periods, execution_price_types
        numba_arrays_mem_bytes += 2 * n_combinations_val * float64_size # stop_loss_pcts, take_profit_pcts
        # Internal state arrays in Numba kernel
        numba_arrays_mem_bytes += 12 * n_combinations_val * float64_size # cash_arr, ..., max_drawdown_arr
        numba_arrays_mem_bytes += 4 * n_combinations_val * int64_size # position_arr, total_trades_arr, ...
        numba_arrays_mem_bytes += 2 * n_combinations_val * float64_size # k_fast_arr, k_slow_arr
        
        mem_estimates_mb['numba_kernel_arrays_mb'] = numba_arrays_mem_bytes * bytes_to_mb
        mem_estimates_mb['total_estimated_for_numba_path_approx_mb'] = (
            mem_estimates_mb.get('historical_data_pandas_df_mb', 0.0) +
            mem_estimates_mb.get('numba_kernel_arrays_mb', 0.0) +
            mem_estimates_mb.get('historical_data_python_list_approx_mb',0.0)
        )
    else: 
        mem_estimates_mb['total_estimated_for_python_path_approx_mb'] = (
             mem_estimates_mb.get('historical_data_pandas_df_mb', 0.0) +
             mem_estimates_mb.get('historical_data_python_list_approx_mb', 0.0)
        )
        mem_estimates_mb['python_path_note'] = "Strategy/Portfolio objects not deeply estimated."

    # Results storage estimation
    avg_result_entry_size_bytes = 350 # Rough estimate per OptimizationResultEntry
    results_storage_mem_bytes = n_combinations_val * avg_result_entry_size_bytes
    mem_estimates_mb['optimization_results_storage_for_this_job_approx_mb'] = results_storage_mem_bytes * bytes_to_mb
    
    return mem_estimates_mb


async def start_optimization_job(
    request: models.OptimizationRequest,
    strategy_class: Type[BaseStrategy],
    historical_data_points: List[models.OHLCDataPoint],
    background_tasks: BackgroundTasks
) -> models.OptimizationJobStatus:
    job_id = str(uuid.uuid4()) 

    cache_key = _generate_cache_key(request)
    if cache_key in _optimization_cache:
        cached_results = _optimization_cache[cache_key]
        logger.info(f"Cache hit for optimization request (key: {cache_key}). Serving job {job_id} from cache.")
        _optimization_results[job_id] = cached_results
        
        parameter_combinations_for_status = _generate_parameter_combinations(request.parameter_ranges, strategy_class)
        if not parameter_combinations_for_status or \
           (len(parameter_combinations_for_status) == 1 and not parameter_combinations_for_status[0]):
            num_combinations_for_status = 0 
        else:
            num_combinations_for_status = len(parameter_combinations_for_status)

        job_status = models.OptimizationJobStatus(
            job_id=job_id, status="COMPLETED", 
            message=f"Optimization results retrieved from cache. Processed {num_combinations_for_status} combinations.",
            start_time=datetime.utcnow(), end_time=datetime.utcnow(), progress=1.0,
            current_iteration=num_combinations_for_status, total_iterations=num_combinations_for_status,
        )
        _optimization_jobs[job_id] = job_status
        return job_status

    parameter_combinations = _generate_parameter_combinations(request.parameter_ranges, strategy_class)
    
    # --- MEMORY ESTIMATION AND LOGGING ---
    try:
        # Ensure initial_capital is float for estimation function
        initial_cap_for_est = 0.0
        if request.initial_capital is not None:
            try:
                initial_cap_for_est = float(request.initial_capital)
            except ValueError:
                logger.warning(f"Could not convert initial_capital '{request.initial_capital}' to float for memory estimation. Using 0.0.")
        
        estimated_memory_mb = _estimate_optimization_memory(
            historical_data_points,
            parameter_combinations,
            strategy_class,
            initial_cap_for_est,
            request 
        )
        logger.info(f"Estimated memory usage for optimization job {job_id}:")
        for key, value in estimated_memory_mb.items():
            logger.info(f"  {key}: {value:.2f} MB")
        
        total_est_key_numba = 'total_estimated_for_numba_path_approx_mb'
        total_est_key_python = 'total_estimated_for_python_path_approx_mb'

        if strategy_class.strategy_id == "ema_crossover" and total_est_key_numba in estimated_memory_mb:
            total_est = estimated_memory_mb[total_est_key_numba]
            logger.info(f"  ---> Total for Numba Path (approx): {total_est:.2f} MB")
        elif total_est_key_python in estimated_memory_mb :
            total_est = estimated_memory_mb[total_est_key_python]
            logger.info(f"  ---> Total for Python Path (approx): {total_est:.2f} MB")

    except Exception as e:
        logger.error(f"Error during memory estimation for job {job_id}: {e}", exc_info=True)
    # --- END MEMORY ESTIMATION ---


    num_actual_combinations = 0
    if parameter_combinations:
        if len(parameter_combinations) == 1 and not parameter_combinations[0]:
            num_actual_combinations = 1 
        elif not parameter_combinations: # Actual empty list
            num_actual_combinations = 0
        else:
            num_actual_combinations = len(parameter_combinations)

    if num_actual_combinations == 0 : 
         logger.error(f"No valid parameter combinations generated for '{request.strategy_id}' for job {job_id}. Check ranges and strategy defaults.")
         job_status_fail = models.OptimizationJobStatus(
             job_id=job_id, status="FAILED",
             message="No valid parameter combinations to run (e.g., all filtered out or ranges yielded nothing).",
             total_iterations=0
         )
         _optimization_jobs[job_id] = job_status_fail
         return job_status_fail

    job_status = models.OptimizationJobStatus(
        job_id=job_id, status="QUEUED",
        message="Optimization job accepted and queued.",
        total_iterations=num_actual_combinations
    )
    _optimization_jobs[job_id] = job_status
    _optimization_results[job_id] = []

    background_tasks.add_task(
        _execute_optimization_task,
        job_id, request, historical_data_points,
        strategy_class, parameter_combinations
    )

    logger.info(f"Optimization job {job_id} for strategy '{request.strategy_id}' has been queued. Combinations: {num_actual_combinations}")
    return job_status

def get_optimization_job_status(job_id: str) -> Optional[models.OptimizationJobStatus]:
    return _optimization_jobs.get(job_id)

def get_optimization_job_results(job_id: str) -> Optional[List[models.OptimizationResultEntry]]:
    job_status = _optimization_jobs.get(job_id)
    if job_status and job_status.status == "COMPLETED": 
        return _optimization_results.get(job_id)
    if job_status and job_status.status == "CANCELLED" and job_id in _optimization_results:
        logger.info(f"Fetching partial results for cancelled job {job_id}")
        return _optimization_results.get(job_id)
    return None

def cancel_optimization_job(job_id: str) -> Dict[str, str]:
    job_status = _optimization_jobs.get(job_id)
    if not job_status:
        return {"status": "job_not_found", "job_id": job_id, "message": "Job ID not found."}

    if job_status.status in ["COMPLETED", "FAILED", "CANCELLED"]:
        return {"status": f"job_already_{job_status.status.lower()}", "job_id": job_id, "message": f"Job is already {job_status.status}."}

    if job_status.status in ["QUEUED", "RUNNING", "PENDING"]: 
        job_status.status = "CANCELLED"
        job_status.message = "Job cancellation requested by user."
        job_status.end_time = datetime.utcnow()
        logger.info(f"Optimization job {job_id} flagged for cancellation.")
        return {"status": "cancellation_requested", "job_id": job_id, "message": "Cancellation request acknowledged. Task will stop if running."}

    return {"status": "error", "job_id": job_id, "message": f"Cannot cancel job in state: {job_status.status}"}

def run_single_ema_crossover_numba_detailed(
    historical_data_points: List[models.OHLCDataPoint],
    strategy_params: Dict[str, Any],
    initial_capital: float,
    execution_price_type_str: str, 
    ohlc_data_df_index: pd.DatetimeIndex 
) -> Tuple[np.ndarray, ...]: 
    """
    Wrapper to run the Numba kernel for a single EMA Crossover backtest
    with detailed output requested.
    """
    if not historical_data_points:
        raise ValueError("Historical data points list cannot be empty.")

    ohlc_dicts_for_df = []
    for dp in historical_data_points:
        time_val = dp.time
        if isinstance(dp.time, int): 
            time_val = datetime.fromtimestamp(dp.time, tz=timezone.utc)
        
        ohlc_dicts_for_df.append({
            'time': time_val,
            'open': dp.open, 'high': dp.high, 'low': dp.low, 'close': dp.close
        })
    
    df = pd.DataFrame(ohlc_dicts_for_df)
    if df.empty:
        raise ValueError("DataFrame from historical_data_points is empty.")
        
    df['time'] = pd.to_datetime(df['time'])
    df = df.set_index('time').sort_index() 

    open_p = df['open'].to_numpy(dtype=np.float64)
    high_p = df['high'].to_numpy(dtype=np.float64)
    low_p = df['low'].to_numpy(dtype=np.float64)
    close_p = df['close'].to_numpy(dtype=np.float64)
    n_candles = len(df)

    if n_candles == 0:
        raise ValueError("No candles available after processing historical data.")
    
    default_fast_ema = 10 
    default_slow_ema = 20
    default_sl_pct = 0.0
    default_tp_pct = 0.0

    fast_ema_period = int(float(strategy_params.get("fast_ema_period", default_fast_ema)))
    slow_ema_period = int(float(strategy_params.get("slow_ema_period", default_slow_ema)))
    
    stop_loss_pct = float(strategy_params.get("stop_loss_pct", default_sl_pct)) / 100.0
    take_profit_pct = float(strategy_params.get("take_profit_pct", default_tp_pct)) / 100.0

    fast_ema_periods_arr = np.array([fast_ema_period], dtype=np.int64)
    slow_ema_periods_arr = np.array([slow_ema_period], dtype=np.int64)
    stop_loss_pcts_arr = np.array([stop_loss_pct], dtype=np.float64)
    take_profit_pcts_arr = np.array([take_profit_pct], dtype=np.float64)
    
    exec_price_type_int = 1 if execution_price_type_str.lower() == "open" else 0
    execution_price_types_arr = np.array([exec_price_type_int], dtype=np.int64)

    n_combinations = 1

    logger.info(f"Calling Numba kernel for single detailed backtest: FastEMA={fast_ema_period}, SlowEMA={slow_ema_period}, SL={stop_loss_pct*100}%, TP={take_profit_pct*100}%, Exec={execution_price_type_str}")
    
    numba_results_tuple = run_ema_crossover_optimization_numba(
        open_p, high_p, low_p, close_p,
        fast_ema_periods_arr, slow_ema_periods_arr,
        stop_loss_pcts_arr, take_profit_pcts_arr,
        execution_price_types_arr,
        initial_capital,
        n_combinations, 
        n_candles,
        detailed_output_requested=True
    )
    return numba_results_tuple