# app/main.py
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse # Added FileResponse
from fastapi.staticfiles import StaticFiles # Added StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from typing import List, Dict, Type, Optional
import io
import csv
from datetime import date, datetime
import uuid
import pandas as pd
import os # Added os module

from .config import settings, logger
from .auth import get_shoonya_api_client
from . import models
from . import data_module
from . import strategy_engine
from . import optimizer_engine
from .strategies.base_strategy import BaseStrategy
from .strategies.ema_crossover_strategy import EMACrossoverStrategy
# Potentially more strategy imports if you have them

app = FastAPI(title="Trading System V2", version="0.1.0")

# —— Add this block for CORS ——
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # or list your exact front-end URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ————————————————————

# Determine the path to the frontend directory
# Assuming your main.py is in 'app' and 'frontend' is at the same level as 'app'
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

# Mount static files (CSS, JS, etc.) from the frontend directory
# This will serve files like /api.js, /ui.js etc. from the 'frontend' folder
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend_static")


# Strategy Registry
STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {
    "ema_crossover": EMACrossoverStrategy,
    # Add other strategies here
}

_optimization_requests_store: Dict[str, models.OptimizationRequest] = {}


@app.on_event("startup")
async def startup_event():
    logger.info("Application startup...")
    logger.info(f"Base directory: {BASE_DIR}")
    logger.info(f"Frontend directory: {FRONTEND_DIR}")
    if not os.path.exists(FRONTEND_DIR):
        logger.error(f"Frontend directory not found at: {FRONTEND_DIR}")
    if not os.path.exists(os.path.join(FRONTEND_DIR, "index.html")):
        logger.error(f"index.html not found in frontend directory: {os.path.join(FRONTEND_DIR, 'index.html')}")
    logger.info(f"Default symbol: {settings.DEFAULT_SYMBOL} ({settings.DEFAULT_TOKEN})")
    logger.info(f"Registered strategies: {list(STRATEGY_REGISTRY.keys())}")
    try:
        api_client = get_shoonya_api_client()
        if api_client:
            data_module.load_scripmaster(settings.DEFAULT_EXCHANGE)
        logger.info("Initial API client access attempted and default scripmaster loaded (if available).")
    except Exception as e:
        logger.error(f"Error during startup (API client or Scripmaster load): {e}", exc_info=True)


# Serve index.html as the root page for the application
@app.get("/", include_in_schema=False) # include_in_schema=False to hide from API docs
async def serve_index_html():
    index_html_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(index_html_path):
        logger.error(f"index.html not found at path: {index_html_path}")
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_html_path, media_type="text/html")


# Your existing API endpoints (health, symbols, data, strategies, optimize, backtest, chart_data_with_strategy)
# will remain largely the same. The paths for these API endpoints (e.g., /health, /symbols/{exchange})
# will still work as before. The frontend JavaScript will call these API endpoints.

# Example:
# @app.get("/api_root") # Renamed your old root to avoid conflict if needed, or remove it
# async def read_root_api():
# return {"message": f"Welcome to Trading System V2 API. Default Symbol: {settings.DEFAULT_SYMBOL}"}

@app.get("/health", response_model=models.HealthResponse)
async def health_check():
    # ... (health check logic remains the same)
    shoonya_status = "login_attempt_required_or_success" # Default optimistic status
    try:
        get_shoonya_api_client() # This will attempt login if not already done
        shoonya_status = "login_successful_or_pending" # If no exception, login was attempted or is okay
        return models.HealthResponse(status="healthy", shoonya_api_status=shoonya_status)
    except ConnectionError as e:
        logger.error(f"Health check: Shoonya API connection error - {e}")
        return models.HealthResponse(status="unhealthy", shoonya_api_status=f"connection_error: {e}")
    except ValueError as e:
        logger.error(f"Health check: Configuration error - {e}")
        return models.HealthResponse(status="unhealthy", shoonya_api_status=f"configuration_error: {e}")
    except Exception as e:
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
    # ... (historical data fetching logic remains the same)
    try:
        logger.info(f"Received request for historical data: {request.exchange}:{request.token}")
        historical_data_response = await data_module.fetch_and_store_historical_data(request)
        return historical_data_response
    except FileNotFoundError as e:
        logger.error(f"File not found error in historical data endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        logger.error(f"Value error in historical data endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=str(e)) # 422 Unprocessable Entity
    except ConnectionError as e:
        logger.error(f"Connection error in historical data endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to data provider. {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in /data/historical endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred: {str(e)}")

