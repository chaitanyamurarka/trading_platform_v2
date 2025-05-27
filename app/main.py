# app/main.py
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse # Added JSONResponse
from typing import List, Dict, Type, Optional 
import io
import csv
from datetime import date, datetime # Added datetime
import uuid
import pandas as pd

from .config import settings, logger
from .auth import get_shoonya_api_client # Assuming this remains for other parts
from . import models
from . import data_module
from . import strategy_engine
from . import optimizer_engine
from .strategies.base_strategy import BaseStrategy
from .strategies.ema_crossover_strategy import EMACrossoverStrategy
# Potentially more strategy imports if you have them

app = FastAPI(title="Trading System V2", version="0.1.0")

# Strategy Registry
STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {
    "ema_crossover": EMACrossoverStrategy,
    # Add other strategies here
}

_optimization_requests_store: Dict[str, models.OptimizationRequest] = {}


@app.on_event("startup")
async def startup_event():
    logger.info("Application startup...")
    # ... (rest of startup logic remains the same)
    logger.info(f"Default symbol: {settings.DEFAULT_SYMBOL} ({settings.DEFAULT_TOKEN})")
    logger.info(f"Registered strategies: {list(STRATEGY_REGISTRY.keys())}")
    try:
        api_client = get_shoonya_api_client() 
        if api_client: 
             data_module.load_scripmaster(settings.DEFAULT_EXCHANGE) 
        logger.info("Initial API client access attempted and default scripmaster loaded (if available).")
    except Exception as e:
        logger.error(f"Error during startup (API client or Scripmaster load): {e}", exc_info=True)


@app.get("/")
async def read_root():
    return {"message": f"Welcome to Trading System V2. Default Symbol: {settings.DEFAULT_SYMBOL}"}

@app.get("/health", response_model=models.HealthResponse)
async def health_check():
    # ... (health check logic remains the same)
    shoonya_status = "login_attempt_required_or_success" # Default optimistic status
    try:
        get_shoonya_api_client() # This will attempt login if not already done
        shoonya_status = "login_successful_or_pending" # If no exception, login was attempted or is okay
        # You might want a more definitive status from get_shoonya_api_client if it returns one
        return models.HealthResponse(status="healthy", shoonya_api_status=shoonya_status)
    except ConnectionError as e: # Specific error for Shoonya connection problems
        logger.error(f"Health check: Shoonya API connection error - {e}")
        # shoonya_api_status should reflect this specific error
        return models.HealthResponse(status="unhealthy", shoonya_api_status=f"connection_error: {e}")
    except ValueError as e: # E.g., config errors from Shoonya client init
        logger.error(f"Health check: Configuration error - {e}")
        return models.HealthResponse(status="unhealthy", shoonya_api_status=f"configuration_error: {e}")
    except Exception as e: # Catch any other unexpected errors during API client access
        logger.error(f"Health check: Unexpected error with Shoonya API - {e}", exc_info=True)
        return models.HealthResponse(status="unhealthy", shoonya_api_status=f"unexpected_error: {e}")


