# app/optimizer_engine.py (Refined for BackgroundTasks)
import pandas as pd
import itertools
import uuid
from datetime import datetime
from typing import Dict, Any, List, Type, Tuple, Optional
import time
import asyncio

from fastapi import BackgroundTasks # Ensure this is imported

from .config import logger
from . import models
from .strategies.base_strategy import BaseStrategy, PortfolioState
from .strategy_engine import calculate_performance_metrics
from .data_module import get_historical_data

_optimization_jobs: Dict[str, models.OptimizationJobStatus] = {}
_optimization_results: Dict[str, List[models.OptimizationResultEntry]] = {}

def _generate_parameter_combinations(
    parameter_ranges: List[models.OptimizationParameterRange]
) -> List[Dict[str, Any]]:
    # ... (same as before, no changes needed here)
    if not parameter_ranges:
        return [{}]

    param_values_list = []
    param_names = []

    for p_range in parameter_ranges:
        param_names.append(p_range.name)
        
        is_int_range = False
        if hasattr(p_range, 'type') and p_range.type == 'int': # Checking for 'type' attribute
            is_int_range = True
        elif isinstance(p_range.start, int) and isinstance(p_range.end, int) and isinstance(p_range.step, int):
            is_int_range = True

        if is_int_range:
            current_values = list(range(int(p_range.start), int(p_range.end) + int(p_range.step), int(p_range.step)))
        else: 
            current_values = []
            val = float(p_range.start)
            step_val = float(p_range.step)
            if step_val <= 0: 
                step_val = 1.0 if p_range.start < p_range.end else (p_range.start - p_range.end)/10.0 or 1.0
            
            if p_range.start == p_range.end : 
                 current_values.append(round(val,8))
            elif p_range.start < p_range.end:
                while val <= float(p_range.end) + 1e-9: 
                    current_values.append(round(val, 8)) 
                    val += step_val
            else: 
                 current_values.append(round(val,8))
        param_values_list.append(current_values)

    if not param_values_list:
        return [{}]

    combinations_tuples = list(itertools.product(*param_values_list))
    combinations_dicts = [dict(zip(param_names, combo)) for combo in combinations_tuples]
    
    logger.info(f"Generated {len(combinations_dicts)} parameter combinations.")
    return combinations_dicts


