# app/main.py (Updated)
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks # Added BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Dict, Type
import io # For CSV download
import csv # For CSV generation
from datetime import date

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
@app.on_event("startup")
async def startup_event():
    logger.info("Application startup...")
    logger.info(f"Default symbol: {settings.DEFAULT_SYMBOL} ({settings.DEFAULT_TOKEN})")
    logger.info(f"Registered strategies: {list(STRATEGY_REGISTRY.keys())}")
    try:
        data_module.load_scripmaster("NSE")
        logger.info("Initial API client access attempted and default scripmaster loaded (if available).")
    except ConnectionError as e:
        logger.error(f"Failed to connect to Shoonya API on startup: {e}")
    except FileNotFoundError as e:
        logger.warning(f"Scripmaster file not found on startup: {e}")
    except ValueError as e:
        logger.error(f"Configuration or Scripmaster error on startup: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred on startup: {e}", exc_info=True)

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

@app.post("/data/historical", response_model=models.HistoricalDataResponse)
async def fetch_historical_data_api(request: models.HistoricalDataRequest):
    try:
        get_shoonya_api_client()
        response = await data_module.fetch_and_store_historical_data(request)
        if not response.data and response.message == "No data found for the given parameters.":
             pass
        elif not response.data:
             raise HTTPException(status_code=404, detail="No data found for the specified parameters, or an API error occurred.")
        return response
    except ConnectionError as e:
        logger.error(f"API Connection Error fetching historical data: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"API Connection Error: {str(e)}")
    except ValueError as e:
        logger.error(f"Validation or Configuration Error fetching historical data: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Validation or Configuration Error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error fetching historical data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected server error occurred.")

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
@app.post("/optimize/start", response_model=models.OptimizationJobStatus)
async def start_optimization_api(
    request: models.OptimizationRequest,
    background_tasks: BackgroundTasks 
):
    logger.info(f"Received optimization request for strategy_id: '{request.strategy_id}'") # Added log
    logger.info(f"Current STRATEGY_REGISTRY keys for optimization: {list(STRATEGY_REGISTRY.keys())}") # Added log

    strategy_class = STRATEGY_REGISTRY.get(request.strategy_id)
    if not strategy_class:
        logger.error(f"Strategy ID '{request.strategy_id}' not found for optimization. Available: {list(STRATEGY_REGISTRY.keys())}")
        raise HTTPException(status_code=404, detail=f"Strategy ID '{request.strategy_id}' not found.")


    # Fetch historical data for optimization
    data_req = models.HistoricalDataRequest(
        exchange=request.exchange, token=request.token,
        start_time=request.start_date, end_time=request.end_date,
        interval=request.timeframe
    )
    try:
        get_shoonya_api_client() # Ensure logged in
        historical_data_response = await data_module.fetch_and_store_historical_data(data_req)
        if not historical_data_response.data:
            logger.warning(f"No historical data found for optimization: {data_req.model_dump()}")
            raise HTTPException(status_code=404, detail="No historical data found for optimization.")
        ohlc_data_points = historical_data_response.data
    except Exception as e: # Simplified error handling
        logger.error(f"Error fetching data for optimization: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching data for optimization: {str(e)}")

    try:
        # This will now run the optimization task.
        # If _execute_optimization_task in optimizer_engine uses background_tasks.add_task,
        # this endpoint will return quickly. Otherwise, it blocks.
        # For now, optimizer_engine.start_optimization_job calls it synchronously but is async.
        # We'll pass background_tasks to it, so it *can* use it if modified.
        job_status = await optimizer_engine.start_optimization_job(
            request=request,
            strategy_class=strategy_class,
            historical_data_points=ohlc_data_points,
            background_tasks=background_tasks # Pass it down
        )
        return job_status
    except ValueError as e: # E.g., no parameter combinations
        logger.error(f"ValueError starting optimization: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error starting optimization: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start optimization job.")


@app.get("/optimize/status/{job_id}", response_model=models.OptimizationJobStatus)
async def get_optimization_status_api(job_id: str):
    """
    Retrieves the status of an optimization job.
    """
    status = optimizer_engine.get_optimization_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Optimization job ID '{job_id}' not found.")
    return status


@app.get("/optimize/results/{job_id}", response_model=models.OptimizationResultsResponse)
async def get_optimization_results_api(job_id: str):
    """
    Retrieves the results of a completed optimization job.
    """
    status = optimizer_engine.get_optimization_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Optimization job ID '{job_id}' not found.")
    if status.status != "COMPLETED":
        raise HTTPException(status_code=400, detail=f"Optimization job '{job_id}' is not yet completed. Status: {status.status}")

    results = optimizer_engine.get_optimization_job_results(job_id)
    if results is None: # Should ideally not happen if status is COMPLETED
        raise HTTPException(status_code=404, detail=f"Results for job ID '{job_id}' not found, though job is marked COMPLETED.")
        
    return models.OptimizationResultsResponse(
        job_id=job_id,
        strategy_id=status.message.split("for ")[1].split(" ")[0] if "for" in status.message else "unknown", # Attempt to parse from message
        results=results,
        total_combinations_tested=len(results)
    )

@app.get("/optimize/results/{job_id}/download")
async def download_optimization_results_api(job_id: str):
    """
    Downloads the results of a completed optimization job as a CSV file.
    """
    status = optimizer_engine.get_optimization_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Optimization job ID '{job_id}' not found.")
    if status.status != "COMPLETED":
        raise HTTPException(status_code=400, detail=f"Job '{job_id}' not complete. Status: {status.status}")

    results = optimizer_engine.get_optimization_job_results(job_id)
    if not results:
        raise HTTPException(status_code=404, detail=f"No results found for job '{job_id}'.")

    output = io.StringIO()
    if not results: # Should be caught above, but as a safeguard
        writer = csv.writer(output)
        writer.writerow(["Message"])
        writer.writerow(["No results available."])
    else:
        # Dynamically create headers
        # First entry's parameters keys + performance keys
        first_result = results[0]
        param_headers = list(first_result.parameters.keys())
        perf_headers = list(first_result.performance.keys())
        headers = param_headers + perf_headers
        
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        for entry in results:
            row_data = {}
            row_data.update(entry.parameters)
            row_data.update(entry.performance)
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