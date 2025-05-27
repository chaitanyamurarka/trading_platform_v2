# app/optimizer_engine.py
import pandas as pd
import itertools
import uuid
from datetime import datetime
from typing import Dict, Any, List, Type, Tuple, Optional
import time
import numpy as np 

from fastapi import BackgroundTasks

from .config import logger
from . import models
from .strategies.base_strategy import BaseStrategy 
from .strategies.ema_crossover_strategy import EMACrossoverStrategy 
from .data_module import get_historical_data

# Import the Numba kernel
from .numba_kernels import run_ema_crossover_optimization_numba 

_optimization_jobs: Dict[str, models.OptimizationJobStatus] = {}
_optimization_results: Dict[str, List[models.OptimizationResultEntry]] = {}


def _generate_parameter_combinations(
    parameter_ranges: List[models.OptimizationParameterRange],
    strategy_class: Type[BaseStrategy] 
) -> List[Dict[str, Any]]:
    # This function remains largely the same as the robust version from before,
    # including the filtering for fast_ema < slow_ema.
    if not parameter_ranges: 
        if strategy_class:
            strategy_info = strategy_class.get_info()
            default_params = {p.name: p.default for p in strategy_info.parameters if p.default is not None}
            if default_params:
                logger.info(f"No parameter ranges provided, using strategy defaults: {default_params}")
                return [default_params]
        return [{}] 

    param_values_list = []
    param_names = []

    for p_range in parameter_ranges:
        param_names.append(p_range.name)
        current_values = []
        try:
            p_start = float(p_range.start)
            p_end = float(p_range.end)
            p_step = float(p_range.step)
        except (ValueError, TypeError): # Added TypeError for robustness
            logger.warning(f"Invalid non-numeric start/end/step for parameter {p_range.name}. Using single value: {p_range.start}")
            current_values = [p_range.start] 
            param_values_list.append(current_values)
            continue

        # Using type attribute from OptimizationParameterRange if available
        param_type = getattr(p_range, 'type', None)
        if param_type == 'int' or (isinstance(p_start,int) and isinstance(p_end,int) and isinstance(p_step,int) and p_step != 0):
            p_step_int = int(p_step) if p_step != 0 else 1
            if p_start > p_end and p_step_int > 0: p_step_int = -p_step_int # Ensure step direction matches range
            if p_start < p_end and p_step_int < 0: p_step_int = -p_step_int

            # Correct range generation for int
            if p_step_int > 0:
                current_values = list(range(int(p_start), int(p_end) + 1, p_step_int))
            elif p_step_int < 0:
                 current_values = list(range(int(p_start), int(p_end) -1 , p_step_int))
            else: # step is 0, only one value
                current_values = [int(p_start)]
        
        elif param_type == 'float' or isinstance(p_start, float) or isinstance(p_end, float) or isinstance(p_step, float):
            if p_step == 0: # If step is 0 for float, treat as single value
                current_values = [round(p_start, 8)]
            else:
                val = p_start
                # Ensure step direction for floats too
                if p_start > p_end and p_step > 0: p_step = -p_step
                if p_start < p_end and p_step < 0: p_step = -p_step
                
                if p_step > 0 :
                    while val <= p_end + 1e-9: 
                        current_values.append(round(val, 8))
                        val += p_step
                elif p_step < 0:
                     while val >= p_end - 1e-9: # For negative step
                        current_values.append(round(val, 8))
                        val += p_step
                else: # Should be caught by p_step == 0 above
                    current_values = [round(p_start,8)]


        else: 
             logger.warning(f"Parameter {p_range.name} has unrecognized type or step. Using single value: {p_range.start}")
             current_values = [p_range.start]
        
        if not current_values and p_start == p_end : 
            current_values = [p_start]
            
        param_values_list.append(current_values)

    if not param_values_list: return [{}]

    combinations_tuples = list(itertools.product(*param_values_list))
    combinations_dicts = [dict(zip(param_names, combo)) for combo in combinations_tuples]
    
    valid_combinations = []
    for combo in combinations_dicts:
        fast_ema = combo.get('fast_ema_period')
        slow_ema = combo.get('slow_ema_period')
        if fast_ema is not None and slow_ema is not None:
            if fast_ema < slow_ema:
                valid_combinations.append(combo)
            else:
                logger.debug(f"Skipping invalid combo: fast_ema {fast_ema} >= slow_ema {slow_ema}")
        else: 
            valid_combinations.append(combo)

    logger.info(f"Generated {len(valid_combinations)} valid parameter combinations.")
    return valid_combinations if valid_combinations else [{}]