@app.get("/strategies/available", response_model=models.AvailableStrategiesResponse, tags=["Strategies"])
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
    optimization_request: models.OptimizationRequest,
    background_tasks: BackgroundTasks
):
    logger.info(f"Received optimization request for strategy_id: '{optimization_request.strategy_id}'")
    strategy_class = STRATEGY_REGISTRY.get(optimization_request.strategy_id)
    if not strategy_class:
        logger.error(f"Strategy ID '{optimization_request.strategy_id}' not found for optimization.")
        temp_job_id_fail = str(uuid.uuid4())
        return models.OptimizationJobStatus(
            job_id=temp_job_id_fail, status="FAILED",
            message=f"Strategy ID '{optimization_request.strategy_id}' not found.",
            total_iterations=0
        )

    try:
        data_req = models.HistoricalDataRequest(
            exchange=optimization_request.exchange, token=optimization_request.token,
            start_time=optimization_request.start_date, end_time=optimization_request.end_date,
            interval=optimization_request.timeframe
        )
        api_client = get_shoonya_api_client()
        if not api_client:
             raise ConnectionError("Shoonya API client not available for optimization data.")
        historical_data_container = await data_module.fetch_and_store_historical_data(data_req)
        ohlc_data_points_for_opt = historical_data_container.data

        if not ohlc_data_points_for_opt:
            logger.error(f"No historical data for optimization: {data_req.model_dump_json()}. Message: {historical_data_container.message}")
            temp_job_id_fail_data = str(uuid.uuid4())
            return models.OptimizationJobStatus(
                job_id=temp_job_id_fail_data, status="FAILED",
                message=f"No historical data for optimization. {historical_data_container.message or ''}",
                total_iterations=0
            )
        
        logger.info(f"Data fetched for optimization ({len(ohlc_data_points_for_opt)} points). Starting job task...")
        job_status = await optimizer_engine.start_optimization_job(
            request=optimization_request,
            strategy_class=strategy_class,
            historical_data_points=ohlc_data_points_for_opt,
            background_tasks=background_tasks
        )
        
        if job_status and job_status.job_id and job_status.status not in ["FAILED"]:
            _optimization_requests_store[job_status.job_id] = optimization_request
            logger.info(f"Optimization job {job_status.job_id} successfully queued. Storing original request.")
        else:
            logger.warning(f"Optimization job for strategy {optimization_request.strategy_id} could not be started properly. Status: {job_status.status if job_status else 'N/A'}")
            
        return job_status

    except HTTPException as he:
        logger.error(f"HTTPException during optimization start data fetch: {he.detail}")
        raise he
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
    logger.debug(f"Request for optimization status for job ID: {job_id}")
    status = optimizer_engine.get_optimization_job_status(job_id)
    if not status:
        logger.warning(f"Optimization job ID '{job_id}' not found for status check.")
        raise HTTPException(status_code=404, detail=f"Optimization job ID '{job_id}' not found.")
    return status

@app.get("/optimize/results/{job_id}", response_model=models.OptimizationResultsResponse, tags=["Optimization"])
async def get_optimization_results_api(job_id: str):
    logger.debug(f"Request for optimization results for job ID: {job_id}")
    status = optimizer_engine.get_optimization_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found.")
    
    if status.status not in ["COMPLETED", "CANCELLED"]:
        raise HTTPException(status_code=400, detail=f"Job '{job_id}' not {status.status}. Current status: {status.status}")

    results = optimizer_engine.get_optimization_job_results(job_id)
    if results is None and status.status == "COMPLETED":
        raise HTTPException(status_code=404, detail=f"Results for COMPLETED job ID '{job_id}' not found.")
    if results is None and status.status == "CANCELLED":
        logger.info(f"Job {job_id} was cancelled and no partial results are available.")
        results = []

    original_request = _optimization_requests_store.get(job_id)
    if not original_request:
        logger.error(f"Original request for job ID '{job_id}' not found in store.")
        raise HTTPException(status_code=500, detail=f"Internal error: Original request details for job '{job_id}' missing.")

    best_result_entry: Optional[models.OptimizationResultEntry] = None
    if results:
        metric_key = original_request.metric_to_optimize
        try:
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
        request_details=original_request,
        results=results if results is not None else [],
        best_result=best_result_entry,
        summary_stats={"total_combinations_run": len(results) if results is not None else 0, "status": status.status},
        total_combinations_tested=len(results) if results is not None else 0
    )