async def _execute_optimization_task( # This remains an async function
    job_id: str,
    historical_data_points: List[models.OHLCDataPoint],
    strategy_class: Type[BaseStrategy],
    parameter_combinations: List[Dict[str, Any]],
    initial_capital: float = 100000.0
):
    # ... (main logic of _execute_optimization_task remains IDENTICAL to the previous corrected version)
    # This function will be run in a background thread by FastAPI.
    # Ensure all operations within are thread-safe if they modify shared global state
    # beyond _optimization_jobs and _optimization_results for this job_id.
    # Our current _optimization_jobs and _optimization_results are simple dicts,
    # and updates are generally per job_id, so race conditions are less likely for distinct jobs.
    # For shared counters or resources, locks might be needed if not using Celery.

    _optimization_jobs[job_id].status = "RUNNING"
    _optimization_jobs[job_id].start_time = datetime.utcnow()
    logger.info(f"Optimization job {job_id} started for {strategy_class.strategy_id} with {len(parameter_combinations)} combinations.")

    if not historical_data_points:
        logger.error(f"Job {job_id}: No historical data provided.")
        _optimization_jobs[job_id].status = "FAILED"
        _optimization_jobs[job_id].message = "No historical data for optimization."
        _optimization_jobs[job_id].end_time = datetime.utcnow()
        return

    try:
        ohlc_df = pd.DataFrame([item.model_dump() for item in historical_data_points])
        ohlc_df['time'] = pd.to_datetime(ohlc_df['time'])
        ohlc_df = ohlc_df.set_index('time').sort_index()
    except Exception as e:
        logger.error(f"Job {job_id}: Error converting historical data: {e}", exc_info=True)
        _optimization_jobs[job_id].status = "FAILED"
        _optimization_jobs[job_id].message = f"Invalid historical data format: {e}"
        _optimization_jobs[job_id].end_time = datetime.utcnow()
        return

    num_candles = len(ohlc_df)
    if num_candles == 0:
        logger.error(f"Job {job_id}: OHLC DataFrame is empty after processing.")
        _optimization_jobs[job_id].status = "FAILED"
        _optimization_jobs[job_id].message = "No data points in OHLC data for optimization."
        _optimization_jobs[job_id].end_time = datetime.utcnow()
        return

    strategy_instances_and_portfolios: List[Tuple[BaseStrategy, PortfolioState]] = []
    for i, params in enumerate(parameter_combinations):
        portfolio = PortfolioState(initial_capital=initial_capital)
        try:
            # OLD LINE: strategy_instance = strategy_class(data=ohlc_df, params=params, portfolio=portfolio)
            strategy_instance = strategy_class(shared_ohlc_data=ohlc_df, params=params, portfolio=portfolio) # <<<< CORRECTED HERE
            strategy_instances_and_portfolios.append((strategy_instance, portfolio))
            if not ohlc_df.empty:
                portfolio.record_equity(ohlc_df.index[0], ohlc_df.iloc[0]['close'])
        except Exception as e:
            logger.error(f"Job {job_id}, Combo {i} ({params}): Error initializing strategy: {e}", exc_info=True) # Log actual params
            # Mark this specific combination as failed or skip it
            continue # Skip this faulty combination
    
    if not strategy_instances_and_portfolios:
        logger.error(f"Job {job_id}: No strategy instances could be initialized.")
        _optimization_jobs[job_id].status = "FAILED";
        _optimization_jobs[job_id].message = "Failed to initialize any strategy instances."
        _optimization_jobs[job_id].end_time = datetime.utcnow()
        return

    total_combinations_active = len(strategy_instances_and_portfolios)
    if _optimization_jobs.get(job_id):
        _optimization_jobs[job_id].total_combinations = total_combinations_active
    
    start_run_time = time.time()

    for bar_index in range(num_candles):
        current_bar = ohlc_df.iloc[bar_index]
        
        for i, (strategy, portfolio) in enumerate(strategy_instances_and_portfolios):
            try:
                strategy.process_bar(bar_index)
            except Exception as e:
                temp_params_str = str(strategy.params) if hasattr(strategy,'params') else "unknown_params"
                logger.error(f"Job {job_id}, Combo {temp_params_str}, Bar {bar_index}: Error processing bar: {e}", exc_info=True)
            portfolio.record_equity(current_bar.name, current_bar['close'])
        
        if bar_index % (num_candles // 20 + 1) == 0 or bar_index == num_candles - 1 :
            if _optimization_jobs.get(job_id):
                progress = (bar_index + 1) / num_candles
                _optimization_jobs[job_id].progress = round(progress, 4)
                time_elapsed_val = time.time() - start_run_time
                _optimization_jobs[job_id].message = f"Processed {bar_index + 1}/{num_candles} candles. Time elapsed: {time_elapsed_val:.2f}s."
                if progress > 1e-3:
                     estimated_total_time = time_elapsed_val / progress
                     _optimization_jobs[job_id].estimated_remaining_time_seconds = round(estimated_total_time - time_elapsed_val, 2)
                logger.debug(f"Job {job_id}: Progress {progress*100:.2f}%")

    job_results: List[models.OptimizationResultEntry] = []
    for i, (strategy, portfolio) in enumerate(strategy_instances_and_portfolios):
        if portfolio.current_position_qty > 0 and not ohlc_df.empty:
            last_bar_time = ohlc_df.index[-1]
            last_close_price = ohlc_df.iloc[-1]['close']
            portfolio.close_position(last_bar_time, last_close_price)
            portfolio.record_equity(last_bar_time, last_close_price)

        params_for_this_run = strategy.params
        performance_summary = calculate_performance_metrics(portfolio, initial_capital)
        job_results.append(models.OptimizationResultEntry(
            parameters=params_for_this_run,
            performance=performance_summary
        ))

    _optimization_results[job_id] = job_results
    if _optimization_jobs.get(job_id):
        _optimization_jobs[job_id].status = "COMPLETED"
        _optimization_jobs[job_id].progress = 1.0
        _optimization_jobs[job_id].end_time = datetime.utcnow()
        total_run_time_val = time.time() - start_run_time
        _optimization_jobs[job_id].message = f"Optimization completed in {total_run_time_val:.2f}s. Results for {len(job_results)} combinations."
    logger.info(f"Optimization job {job_id} completed. Results: {len(job_results)} entries.")


async def start_optimization_job( # This function signature itself can remain async or become sync
    request: models.OptimizationRequest,
    strategy_class: Type[BaseStrategy],
    historical_data_points: List[models.OHLCDataPoint],
    background_tasks: BackgroundTasks # Key change: using this
) -> models.OptimizationJobStatus:
    job_id = str(uuid.uuid4())
    dataset_length = len(historical_data_points)
    
    adjusted_parameter_ranges = []
    for pr_item in request.parameter_ranges:
        current_pr = pr_item.model_copy(deep=True)
        if hasattr(current_pr, 'name') and "ma" in current_pr.name.lower() and "fast" in current_pr.name.lower(): # Added hasattr check
            max_allowed_len = dataset_length // 3
            if max_allowed_len > 0 and hasattr(current_pr, 'end') and isinstance(current_pr.end, (int, float)) and current_pr.end > max_allowed_len :
                logger.info(f"Capping {current_pr.name} max length from {current_pr.end} to {max_allowed_len} based on dataset length {dataset_length}")
                current_pr.end = max_allowed_len
        adjusted_parameter_ranges.append(current_pr)

    parameter_combinations = _generate_parameter_combinations(adjusted_parameter_ranges)

    if not parameter_combinations:
        # This should ideally be caught by _generate_parameter_combinations if it returns empty for valid reasons
        # or _generate_parameter_combinations should raise an error if ranges are invalid.
        logger.error("No parameter combinations generated. Check parameter ranges.")
        # Return a status indicating failure to generate combinations
        # For simplicity, let's assume _generate_parameter_combinations is robust or this is caught by API validation.
        # If it can genuinely return empty for valid but unproductive ranges, the job should reflect that.
        # For now, we'll proceed and let it potentially fail if _execute_optimization_task expects combinations.
        # Better: handle this by creating a FAILED job status immediately.
        job_status_fail = models.OptimizationJobStatus(
            job_id=job_id, status="FAILED", 
            message="No parameter combinations generated. Please check input ranges.",
            total_combinations=0
        )
        _optimization_jobs[job_id] = job_status_fail
        return job_status_fail


    job_status = models.OptimizationJobStatus(
        job_id=job_id,
        status="QUEUED", # Changed from PENDING to QUEUED
        message="Optimization job accepted and queued for background execution.",
        total_combinations=len(parameter_combinations),
        current_combination_count=0 
    )
    _optimization_jobs[job_id] = job_status
    _optimization_results[job_id] = [] # Initialize results list

    # *** KEY CHANGE: Add the task to background_tasks ***
    background_tasks.add_task(
        _execute_optimization_task, # The function to run
        job_id,                     # Arguments to the function
        historical_data_points,
        strategy_class,
        parameter_combinations
        # initial_capital is already defaulted in _execute_optimization_task
    )
    
    logger.info(f"Optimization job {job_id} has been queued to run in the background.")
    
    return job_status # Return the initial QUEUED status immediately

def get_optimization_job_status(job_id: str) -> Optional[models.OptimizationJobStatus]:
    return _optimization_jobs.get(job_id)

def get_optimization_job_results(job_id: str) -> Optional[List[models.OptimizationResultEntry]]:
    job_status = _optimization_jobs.get(job_id)
    if job_status and job_status.status == "COMPLETED":
        return _optimization_results.get(job_id)
    return None