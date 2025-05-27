# app/main.py (Updated)
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks # Added BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Dict, Type, Optional # Added Optional
import io # For CSV download
import csv # For CSV generation
from datetime import date
import uuid # For job IDs if needed outside optimizer_engine

from .config import settings, logger
from .auth import get_shoonya_api_client
from . import models
from . import data_module
from . import strategy_engine
from . import optimizer_engine # Import the optimizer engine
from .strategies.base_strategy import BaseStrategy
from .strategies.ema_crossover_strategy import EMACrossoverStrategy

app = FastAPI(title="Trading System V2", version="0.1.0")

# --- Strategy Registry ---
# Use explicit string literals for keys for robustness
STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {
    "ema_crossover": EMACrossoverStrategy,
    # Add other strategies here using their string ID as the key:
    # "another_strategy_id": AnotherStrategyClass,
}

# --- In-memory store for original optimization requests ---
# This was missing its definition.
# In a production system, consider a more persistent store (e.g., Redis, database)
# if the server might restart or run with multiple workers.
_optimization_requests_store: Dict[str, models.OptimizationRequest] = {}

@app.on_event("startup")
async def startup_event():
    logger.info("Application startup...")
    logger.info(f"Default symbol: {settings.DEFAULT_SYMBOL} ({settings.DEFAULT_TOKEN})")
    logger.info(f"Registered strategies: {list(STRATEGY_REGISTRY.keys())}")
    try:
        # Trigger Shoonya login attempt and load default scripmaster on startup
        # This also initializes the ShoonyaAPI client instance.
        api_client = get_shoonya_api_client() # Ensures login attempt
        if api_client: # Check if client was successfully initialized
             data_module.load_scripmaster(settings.DEFAULT_EXCHANGE) # Load default scripmaster
        logger.info("Initial API client access attempted and default scripmaster loaded (if available).")
    except Exception as e:
        logger.error(f"Error during startup (API client or Scripmaster load): {e}", exc_info=True)

@app.get("/")
async def read_root():
    return {"message": f"Welcome to Trading System V2. Default Symbol: {settings.DEFAULT_SYMBOL}"}

@app.get("/health", response_model=models.HealthResponse)
async def health_check():
    shoonya_status = "login_attempt_required_or_success"
    try:
        get_shoonya_api_client()
        shoonya_status = "login_successful_or_pending"
        return models.HealthResponse(status="healthy", shoonya_api_status=shoonya_status)
    except ConnectionError as e:
        logger.error(f"Health check: Shoonya API connection error - {e}")
        return models.HealthResponse(status="unhealthy", shoonya_api_status=f"connection_error: {e}")
    except ValueError as e:
        logger.error(f"Health check: Configuration error - {e}")
        return models.HealthResponse(status="unhealthy", shoonya_api_status=f"configuration_error: {e}")

@app.get("/symbols/{exchange}", response_model=models.AvailableSymbolsResponse)
async def list_available_symbols(exchange: str):
    try:
        response = await data_module.get_available_symbols(exchange.upper())
        return response
    except FileNotFoundError:
        logger.warning(f"Scripmaster not found for exchange: {exchange.upper()}")
        raise HTTPException(status_code=404, detail=f"Scripmaster for exchange '{exchange.upper()}' not found.")
    except Exception as e:
        logger.error(f"Error listing symbols for {exchange.upper()}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not retrieve symbols for exchange '{exchange.upper()}'.")