@app.get("/optimize/results/{job_id}/download", tags=["Optimization"])
async def download_optimization_results_api(job_id: str):
    logger.debug(f"Request to download optimization results for job ID: {job_id}")
    status = optimizer_engine.get_optimization_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Optimization job ID '{job_id}' not found.")
    if status.status not in ["COMPLETED", "CANCELLED"]:
         raise HTTPException(status_code=400, detail=f"Optimization job '{job_id}' is not yet completed or cancelled with results. Current status: {status.status}")

    results = optimizer_engine.get_optimization_job_results(job_id)

    output = io.StringIO()
    if not results:
        writer = csv.writer(output)
        writer.writerow(["Message"])
        writer.writerow([f"No results available for job '{job_id}'. Status: {status.status}."])
    else:
        all_param_keys = set()
        all_perf_keys = set()
        for entry in results:
            if isinstance(entry.parameters, dict):
                all_param_keys.update(entry.parameters.keys())
            if isinstance(entry.performance_metrics, dict):
                all_perf_keys.update(entry.performance_metrics.keys())
        
        param_headers = sorted(list(all_param_keys))
        perf_headers = sorted(list(all_perf_keys))
        headers = param_headers + perf_headers
        
        if not headers:
            writer = csv.writer(output)
            writer.writerow(["Message"])
            writer.writerow([f"Results for job '{job_id}' are malformed or empty."])
        else:
            writer = csv.DictWriter(output, fieldnames=headers)
            writer.writeheader()
            for entry in results:
                row_data = {}
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

@app.post("/optimize/cancel/{job_id}", response_model=models.CancelOptimizationResponse, tags=["Optimization"])
async def cancel_optimization_api(job_id: str):
    logger.info(f"Received request to cancel optimization job ID: {job_id}")
    cancel_result = optimizer_engine.cancel_optimization_job(job_id)

    status_code = 200
    if cancel_result["status"] == "job_not_found":
        status_code = 404
    elif cancel_result["status"] == "error" or "already" in cancel_result["status"]:
        status_code = 400

    return JSONResponse(status_code=status_code, content=cancel_result)


