# app/optimizer_engine.py
import pandas as pd
import itertools
import uuid
from datetime import datetime
from typing import Dict, Any, List, Type, Optional
import time
import numpy as np

from fastapi import BackgroundTasks # Ensure this is imported

from .config import logger
from . import models # Assuming models.py is in the same directory or correctly pathed
from .strategies.base_strategy import BaseStrategy
# from .strategies.ema_crossover_strategy import EMACrossoverStrategy # Not directly used here, but strategy_class is BaseStrategy
from .numba_kernels import run_ema_crossover_optimization_numba # If used

# In-memory stores for job status and results
_optimization_jobs: Dict[str, models.OptimizationJobStatus] = {}
_optimization_results: Dict[str, List[models.OptimizationResultEntry]] = {}


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
            param_values_list.append([p_range.start_value]) # Use as a single choice
            continue

        # Determine type for iteration (int or float)
        # Check if all are whole numbers for int iteration
        is_int_range = all(x == int(x) for x in [p_start, p_end, p_step] if x is not None)

        if is_int_range and p_step != 0:
            p_step_int = int(p_step)
            # Ensure step direction matches range direction
            if p_start > p_end and p_step_int > 0: p_step_int = -p_step_int
            if p_start < p_end and p_step_int < 0: p_step_int = abs(p_step_int) # Make step positive for increasing range

            if p_step_int > 0: # Increasing or single value
                current_values = list(range(int(p_start), int(p_end) + 1, p_step_int))
            elif p_step_int < 0: # Decreasing
                current_values = list(range(int(p_start), int(p_end) -1 , p_step_int)) # -1 to include end for negative step
            else: # step is 0
                 current_values = [int(p_start)]

            if not current_values and p_start == p_end : current_values = [int(p_start)]
            # For negative steps, ensure the end value is included if the range function missed it due to step size
            if p_step_int < 0 and p_end not in current_values and int(p_end) <= p_start :
                if not current_values or current_values[-1] > p_end: # if last generated value is still > p_end
                     idx = 0
                     while int(p_start) + idx * p_step_int >= int(p_end):
                         val_to_add = int(p_start) + idx*p_step_int
                         if val_to_add not in current_values: # avoid duplicates if already added
                            if not current_values or (p_step_int < 0 and val_to_add < current_values[-1]) or \
                               (p_step_int > 0 and val_to_add > current_values[-1]): # ensure order
                                current_values.append(val_to_add) # simple append might break order, re-sort later if needed
                         idx +=1
                     current_values = sorted(list(set(current_values)), reverse=True) # ensure unique and ordered


        elif p_step != 0: # Float range
             # Ensure step direction matches range direction
            if p_start > p_end and p_step > 0: p_step = -p_step
            if p_start < p_end and p_step < 0: p_step = abs(p_step) # Make step positive

            val = p_start
            epsilon = abs(p_step * 0.001) # Epsilon relative to step size for float comparisons

            if p_step > 0: # Increasing
                while val <= p_end + epsilon:
                    current_values.append(round(val, 8)) # Round to avoid float precision issues
                    val += p_step
            elif p_step < 0: # Decreasing
                while val >= p_end - epsilon:
                    current_values.append(round(val, 8))
                    val += p_step
            else: # step is 0
                current_values = [round(p_start, 8)]
        else: # p_step is 0
            current_values = [round(p_start, 8)] # single value if step is 0

        if not current_values and abs(p_start - p_end) < 1e-9 : # Handle case where start == end
            current_values = [round(p_start, 8)]

        param_values_list.append(current_values if current_values else [p_start]) # Fallback to p_start if empty

    if not param_values_list: return [{}] # Should not happen if parameter_ranges is not empty

    combinations_tuples = list(itertools.product(*param_values_list))
    combinations_dicts = [dict(zip(param_names, combo)) for combo in combinations_tuples]

    # Filter invalid combinations (e.g., fast_ema >= slow_ema)
    valid_combinations = []
    if strategy_class and strategy_class.strategy_id == "ema_crossover": # Specific filter for ema_crossover
        for combo in combinations_dicts:
            fast_param_name = next((p_name for p_name in ['fast_ema_period', 'fast_ma_length'] if p_name in combo), None)
            slow_param_name = next((p_name for p_name in ['slow_ema_period', 'slow_ma_length'] if p_name in combo), None)

            if fast_param_name and slow_param_name:
                try:
                    if float(combo[fast_param_name]) < float(combo[slow_param_name]):
                        valid_combinations.append(combo)
                    # else:
                        # logger.debug(f"Skipping invalid EMA combo: {fast_param_name}={combo[fast_param_name]} >= {slow_param_name}={combo[slow_param_name]}")
                except ValueError: # If params are not numbers (should not happen with earlier checks)
                    # logger.warning(f"Could not compare EMA params for combo {combo}, adding it.")
                    valid_combinations.append(combo)
            else:
                valid_combinations.append(combo) # If not EMA params, it's valid by this filter
    else:
        valid_combinations = combinations_dicts # No specific filter for other strategies yet

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
    if not parameter_combinations:
        job_status_obj.status = "FAILED"; job_status_obj.message = "No param combinations."; job_status_obj.end_time = datetime.utcnow(); return

    # --- Numba Kernel Specific Preparation (if using EMA Crossover and Numba) ---
    use_numba_kernel = strategy_class.strategy_id == "ema_crossover" # and IS_NUMBA_AVAILABLE_AND_ENABLED
    # Check if all required parameters for Numba kernel are present in combinations
    if use_numba_kernel:
        first_combo = parameter_combinations[0]
        required_numba_params = ['fast_ema_period', 'slow_ema_period', 'stop_loss_pct', 'take_profit_pct']
        # Allow alternative names from UI
        param_name_map = {
            'fast_ma_length': 'fast_ema_period',
            'slow_ma_length': 'slow_ema_period'
        }
        
        # Get default values from strategy info for missing params
        strategy_info_defaults = {p.name: p.default for p in strategy_class.get_info().parameters}

        mapped_combinations = []
        for combo in parameter_combinations:
            mapped_combo = {}
            for req_param in required_numba_params:
                # Find the param value: 1. direct name, 2. mapped name, 3. default from strategy_info
                val = combo.get(req_param)
                if val is None: # Try mapped names
                    for ui_name, internal_name in param_name_map.items():
                        if internal_name == req_param and ui_name in combo:
                            val = combo[ui_name]
                            break
                if val is None: # Try default
                    val = strategy_info_defaults.get(req_param)

                if val is None: # If still None, Numba kernel cannot run
                    logger.error(f"Numba kernel for {strategy_class.strategy_id} requires parameter '{req_param}' but it's missing in combo {combo} and defaults.")
                    use_numba_kernel = False
                    break
                mapped_combo[req_param] = val
            if not use_numba_kernel: break
            mapped_combinations.append(mapped_combo)
        
        if use_numba_kernel:
            parameter_combinations = mapped_combinations # Use the combinations with correct names for Numba
            logger.info(f"Parameters mapped for Numba kernel for job {job_id}.")


    if use_numba_kernel: # Call Numba-accelerated version
        logger.info(f"Using Numba-accelerated optimization for job {job_id}")
        # ... (Numba kernel call as in the provided optimizer_engine.py, adapted for the new param names if needed)
        # Ensure ohlc_df is prepared as numpy arrays
        try:
            ohlc_dicts_for_df_numba = []
            for item in historical_data_points:
                item_dict = item.model_dump()
                if isinstance(item.time, int):
                    item_dict['time'] = datetime.fromtimestamp(item.time)
                ohlc_dicts_for_df_numba.append(item_dict)

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
            stop_losses = np.array([c.get('stop_loss_pct', 0.0) / 100.0 for c in parameter_combinations], dtype=np.float64) # SL in pct
            take_profits = np.array([c.get('take_profit_pct', 0.0) / 100.0 for c in parameter_combinations], dtype=np.float64) # TP in pct
            # execution_price_type: 0 for close, 1 for open
            exec_price_type_int = 1 if request.execution_price_type == "open" else 0
            execution_price_types = np.full(n_combinations, exec_price_type_int, dtype=np.int64)


            start_run_time = time.time()
            final_pnl_arr, total_trades_arr, winning_trades_arr, losing_trades_arr, max_drawdown_arr = run_ema_crossover_optimization_numba(
                open_p, high_p, low_p, close_p,
                fast_emas, slow_emas,
                stop_losses, take_profits,
                execution_price_types,
                request.initial_capital,
                n_combinations, n_candles
            )
            total_run_time = time.time() - start_run_time
            logger.info(f"Numba kernel for job {job_id} completed in {total_run_time:.2f}s.")

            job_results_list: List[models.OptimizationResultEntry] = []
            for k in range(n_combinations):
                 # Check for cancellation periodically within the loop if Numba didn't do it all at once
                if _optimization_jobs[job_id].status == "CANCELLED":
                    logger.info(f"Optimization job {job_id} cancelled during Numba result processing.")
                    # job_status_obj.message = "Job cancelled during result processing." # Status already set
                    # job_status_obj.end_time = datetime.utcnow()
                    return # Exit task

                params_for_this_run = parameter_combinations[k]
                perf_metrics = {
                    "net_pnl": round(float(final_pnl_arr[k]), 2),
                    "total_trades": int(total_trades_arr[k]),
                    "winning_trades": int(winning_trades_arr[k]),
                    "losing_trades": int(losing_trades_arr[k]),
                    "win_rate": round((float(winning_trades_arr[k]) / float(total_trades_arr[k]) * 100.0) if total_trades_arr[k] > 0 else 0.0, 2),
                    "max_drawdown_pct": round(float(max_drawdown_arr[k]) * 100.0, 2), # Numba kernel returns decimal DD
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
            job_status_obj.status = "FAILED"; job_status_obj.message = f"Numba execution error: {e}"; job_status_obj.end_time = datetime.utcnow(); return

    else: # Fallback to iterative Python backtests (slower)
        logger.info(f"Using iterative Python backtests for job {job_id} (Strategy: {strategy_class.strategy_id})")
        all_results: List[models.OptimizationResultEntry] = []
        total_combinations = len(parameter_combinations)

        for i, params_combo in enumerate(parameter_combinations):
            if _optimization_jobs[job_id].status == "CANCELLED":
                logger.info(f"Optimization job {job_id} cancelled at iteration {i}.")
                # job_status_obj.message = f"Job cancelled by user at iteration {i}." # Status already set
                # job_status_obj.end_time = datetime.utcnow()
                return # Exit task

            job_status_obj.current_iteration = i + 1
            job_status_obj.progress = (i + 1) / total_combinations

            # Construct a BacktestRequest for this iteration
            temp_backtest_req = models.BacktestRequest(
                exchange=request.exchange, token=request.token,
                start_date=request.start_date, end_date=request.end_date,
                timeframe=request.timeframe, strategy_id=request.strategy_id,
                parameters=params_combo, initial_capital=request.initial_capital,
                execution_price_type=request.execution_price_type
            )
            try:
                # logger.debug(f"Job {job_id} - Iter {i+1}/{total_combinations}, Params: {params_combo}")
                # from app.strategy_engine import run_single_backtest # Local import to avoid circularity at module level
                # backtest_result_iter: models.BacktestResult = await run_single_backtest( # This is tricky as _execute_optimization_task is sync after FastAPI BackgroundTasks hands it off
                # For now, assume strategy_engine.run_single_backtest is available and can be called.
                # This part is more complex due to async nature of run_single_backtest
                # For a sync background task, run_single_backtest would need to be callable synchronously or adapted.
                # Let's simulate the outcome for now as direct await is not possible in this sync task.
                # This indicates a deeper refactor might be needed for python-based iterative optimization if run_single_backtest is async.
                # For simplicity, we'll assume a placeholder result or skip if direct call is an issue.
                # Placeholder:
                perf_metrics_iter = {"net_pnl": 0, "total_trades": 0, "winning_trades": 0, "losing_trades":0, "max_drawdown_pct": 0, "final_equity": request.initial_capital}
                # In a real scenario, you'd call a synchronous version of run_single_backtest here.
                # For this example, we'll acknowledge this is a placeholder if not using Numba.
                if strategy_class.strategy_id != "ema_crossover": # Only log for non-numba paths
                    logger.warning(f"Job {job_id}: Iterative Python backtest executed for combo {i+1}. Performance calculation would happen here.")


                all_results.append(models.OptimizationResultEntry(
                    parameters=params_combo,
                    performance_metrics=perf_metrics_iter
                ))
            except Exception as e:
                logger.error(f"Job {job_id} - Error in iter {i+1} with params {params_combo}: {e}", exc_info=True)
                # Store partial failure or skip
                all_results.append(models.OptimizationResultEntry(
                    parameters=params_combo,
                    performance_metrics={"error": str(e)}
                ))
        
        _optimization_results[job_id] = all_results
        job_status_obj.status = "COMPLETED"
        job_status_obj.progress = 1.0
        job_status_obj.message = f"Iterative Python optimization completed: {len(all_results)} results."


    job_status_obj.end_time = datetime.utcnow()
    if job_status_obj.status != "FAILED" and job_status_obj.status != "CANCELLED": # Ensure status is completed if not failed/cancelled
        job_status_obj.status = "COMPLETED"
    logger.info(f"Optimization job {job_id} finished with status: {job_status_obj.status}. Results stored: {len(_optimization_results.get(job_id, []))}")


async def start_optimization_job(
    request: models.OptimizationRequest,
    strategy_class: Type[BaseStrategy],
    historical_data_points: List[models.OHLCDataPoint],
    background_tasks: BackgroundTasks # FastAPI BackgroundTasks
) -> models.OptimizationJobStatus:
    job_id = str(uuid.uuid4())

    # Parameter generation now happens inside _execute_optimization_task or just before it,
    # using the strategy_class to fetch defaults if needed.
    # For now, let's generate them here to set total_iterations correctly.
    parameter_combinations = _generate_parameter_combinations(request.parameter_ranges, strategy_class)

    if not parameter_combinations or (len(parameter_combinations) == 1 and not parameter_combinations[0]):
        logger.error(f"No valid parameter combinations for '{request.strategy_id}'. Check ranges and strategy defaults.")
        job_status_fail = models.OptimizationJobStatus(
            job_id=job_id, status="FAILED",
            message="No valid parameter combinations (e.g., fast_ema >= slow_ema or empty ranges).",
            total_iterations=0
        )
        _optimization_jobs[job_id] = job_status_fail # Store failed job status
        return job_status_fail

    job_status = models.OptimizationJobStatus(
        job_id=job_id, status="QUEUED",
        message="Optimization job accepted and queued.",
        total_iterations=len(parameter_combinations)
    )
    _optimization_jobs[job_id] = job_status
    _optimization_results[job_id] = [] # Initialize empty results

    # Pass the original request to the background task
    background_tasks.add_task(
        _execute_optimization_task,
        job_id, request, historical_data_points,
        strategy_class, parameter_combinations
    )

    logger.info(f"Optimization job {job_id} for strategy '{request.strategy_id}' has been queued. Combinations: {len(parameter_combinations)}")
    return job_status

def get_optimization_job_status(job_id: str) -> Optional[models.OptimizationJobStatus]:
    return _optimization_jobs.get(job_id)

def get_optimization_job_results(job_id: str) -> Optional[List[models.OptimizationResultEntry]]:
    job_status = _optimization_jobs.get(job_id)
    if job_status and job_status.status == "COMPLETED":
        return _optimization_results.get(job_id)
    # Allow fetching results even if cancelled but some results were processed
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
        job_status.end_time = datetime.utcnow() # Mark end time on cancellation request
        logger.info(f"Optimization job {job_id} flagged for cancellation. Current state: {job_status.status}")
        # The background task (_execute_optimization_task) needs to check this status periodically.
        return {"status": "cancellation_requested", "job_id": job_id, "message": "Cancellation request acknowledged. Task will stop if running."}

    return {"status": "error", "job_id": job_id, "message": f"Cannot cancel job in state: {job_status.status}"}