async def _execute_optimization_task(
    job_id: str,
    historical_data_points: List[models.OHLCDataPoint],
    strategy_class: Type[BaseStrategy], 
    parameter_combinations: List[Dict[str, Any]], 
    initial_capital: float,
    # New: Pass the global execution_price_type for the whole optimization run
    execution_price_type_global: str 
):
    job_status_obj = _optimization_jobs[job_id]
    job_status_obj.status = "RUNNING"
    job_status_obj.start_time = datetime.utcnow()
    logger.info(f"Opt. job {job_id} (Numba) for '{strategy_class.strategy_id}', {len(parameter_combinations)} combos.")

    if not historical_data_points:
        job_status_obj.status = "FAILED"; job_status_obj.message = "No data."; job_status_obj.end_time = datetime.utcnow(); return
    if not parameter_combinations or (len(parameter_combinations) == 1 and not parameter_combinations[0]):
        job_status_obj.status = "FAILED"; job_status_obj.message = "No valid param combos."; job_status_obj.end_time = datetime.utcnow(); return

    try:
        ohlc_df = pd.DataFrame([item.model_dump() for item in historical_data_points])
        ohlc_df['time'] = pd.to_datetime(ohlc_df['time'])
        ohlc_df = ohlc_df.set_index('time').sort_index()
        if ohlc_df.empty: raise ValueError("OHLC DataFrame is empty.")
    except Exception as e:
        job_status_obj.status = "FAILED"; job_status_obj.message = f"Data prep error: {e}"; job_status_obj.end_time = datetime.utcnow(); return

    n_candles = len(ohlc_df)
    n_combinations = len(parameter_combinations)
    job_status_obj.total_combinations = n_combinations

    open_p = ohlc_df['open'].to_numpy(dtype=np.float64)
    high_p = ohlc_df['high'].to_numpy(dtype=np.float64)
    low_p = ohlc_df['low'].to_numpy(dtype=np.float64)
    close_p = ohlc_df['close'].to_numpy(dtype=np.float64)

    strategy_info = strategy_class.get_info()
    default_params_map = {p.name: p.default for p in strategy_info.parameters if p.default is not None}

    try:
        fast_ema_periods_arr = np.array([c.get('fast_ema_period', default_params_map.get('fast_ema_period',10)) for c in parameter_combinations], dtype=np.int64)
        slow_ema_periods_arr = np.array([c.get('slow_ema_period', default_params_map.get('slow_ema_period',20)) for c in parameter_combinations], dtype=np.int64)
        stop_loss_pcts_arr = np.array([c.get('stop_loss_pct', default_params_map.get('stop_loss_pct',0.0)) / 100.0 for c in parameter_combinations], dtype=np.float64)
        take_profit_pcts_arr = np.array([c.get('take_profit_pct', default_params_map.get('take_profit_pct',0.0)) / 100.0 for c in parameter_combinations], dtype=np.float64)
        
        # Use the global execution_price_type for all combinations in this Numba run
        execution_price_type_int = 1 if execution_price_type_global == "open" else 0
        execution_price_types_arr = np.full(n_combinations, execution_price_type_int, dtype=np.int64)

    except KeyError as e:
        logger.error(f"Missing param {e} in combos or defaults for Numba kernel.")
        job_status_obj.status = "FAILED"; job_status_obj.message = f"Param setup error: {e}"; job_status_obj.end_time = datetime.utcnow(); return
    except Exception as e: # Catch any other error during array prep
        logger.error(f"Error preparing parameter arrays for Numba: {e}", exc_info=True)
        job_status_obj.status = "FAILED"; job_status_obj.message = f"Parameter array prep error: {e}"; job_status_obj.end_time = datetime.utcnow(); return


    start_run_time = time.time()
    
    try:
        logger.info(f"Calling Numba kernel for job {job_id} with {n_combinations} combinations, {n_candles} candles.")
        final_pnl_arr, total_trades_arr, winning_trades_arr, losing_trades_arr, max_drawdown_arr = run_ema_crossover_optimization_numba(
            open_p, high_p, low_p, close_p,
            fast_ema_periods_arr, slow_ema_periods_arr,
            stop_loss_pcts_arr, take_profit_pcts_arr,
            execution_price_types_arr, 
            initial_capital,
            n_combinations, n_candles
        )
        job_status_obj.progress = 1.0
        job_status_obj.message = "Numba kernel processing completed."

    except Exception as e:
        logger.error(f"Job {job_id}: Error during Numba execution: {e}", exc_info=True)
        job_status_obj.status = "FAILED"; job_status_obj.message = f"Numba error: {str(e)}"; job_status_obj.end_time = datetime.utcnow(); return

    job_results_list: List[models.OptimizationResultEntry] = []
    for k in range(n_combinations):
        params_for_this_run = parameter_combinations[k]
        performance = {
            "net_pnl": round(float(final_pnl_arr[k]), 2),
            "total_trades": int(total_trades_arr[k]),
            "winning_trades": int(winning_trades_arr[k]),
            "losing_trades": int(losing_trades_arr[k]),
            "win_rate": round((float(winning_trades_arr[k]) / float(total_trades_arr[k]) * 100.0) if total_trades_arr[k] > 0 else 0.0, 2),
            "max_drawdown_pct": round(float(max_drawdown_arr[k]) * 100.0, 2), # Numba returns as decimal
            "final_equity": round(initial_capital + float(final_pnl_arr[k]), 2)
        }
        job_results_list.append(models.OptimizationResultEntry(parameters=params_for_this_run, performance=performance))

    _optimization_results[job_id] = job_results_list
    job_status_obj.status = "COMPLETED"
    job_status_obj.end_time = datetime.utcnow()
    total_run_time = time.time() - start_run_time
    job_status_obj.message = f"Optimization (Numba) completed in {total_run_time:.2f}s for {len(job_results_list)} combos."
    logger.info(f"Optimization job {job_id} (Numba) completed. Results: {len(job_results_list)} entries.")