@app.post("/chart_data_with_strategy", response_model=models.ChartDataResponse, tags=["Charting"])
async def get_chart_data_with_strategy(chart_request: models.ChartDataRequest):
    logger.info(f"Received chart data request: Exch={chart_request.exchange}, Tkn={chart_request.token}, Strat={chart_request.strategy_id}")

    strategy_class: Optional[Type[BaseStrategy]] = None
    if chart_request.strategy_id:
        strategy_class = STRATEGY_REGISTRY.get(chart_request.strategy_id)

    default_days_for_chart = 90
    end_d = chart_request.end_date if chart_request.end_date else date.today()
    start_d = chart_request.start_date if chart_request.start_date else end_d - pd.Timedelta(days=default_days_for_chart)

    hist_data_req = models.HistoricalDataRequest(
        exchange=chart_request.exchange,
        token=chart_request.token,
        start_time=start_d,
        end_time=end_d,
        interval=chart_request.timeframe
    )

    try:
        api_client = get_shoonya_api_client()
        if not api_client:
             raise ConnectionError("Shoonya API client not available for chart data.")
        
        historical_data_container = await data_module.fetch_and_store_historical_data(hist_data_req)
        ohlc_points_for_chart = historical_data_container.data

        if not ohlc_points_for_chart:
            logger.warning(f"No historical data found for chart request: {hist_data_req.model_dump_json()}")
            return models.ChartDataResponse(
                ohlc_data=[], indicator_data=[], trade_markers=[],
                chart_header_info=f"{chart_request.exchange.upper()}:{chart_request.token} ({chart_request.timeframe}) - No Data Available",
                timeframe_actual=chart_request.timeframe
            )
        
        token_info = await data_module.get_token_info(chart_request.exchange, chart_request.token)
        trading_symbol_for_header = token_info.trading_symbol if token_info and token_info.trading_symbol else chart_request.token

        chart_response = await strategy_engine.generate_chart_data(
            chart_request=chart_request,
            historical_data_points=ohlc_points_for_chart,
            strategy_class=strategy_class,
            token_trading_symbol=trading_symbol_for_header
        )
        return chart_response

    except FileNotFoundError as e:
        logger.error(f"Data file not found for chart: {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=f"Historical data file not found: {str(e)}")
    except ValueError as e:
        logger.error(f"Value error generating chart data: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=str(e))
    except ConnectionError as e:
        logger.error(f"Connection error generating chart data: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Service unavailable for chart data: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error generating chart data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred while generating chart data: {str(e)}")

@app.post("/backtest/run", response_model=models.BacktestResult, tags=["Backtesting"])
async def run_strategy_backtest(
    backtest_request: models.BacktestRequest,
):
    logger.info(f"Received backtest request for strategy_id: '{backtest_request.strategy_id}' on {backtest_request.exchange}:{backtest_request.token}")

    strategy_class = STRATEGY_REGISTRY.get(backtest_request.strategy_id)
    if not strategy_class:
        logger.error(f"Strategy ID '{backtest_request.strategy_id}' not found for backtesting.")
        return models.BacktestResult(
            error_message=f"Strategy ID '{backtest_request.strategy_id}' not found."
        )

    try:
        hist_data_req = models.HistoricalDataRequest(
            exchange=backtest_request.exchange,
            token=backtest_request.token,
            start_time=backtest_request.start_date,
            end_time=backtest_request.end_date,
            interval=backtest_request.timeframe
        )
        
        api_client_instance = get_shoonya_api_client()
        if not api_client_instance:
             logger.error("Shoonya API client not available for fetching backtest data.")
             return models.BacktestResult(error_message="Data provider API client not available.")

        historical_data_container = await data_module.fetch_and_store_historical_data(hist_data_req)
        ohlc_data_points = historical_data_container.data

        if not ohlc_data_points:
            logger.warning(f"No historical data found for backtest: {hist_data_req.model_dump_json()}. Message: {historical_data_container.message}")
            return models.BacktestResult(
                error_message=f"No historical data found for the specified parameters. {historical_data_container.message or ''}"
            )
        
        logger.info(f"Data fetched for backtest ({len(ohlc_data_points)} points). Running simulation...")

        backtest_result = await strategy_engine.perform_backtest_simulation(
            historical_data_points=ohlc_data_points,
            strategy_class=strategy_class,
            strategy_parameters=backtest_request.parameters,
            initial_capital=backtest_request.initial_capital,
        )
        
        logger.info(f"Backtest completed for {backtest_request.strategy_id} on {backtest_request.exchange}:{backtest_request.token}. Net PnL: {backtest_result.performance_metrics.net_pnl if backtest_result.performance_metrics else 'N/A'}")
        return backtest_result

    except HTTPException as he:
        logger.error(f"HTTPException during backtest: {he.detail}", exc_info=True)
        raise he
    except ValueError as e:
        logger.error(f"Value error during backtest: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=str(e))
    except FileNotFoundError as e:
        logger.error(f"Data file not found during backtest: {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=f"Historical data file not found: {str(e)}")
    except ConnectionError as e:
        logger.error(f"Connection error during backtest data fetching: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Service unavailable for backtest data: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during backtest for '{backtest_request.strategy_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected server error occurred during backtest: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    # The run.py script will handle this if you run it from the project root.
    # If running main.py directly from the 'app' folder for some reason:
    # uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, workers=1)
    # However, it's better to use run.py as it sets up sys.path correctly.
    # The message about _optimization_jobs etc. is still relevant for multi-worker setups.
    logger.warning("Running main.py directly. For production or proper path setup, use run.py from the project root.")
    uvicorn.run(app, host="0.0.0.0", port=8000) # Use 'app' directly when running this file.