@app.get("/symbols/{exchange}", response_model=models.AvailableSymbolsResponse)
async def list_available_symbols(exchange: str):
    # ... (symbol listing logic remains the same)
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
    # ... (historical data fetching logic remains the same, but now returns OHLCDataPoint with datetime)
    try:
        logger.info(f"Received request for historical data: {request.exchange}:{request.token}")
        historical_data_response = await data_module.fetch_and_store_historical_data(request)
        return historical_data_response
    except FileNotFoundError as e: # data_module might raise this if local cache file not found and API fails
        logger.error(f"File not found error in historical data endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e: # For validation errors like invalid token, date format from data_module
        logger.error(f"Value error in historical data endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=str(e)) # 422 Unprocessable Entity
    except ConnectionError as e: # If Shoonya API connection fails
        logger.error(f"Connection error in historical data endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to data provider. {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in /data/historical endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred: {str(e)}")


@app.post("/backtest/run", response_model=models.BacktestResult, tags=["Backtesting"]) # Added tag
async def run_backtest_api(request: models.BacktestRequest):
    logger.info(f"Received backtest request for strategy_id: '{request.strategy_id}'")
    strategy_class = STRATEGY_REGISTRY.get(request.strategy_id)
    if not strategy_class:
        logger.error(f"Strategy ID '{request.strategy_id}' not found. Available: {list(STRATEGY_REGISTRY.keys())}")
        raise HTTPException(status_code=404, detail=f"Strategy ID '{request.strategy_id}' not found.")

    # Prepare HistoricalDataRequest for data fetching
    # The timeframe in BacktestRequest should match HistoricalDataRequest interval format
    data_req = models.HistoricalDataRequest(
        exchange=request.exchange, token=request.token,
        start_time=request.start_date, end_time=request.end_date,
        interval=request.timeframe # Ensure this timeframe is valid for data_module
    )
    try:
        # Fetch data using data_module (which handles Shoonya interaction)
        api_client = get_shoonya_api_client() # Ensures API client is ready
        if not api_client:
             raise ConnectionError("Shoonya API client not available for backtest data.")
        historical_data_container = await data_module.fetch_and_store_historical_data(data_req) # This is HistoricalDataResponse
        
        if not historical_data_container.data:
            logger.warning(f"No historical data for backtest: {data_req.model_dump_json()}. Message: {historical_data_container.message}")
            # It's better to raise an error that translates to a 404 or 400 for the client
            raise HTTPException(status_code=404, detail=f"No historical data found for the backtest parameters. {historical_data_container.message or ''}")
        
        ohlc_data_points_for_backtest = historical_data_container.data # List[OHLCDataPoint]
        logger.info(f"Fetched {len(ohlc_data_points_for_backtest)} data points for backtest.")

    except HTTPException: # Re-raise HTTPExceptions (like the 404 above)
        raise
    except ConnectionError as e:
        logger.error(f"Connection error fetching data for backtest: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Could not connect to data provider for backtest: {str(e)}")
    except Exception as e:
        logger.error(f"Error fetching data for backtest: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching data for backtest: {str(e)}")

    # Run the backtest using strategy_engine
    try:
        # initial_capital is part of BacktestRequest model with a default
        # strategy_params are also part of BacktestRequest
        backtest_result = await strategy_engine.run_single_backtest(
            historical_data_points=ohlc_data_points_for_backtest, # This is List[OHLCDataPoint]
            strategy_class=strategy_class,
            strategy_params=request.parameters, # Pass the parameters from the request
            backtest_request_details=request,   # Pass the full request for context in the result
            initial_capital=request.initial_capital
        )
        return backtest_result # This is models.BacktestResult, now includes drawdown_curve
    except ValueError as e: # e.g., issues within strategy logic or data processing in strategy_engine
        logger.error(f"ValueError during backtest execution: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e)) # Bad request if strategy logic fails due to bad params etc.
    except Exception as e:
        logger.error(f"Unexpected error during backtest execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during backtest execution: {str(e)}")


@app.get("/strategies/available", response_model=models.AvailableStrategiesResponse, tags=["Strategies"]) # Added tag
async def list_available_strategies():
    available_strategies = []
    for strategy_id, strategy_class in STRATEGY_REGISTRY.items():
        try:
            # get_info() now returns StrategyInfo with enhanced StrategyParameter
            info = strategy_class.get_info()
            available_strategies.append(info)
        except Exception as e:
            logger.error(f"Error getting info for strategy {strategy_id}: {e}", exc_info=True)
            # Optionally skip this strategy or return a partial list
    return models.AvailableStrategiesResponse(strategies=available_strategies)


# --- Optimization Endpoints ---
@app.post("/optimize/start", response_model=models.OptimizationJobStatus, tags=["Optimization"])
async def start_optimization_api(
    optimization_request: models.OptimizationRequest,
    background_tasks: BackgroundTasks
):
    logger.info(f"Received optimization request for strategy_id: '{optimization_request.strategy_id}'")
    strategy_class = STRATEGY_REGISTRY.get(optimization_request.strategy_id)
    if not strategy_class:
        logger.error(f"Strategy ID '{optimization_request.strategy_id}' not found for optimization.")
        # Return a FAILED job status immediately
        temp_job_id_fail = str(uuid.uuid4())
        return models.OptimizationJobStatus(
            job_id=temp_job_id_fail, status="FAILED",
            message=f"Strategy ID '{optimization_request.strategy_id}' not found.",
            total_iterations=0
        )

    try:
        # Fetch data first
        data_req = models.HistoricalDataRequest(
            exchange=optimization_request.exchange, token=optimization_request.token,
            start_time=optimization_request.start_date, end_time=optimization_request.end_date,
            interval=optimization_request.timeframe
        )
        api_client = get_shoonya_api_client() # Ensure API client is ready
        if not api_client:
             raise ConnectionError("Shoonya API client not available for optimization data.")
        historical_data_container = await data_module.fetch_and_store_historical_data(data_req)
        ohlc_data_points_for_opt = historical_data_container.data

        if not ohlc_data_points_for_opt:
            logger.error(f"No historical data for optimization: {data_req.model_dump_json()}. Message: {historical_data_container.message}")
            temp_job_id_fail_data = str(uuid.uuid4())
            # Return a FAILED job status if no data
            return models.OptimizationJobStatus(
                job_id=temp_job_id_fail_data, status="FAILED",
                message=f"No historical data for optimization. {historical_data_container.message or ''}",
                total_iterations=0 # No iterations if no data
            )
        
        logger.info(f"Data fetched for optimization ({len(ohlc_data_points_for_opt)} points). Starting job task...")
        job_status = await optimizer_engine.start_optimization_job(
            request=optimization_request,
            strategy_class=strategy_class,
            historical_data_points=ohlc_data_points_for_opt,
            background_tasks=background_tasks
        )
        
        # Store the original request associated with this job_id if successfully queued/started
        if job_status and job_status.job_id and job_status.status not in ["FAILED"]:
            _optimization_requests_store[job_status.job_id] = optimization_request
            logger.info(f"Optimization job {job_status.job_id} successfully queued. Storing original request.")
        else:
            logger.warning(f"Optimization job for strategy {optimization_request.strategy_id} could not be started properly. Status: {job_status.status if job_status else 'N/A'}")
            # If job_status indicates failure from optimizer_engine.start_optimization_job itself (e.g. no combos)
            # it will be returned directly.
            
        return job_status

    except HTTPException as he: # Re-raise HTTPExceptions from data fetching
        logger.error(f"HTTPException during optimization start data fetch: {he.detail}")
        raise he # Let FastAPI handle this
    except ConnectionError as ce:
        logger.error(f"Connection error during optimization start: {ce}", exc_info=True)
        temp_job_id_fail_conn = str(uuid.uuid4())
        return models.OptimizationJobStatus(
            job_id=temp_job_id_fail_conn, status="FAILED",
            message=f"Could not connect to data provider for optimization: {str(ce)}",
            total_iterations=0
        )
    except Exception as e:
        logger.error(f"Unexpected error starting optimization for '{optimization_request.strategy_id}': {e}", exc_info=True)
        temp_job_id_fail_unexp = str(uuid.uuid4())
        return models.OptimizationJobStatus(
            job_id=temp_job_id_fail_unexp, status="FAILED",
            message=f"Failed to start optimization due to an internal error: {str(e)}",
            total_iterations=0
        )


@app.get("/optimize/status/{job_id}", response_model=Optional[models.OptimizationJobStatus], tags=["Optimization"])
async def get_optimization_status_api(job_id: str):
    # ... (status logic remains the same)
    logger.debug(f"Request for optimization status for job ID: {job_id}")
    status = optimizer_engine.get_optimization_job_status(job_id)
    if not status:
        logger.warning(f"Optimization job ID '{job_id}' not found for status check.")
        raise HTTPException(status_code=404, detail=f"Optimization job ID '{job_id}' not found.")
    return status

@app.get("/optimize/results/{job_id}", response_model=models.OptimizationResultsResponse, tags=["Optimization"])
async def get_optimization_results_api(job_id: str):
    # ... (results logic remains the same, but OptimizationResultsResponse now has original_request)
    logger.debug(f"Request for optimization results for job ID: {job_id}")
    status = optimizer_engine.get_optimization_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found.")
    
    if status.status not in ["COMPLETED", "CANCELLED"]: # Allow fetching results if cancelled but some exist
        raise HTTPException(status_code=400, detail=f"Job '{job_id}' not {status.status}. Current status: {status.status}")

    results = optimizer_engine.get_optimization_job_results(job_id)
    if results is None and status.status == "COMPLETED": # If completed but truly no results
        raise HTTPException(status_code=404, detail=f"Results for COMPLETED job ID '{job_id}' not found.")
    if results is None and status.status == "CANCELLED": # If cancelled and no partial results
        # This is okay, just means no results were processed before cancellation
        logger.info(f"Job {job_id} was cancelled and no partial results are available.")
        # Return an empty results response or a specific message
        # For now, let's prepare for the possibility of empty results list.
        results = []


    original_request = _optimization_requests_store.get(job_id)
    if not original_request:
        logger.error(f"Original request for job ID '{job_id}' not found in store.")
        raise HTTPException(status_code=500, detail=f"Internal error: Original request details for job '{job_id}' missing.")

    best_result_entry: Optional[models.OptimizationResultEntry] = None
    if results: # results can be an empty list if cancelled early
        metric_key = original_request.metric_to_optimize
        try:
            # Filter out results with errors in performance_metrics
            valid_results_for_best = [r for r in results if isinstance(r.performance_metrics, dict) and metric_key in r.performance_metrics and isinstance(r.performance_metrics.get(metric_key), (int, float))]
            if valid_results_for_best:
                best_result_entry = max(valid_results_for_best, key=lambda r: r.performance_metrics[metric_key])
            else:
                logger.warning(f"No valid results found to determine best for job {job_id} using metric '{metric_key}'.")
        except (TypeError, ValueError) as e:
            logger.warning(f"Could not determine best result for job {job_id} using metric '{metric_key}': {e}")

    return models.OptimizationResultsResponse(
        job_id=job_id,
        strategy_id=original_request.strategy_id,
        request_details=original_request, # Now populated
        results=results if results is not None else [],
        best_result=best_result_entry,
        summary_stats={"total_combinations_run": len(results) if results is not None else 0, "status": status.status},
        total_combinations_tested=len(results) if results is not None else 0
    )


@app.get("/optimize/results/{job_id}/download", tags=["Optimization"])
async def download_optimization_results_api(job_id: str):
    # ... (download logic remains largely the same, ensure headers are robust)
    logger.debug(f"Request to download optimization results for job ID: {job_id}")
    status = optimizer_engine.get_optimization_job_status(job_id) # Check status first
    if not status:
        raise HTTPException(status_code=404, detail=f"Optimization job ID '{job_id}' not found.")
    if status.status not in ["COMPLETED", "CANCELLED"]:
         raise HTTPException(status_code=400, detail=f"Optimization job '{job_id}' is not yet completed or cancelled with results. Current status: {status.status}")

    results = optimizer_engine.get_optimization_job_results(job_id) # Fetches results if completed or partial if cancelled

    output = io.StringIO()
    if not results: # No results, even if job is 'COMPLETED' (e.g. no valid combos) or 'CANCELLED' early
        writer = csv.writer(output)
        writer.writerow(["Message"])
        writer.writerow([f"No results available for job '{job_id}'. Status: {status.status}."])
    else:
        # Dynamically get headers from the first result's parameters and performance_metrics
        # Ensure all keys are present, as some combos might have different structure if params are conditional
        all_param_keys = set()
        all_perf_keys = set()
        for entry in results:
            if isinstance(entry.parameters, dict):
                all_param_keys.update(entry.parameters.keys())
            if isinstance(entry.performance_metrics, dict):
                all_perf_keys.update(entry.performance_metrics.keys())
        
        # Order them if possible, e.g., alphabetically or predefined
        param_headers = sorted(list(all_param_keys))
        perf_headers = sorted(list(all_perf_keys))
        headers = param_headers + perf_headers
        
        if not headers: # If results exist but are malformed (empty dicts)
            writer = csv.writer(output)
            writer.writerow(["Message"])
            writer.writerow([f"Results for job '{job_id}' are malformed or empty."])
        else:
            writer = csv.DictWriter(output, fieldnames=headers)
            writer.writeheader()
            for entry in results:
                row_data = {}
                # Populate with None if a key is missing for a specific row
                for p_key in param_headers:
                    row_data[p_key] = entry.parameters.get(p_key) if isinstance(entry.parameters, dict) else None
                for m_key in perf_headers:
                    row_data[m_key] = entry.performance_metrics.get(m_key) if isinstance(entry.performance_metrics, dict) else None
                writer.writerow(row_data)

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=optimization_results_{job_id}.csv"}
    )

# --- New Control Endpoint: Cancel Optimization ---
@app.post("/optimize/cancel/{job_id}", response_model=models.CancelOptimizationResponse, tags=["Optimization"])
async def cancel_optimization_api(job_id: str):
    logger.info(f"Received request to cancel optimization job ID: {job_id}")
    cancel_result = optimizer_engine.cancel_optimization_job(job_id)

    status_code = 200
    if cancel_result["status"] == "job_not_found":
        status_code = 404
    elif cancel_result["status"] == "error" or "already" in cancel_result["status"]:
        status_code = 400 # Bad request if job can't be cancelled or already finished

    return JSONResponse(status_code=status_code, content=cancel_result)


# --- New Endpoint: Chart Data with Strategy ---
@app.post("/chart_data_with_strategy", response_model=models.ChartDataResponse, tags=["Charting"])
async def get_chart_data_with_strategy(chart_request: models.ChartDataRequest):
    logger.info(f"Received chart data request: Exch={chart_request.exchange}, Tkn={chart_request.token}, Strat={chart_request.strategy_id}")

    strategy_class: Optional[Type[BaseStrategy]] = None
    if chart_request.strategy_id:
        strategy_class = STRATEGY_REGISTRY.get(chart_request.strategy_id)
        if not strategy_class:
            logger.warning(f"Strategy ID '{chart_request.strategy_id}' not found for chart data.")
            # Proceed without strategy, or raise HTTPException if strategy is mandatory for this endpoint's purpose
            # For now, we'll allow no strategy (just OHLC)
            # raise HTTPException(status_code=404, detail=f"Strategy ID '{chart_request.strategy_id}' not found.")

    # Determine date range for fetching data
    # If start_date/end_date are not provided, fetch a default recent period (e.g., last N days/months)
    # This logic should ideally be in data_module or configurable
    # For now, assume data_module handles unspecified dates by fetching a default range or requires them.
    # Let's assume if dates are None, we fetch a recent period.
    # The HistoricalDataRequest model requires start_time and end_time.
    # We need to define a default range if not provided by chart_request.
    
    # Default to a recent period if dates are not specified by the client
    # This needs to be more robust, e.g. settings.DEFAULT_CHART_DAYS
    default_days_for_chart = 90 # Example default
    end_d = chart_request.end_date if chart_request.end_date else date.today()
    start_d = chart_request.start_date if chart_request.start_date else end_d - pd.Timedelta(days=default_days_for_chart)


    hist_data_req = models.HistoricalDataRequest(
        exchange=chart_request.exchange,
        token=chart_request.token,
        start_time=start_d,
        end_time=end_d,
        interval=chart_request.timeframe # Make sure this is a valid interval for data_module
    )

    try:
        api_client = get_shoonya_api_client()
        if not api_client:
             raise ConnectionError("Shoonya API client not available for chart data.")
        
        historical_data_container = await data_module.fetch_and_store_historical_data(hist_data_req)
        ohlc_points_for_chart = historical_data_container.data # This is List[OHLCDataPoint] with datetime objects

        if not ohlc_points_for_chart:
            logger.warning(f"No historical data found for chart request: {hist_data_req.model_dump_json()}")
            # Return empty chart data or raise error
            return models.ChartDataResponse(
                ohlc_data=[], indicator_data=[], trade_markers=[],
                chart_header_info=f"{chart_request.exchange.upper()}:{chart_request.token} ({chart_request.timeframe}) - No Data Available",
                timeframe_actual=chart_request.timeframe
            )
        
        # Get trading symbol for header (if available)
        # This could be fetched from scripmaster or passed if known
        token_info = await data_module.get_token_info(chart_request.exchange, chart_request.token)
        trading_symbol_for_header = token_info.trading_symbol if token_info and token_info.trading_symbol else chart_request.token

        # Generate chart data using strategy_engine
        chart_response = await strategy_engine.generate_chart_data(
            chart_request=chart_request,
            historical_data_points=ohlc_points_for_chart, # Pass List[OHLCDataPoint]
            strategy_class=strategy_class,
            token_trading_symbol=trading_symbol_for_header
        )
        return chart_response

    except FileNotFoundError as e:
        logger.error(f"Data file not found for chart: {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=f"Historical data file not found: {str(e)}")
    except ValueError as e: # Validation errors from models or data_module
        logger.error(f"Value error generating chart data: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=str(e))
    except ConnectionError as e:
        logger.error(f"Connection error generating chart data: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Service unavailable for chart data: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error generating chart data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred while generating chart data: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    # Note on BackgroundTasks and multiple workers:
    # The in-memory _optimization_jobs, _optimization_results, and _optimization_requests_store
    # will NOT be shared correctly if uvicorn is run with --workers > 1.
    # For production with multiple workers, an external store (Redis, DB) is essential for these.
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, workers=1) # Explicitly workers=1 for dev