async def start_optimization_job(
    request: models.OptimizationRequest, # This is app.models.OptimizationRequest
    strategy_class: Type[BaseStrategy], 
    historical_data_points: List[models.OHLCDataPoint],
    background_tasks: BackgroundTasks
) -> models.OptimizationJobStatus:
    job_id = str(uuid.uuid4())
    
    dataset_length = len(historical_data_points)
    adjusted_parameter_ranges = []
    for pr_item in request.parameter_ranges:
        current_pr = pr_item.model_copy(deep=True)
        if hasattr(current_pr, 'name') and "ma" in current_pr.name.lower() and "fast" in current_pr.name.lower():
            if dataset_length > 0: # Only cap if dataset_length is positive
                max_allowed_len = dataset_length // 3
                if max_allowed_len > 0 and hasattr(current_pr, 'end') and isinstance(current_pr.end, (int, float)) and current_pr.end > max_allowed_len :
                    logger.info(f"Capping {current_pr.name} max length from {current_pr.end} to {max_allowed_len} based on dataset length {dataset_length}")
                    current_pr.end = max_allowed_len
            elif hasattr(current_pr, 'end'): # No data, or not enough data to apply rule meaningfully
                 logger.warning(f"Cannot apply dataset length rule to cap MA {current_pr.name} as dataset length is {dataset_length}. Using original end: {current_pr.end}")

        adjusted_parameter_ranges.append(current_pr)

    parameter_combinations = _generate_parameter_combinations(adjusted_parameter_ranges, strategy_class)

    if not parameter_combinations or (len(parameter_combinations) == 1 and not parameter_combinations[0]):
        logger.error("No valid parameter combinations generated after filtering. Check ranges and strategy defaults.")
        # Create and return a FAILED job status
        job_status_fail = models.OptimizationJobStatus(
            job_id=job_id, status="FAILED", 
            message="No valid parameter combinations generated (e.g., fast_ema >= slow_ema or empty ranges).",
            total_combinations=0
        )
        _optimization_jobs[job_id] = job_status_fail
        return job_status_fail

    # Extract execution_price_type from the original request if it's there, or default
    # This assumes OptimizationRequest model might be extended to include it,
    # or it's passed in the 'parameters' dict of the request.
    # For now, let's assume it's a general setting for the optimization run.
    # If it's inside request.parameters (which it isn't by default for OptimizationRequest)
    # execution_price_type_global = request.parameters.get("execution_price_type", "close")
    # For now, if we want it configurable PER OPTIMIZATION RUN, it should be part of OptimizationRequest model.
    # Let's assume for now it's not directly in OptimizationRequest, so we use a fixed default or get it from strategy params
    # A cleaner way is to add it to OptimizationRequest model if it's a top-level choice for the whole run.
    # For this implementation, the Numba kernel expects an array, so we'll derive it.
    # We'll assume a default 'close' if not specified by individual combo for now,
    # but the Numba kernel is built to take an array.
    # The `_execute_optimization_task` now expects execution_price_type_global
    # We need to decide where this comes from. Let's make it a parameter of OptimizationRequest in models.py.
    
    # For now, I'll hardcode it in the call to _execute_optimization_task
    # This needs to be made configurable via OptimizationRequest model
    execution_price_type_for_run = getattr(request, "execution_price_type", "close") # If added to model
    # If not in model, and you want it fixed: execution_price_type_for_run = "close"


    job_status = models.OptimizationJobStatus(
        job_id=job_id, status="QUEUED",
        message="Optimization job accepted and queued for Numba execution.",
        total_combinations=len(parameter_combinations)
    )
    _optimization_jobs[job_id] = job_status
    _optimization_results[job_id] = [] 

    initial_capital_for_run = 100000.0 # Default
    # Check if initial_capital is specified in any of the parameter sets or as a general request field
    # For simplicity, assuming a fixed initial capital for now or passed in another way.
    # The Numba kernel takes it as a scalar.


    background_tasks.add_task(
        _execute_optimization_task,
        job_id, historical_data_points,
        strategy_class, 
        parameter_combinations,
        initial_capital_for_run, # Pass initial capital
        execution_price_type_for_run # Pass global execution type for this run
    )
    
    logger.info(f"Optimization job {job_id} has been queued (Numba path).")
    return job_status

def get_optimization_job_status(job_id: str) -> Optional[models.OptimizationJobStatus]:
    # Ensure _optimization_jobs is accessible here (it's a global dict in the module)
    return _optimization_jobs.get(job_id)

def get_optimization_job_results(job_id: str) -> Optional[List[models.OptimizationResultEntry]]:
    # Ensure _optimization_jobs and _optimization_results are accessible
    job_status = _optimization_jobs.get(job_id)
    if job_status and job_status.status == "COMPLETED":
        return _optimization_results.get(job_id)
    return None
# ... (get_optimization_job_status, get_optimization_job_results as before) ...