@app.post("/data/historical", response_model=models.HistoricalDataResponse, tags=["Data"])
async def fetch_historical_data_api(request: models.HistoricalDataRequest):
    try:
        logger.info(f"Received request for historical data: {request.exchange}:{request.token}")
        historical_data_response = await data_module.fetch_and_store_historical_data(request)
        # data_module now correctly handles the message for no data, returning a 200 OK response.
        return historical_data_response
    except FileNotFoundError as e:
        logger.error(f"File not found error in historical data endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e: 
        logger.error(f"Value error in historical data endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in /data/historical endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred: {str(e)}")

@app.post("/backtest/run", response_model=models.BacktestResult)
async def run_backtest_api(request: models.BacktestRequest):
    logger.info(f"Received backtest request for strategy_id: '{request.strategy_id}'") # Added log
    logger.info(f"Current STRATEGY_REGISTRY keys: {list(STRATEGY_REGISTRY.keys())}") # Added log

    strategy_class = STRATEGY_REGISTRY.get(request.strategy_id)
    if not strategy_class:
        logger.error(f"Strategy ID '{request.strategy_id}' not found in registry. Available: {list(STRATEGY_REGISTRY.keys())}")
        raise HTTPException(status_code=404, detail=f"Strategy ID '{request.strategy_id}' not found.")

    data_req = models.HistoricalDataRequest(
        exchange=request.exchange, token=request.token,
        start_time=request.start_date, end_time=request.end_date,
        interval=request.timeframe
    )
    try:
        get_shoonya_api_client()
        historical_data_response = await data_module.fetch_and_store_historical_data(data_req)
        if not historical_data_response.data:
            logger.warning(f"No historical data found for backtest: {data_req.model_dump()}")
            raise HTTPException(status_code=404, detail="No historical data found for the backtest parameters.")
        ohlc_data_points = historical_data_response.data
    except Exception as e: # Simplified error handling for brevity, specific exceptions handled above
        logger.error(f"Error fetching data for backtest: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching data for backtest: {str(e)}")

    try:
        initial_capital = request.parameters.pop("initial_capital", 100000.0)
        backtest_result = await strategy_engine.run_single_backtest(
            historical_data_points=ohlc_data_points, strategy_class=strategy_class,
            strategy_params=request.parameters, backtest_request_details=request,
            initial_capital=initial_capital
        )
        return backtest_result
    except ValueError as e:
        logger.error(f"ValueError during backtest execution: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during backtest execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred during backtest execution.")

@app.get("/strategies/available", response_model=models.AvailableStrategiesResponse)
async def list_available_strategies():
    available_strategies = []
    for strategy_id, strategy_class in STRATEGY_REGISTRY.items():
        try:
            info = strategy_class.get_info()
            available_strategies.append(info)
        except Exception as e:
            logger.error(f"Error getting info for strategy {strategy_id}: {e}", exc_info=True)
    return models.AvailableStrategiesResponse(strategies=available_strategies)

# --- Optimization Endpoints ---
@app.post("/optimize/start", response_model=models.OptimizationJobStatus, tags=["Optimization"])
async def start_optimization_api(
    optimization_request: models.OptimizationRequest, # This is the Pydantic model from app.models
    background_tasks: BackgroundTasks
):
    logger.info(f"Received optimization request for strategy_id: '{optimization_request.strategy_id}'")
    strategy_class = STRATEGY_REGISTRY.get(optimization_request.strategy_id)
    logger.info(f"Current STRATEGY_REGISTRY keys for optimization: {list(STRATEGY_REGISTRY.keys())}")

    if not strategy_class:
        logger.error(f"Strategy ID '{optimization_request.strategy_id}' not found in registry during optimization start.")
        raise HTTPException(status_code=404, detail=f"Strategy '{optimization_request.strategy_id}' not found.")

    try:
        # Fetch data first
        data_req = models.HistoricalDataRequest(
            exchange=optimization_request.exchange,
            token=optimization_request.token,
            start_time=optimization_request.start_date,
            end_time=optimization_request.end_date,
            interval=optimization_request.timeframe
        )
        logger.info(f"Fetching data for optimization: {data_req.exchange}:{data_req.token} from {data_req.start_time} to {data_req.end_time} interval {data_req.interval}")
        
        historical_data_response = await data_module.fetch_and_store_historical_data(request=data_req)
        ohlc_data_points = historical_data_response.data

        if not ohlc_data_points:
            logger.error(f"No historical data for optimization: {data_req}. Message: {historical_data_response.message}")
            # Return a custom response or raise an error that results in a client-friendly message
            # For consistency, we could simulate a job status FAILED or just raise 400
            raise HTTPException(status_code=400, detail=f"No historical data available for the optimization parameters. {historical_data_response.message}")

        logger.info(f"Data fetched for optimization. Count: {len(ohlc_data_points)}. Starting optimization job task...")
        
        # Start the optimization job
        job_status = await optimizer_engine.start_optimization_job(
            request=optimization_request,
            strategy_class=strategy_class,
            historical_data_points=ohlc_data_points,
            background_tasks=background_tasks
        )
        
        # Store the original request associated with this job_id
        if job_status and job_status.job_id and job_status.status != "FAILED": # Only store if job created successfully
            _optimization_requests_store[job_status.job_id] = optimization_request
            logger.info(f"Optimization job {job_status.job_id} successfully queued. Storing original request.")
        
        return job_status
        
    except HTTPException: # Re-raise HTTPExceptions from data fetching or other validation
        raise
    except Exception as e:
        logger.error(f"Unexpected error starting optimization for strategy '{optimization_request.strategy_id}': {e}", exc_info=True)
        # Construct a FAILED job status to return to the client
        # This might be more informative than a generic 500 if the job object itself cannot be created.
        # However, if job creation itself fails catastrophically, a 500 might be appropriate.
        # For now, let's try to return a FAILED job status if possible.
        temp_job_id = str(uuid.uuid4()) # Placeholder if job object creation fails before ID is set
        # Fallback for unhandled errors during job submission phase
        return models.OptimizationJobStatus(
            job_id=temp_job_id, 
            status="FAILED",
            message=f"Failed to start optimization job due to an internal error: {str(e)}",
            progress=0.0,
            total_iterations=0
        )


@app.get("/optimize/status/{job_id}", response_model=Optional[models.OptimizationJobStatus], tags=["Optimization"])
async def get_optimization_status_api(job_id: str):
    logger.debug(f"Request for optimization status for job ID: {job_id}")
    status = optimizer_engine.get_optimization_job_status(job_id)
    if not status:
        logger.warning(f"Optimization job ID '{job_id}' not found for status check.")
        raise HTTPException(status_code=404, detail=f"Optimization job ID '{job_id}' not found.")
    return status


@app.get("/optimize/results/{job_id}", response_model=models.OptimizationResultsResponse, tags=["Optimization"])
async def get_optimization_results_api(job_id: str):
    logger.debug(f"Request for optimization results for job ID: {job_id}")
    status = optimizer_engine.get_optimization_job_status(job_id) # Check status first
    if not status:
        raise HTTPException(status_code=404, detail=f"Optimization job ID '{job_id}' not found.")
    
    if status.status != "COMPLETED":
        raise HTTPException(status_code=400, detail=f"Optimization job '{job_id}' is not yet completed. Current status: {status.status}")

    results = optimizer_engine.get_optimization_job_results(job_id)
    if results is None: # Should be caught by status check, but as a safeguard
        raise HTTPException(status_code=404, detail=f"Results for job ID '{job_id}' not found, though job is marked COMPLETED.")

    # Retrieve the original request for 'request_details'
    original_request = _optimization_requests_store.get(job_id)
    if not original_request:
        logger.error(f"Original request details for job ID '{job_id}' not found in store. Cannot build full OptimizationResultsResponse.")
        # Fallback or raise error. For now, raising an error.
        # This indicates a server-side state management issue.
        raise HTTPException(status_code=500, detail=f"Internal error: Original request details for job '{job_id}' are missing.")

    # Find best result (example: max net_pnl)
    best_result_entry: Optional[models.OptimizationResultEntry] = None
    if results:
        # Ensure metric_to_optimize is valid and present in performance_metrics
        metric_key = original_request.metric_to_optimize
        try:
            best_result_entry = max(results, key=lambda r: r.performance_metrics.get(metric_key, float('-inf')) if isinstance(r.performance_metrics.get(metric_key), (int,float)) else float('-inf'))
        except (TypeError, ValueError) as e: # Handle cases where metric might not be comparable or present
            logger.warning(f"Could not determine best result for job {job_id} using metric '{metric_key}': {e}")


    return models.OptimizationResultsResponse(
        job_id=job_id,
        strategy_id=original_request.strategy_id, # From stored request
        request_details=original_request,          # CORRECTED: Populate this field
        results=results,
        best_result=best_result_entry,
        summary_stats={"total_combinations_run": len(results)}, # Example summary
        total_combinations_tested=len(results) # Matches model field name
    )


@app.get("/optimize/results/{job_id}/download", tags=["Optimization"])
async def download_optimization_results_api(job_id: str):
    logger.debug(f"Request to download optimization results for job ID: {job_id}")
    results = optimizer_engine.get_optimization_job_results(job_id) # This already checks for COMPLETED status implicitly via optimizer_engine logic.
    
    job_status = optimizer_engine.get_optimization_job_status(job_id)
    if not job_status:
        raise HTTPException(status_code=404, detail=f"Optimization job ID '{job_id}' not found.")
    if job_status.status != "COMPLETED":
         raise HTTPException(status_code=400, detail=f"Optimization job '{job_id}' is not yet completed. Current status: {job_status.status}")
    if not results: # If job completed but no results (e.g., no valid combos run)
        raise HTTPException(status_code=404, detail=f"No results found for completed job '{job_id}'.")

    output = io.StringIO()
    if not results: 
        writer = csv.writer(output)
        writer.writerow(["Message"])
        writer.writerow(["No results available."])
    else:
        first_result = results[0]
        param_headers = list(first_result.parameters.keys())
        # CORRECTED: Use performance_metrics
        perf_headers = list(first_result.performance_metrics.keys()) 
        headers = param_headers + perf_headers
        
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        for entry in results:
            row_data = {}
            row_data.update(entry.parameters)
            # CORRECTED: Use performance_metrics
            row_data.update(entry.performance_metrics) 
            writer.writerow(row_data)

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=optimization_results_{job_id}.csv"}
    )

if __name__ == "__main__":
    import uvicorn
    # Note: For BackgroundTasks to work reliably across multiple workers if using uvicorn --workers > 1,
    # the "job store" (_optimization_jobs, _optimization_results) would need to be external (Redis, DB).
    # For development with one worker, in-memory is fine.
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)