# test.py
import requests
import json
import time
from datetime import datetime, timedelta
import uuid

# --- Configuration ---
BASE_URL = "http://localhost:8000"
OUTPUT_FILE = "api_test_output_v6.txt" # Incremented version
LOG_BUFFER = []

DEFAULT_TEST_TOKEN = "3456" # NSE:TATAMOTORS as per previous context if available in scripmaster
DEFAULT_TEST_EXCHANGE = "NSE"
DEFAULT_TIMEFRAME_DAY = "1"
DEFAULT_TIMEFRAME_MIN = "1" # For chart data testing, 5 min
EMA_CROSSOVER_STRATEGY_ID = "ema_crossover"

OPTIMIZATION_POLL_INTERVAL = 5 # Reduced for faster testing of cancel
OPTIMIZATION_MAX_POLLS = 12 # Reduced (e.g., for 1 min total polling before cancel test)
OPTIMIZATION_CANCEL_WAIT_TIME = 2 # Seconds to wait after starting opt before cancelling

# --- Helper Functions ---
def log_test(endpoint_name, request_method, url, headers=None, body=None, response=None, note=None, assertion_status=None):
    log_entry = [
        f"Testing API Endpoint: {endpoint_name}",
        f"Request: {request_method} {url}"
    ]
    if headers:
        log_entry.append(f"Request Headers: {json.dumps(headers, indent=2)}")
    if body:
        log_entry.append(f"Request Body: {json.dumps(body, indent=2) if isinstance(body, dict) else body}")

    status_code_for_print = "N/A (No Response/Error)"
    response_text_for_print = ""
    if response is not None:
        status_code_for_print = response.status_code
        try:
            content_type = response.headers.get("Content-Type", "")
            if "text/csv" in content_type:
                response_text_for_print = "CSV data (first 200 chars): " + response.text[:200]
            elif "application/json" in content_type and response.content:
                response_text_for_print = f"Response Body:\n{json.dumps(response.json(), indent=2)}"
            elif response.content:
                response_text_for_print = f"Response Body (Non-JSON):\n{response.text[:500]}{'...' if len(response.text) > 500 else ''}"
            else:
                response_text_for_print = "Response Body: No content"
        except json.JSONDecodeError:
            response_text_for_print = f"Response Body (Non-JSON, JSONDecodeError):\n{response.text[:500]}{'...' if len(response.text) > 500 else ''}"
        except Exception as e:
            response_text_for_print = f"Error processing response body: {e}"
        log_entry.append(f"Response Status: {response.status_code}")
        log_entry.append(response_text_for_print)

    elif note:
        log_entry.append(note)
    
    final_assertion_status = assertion_status if assertion_status else "UNKNOWN (No explicit assertion made)"
    if response is None and not assertion_status: 
        final_assertion_status = "FAIL (No response from server or connection error)"

    log_entry.append(f"Assertion: {final_assertion_status}")
    log_entry.append("-" * 50)
    
    LOG_BUFFER.extend(log_entry)
    # Simplified console output
    print(f"Tested: {endpoint_name} - Status: {status_code_for_print} - Assertion: {final_assertion_status}")
    if "FAIL" in final_assertion_status and response is not None and status_code_for_print != "N/A (No Response/Error)":
        if response_text_for_print and "Response Body:" in response_text_for_print :
             print(f"    Detail: {response_text_for_print.split('Response Body:')[1].strip()[:300]}")
        elif response:
             print(f"    Detail: Full response text: {response.text[:300]}")


def make_request(method, endpoint, **kwargs):
    url = f"{BASE_URL}{endpoint}"
    try:
        response = requests.request(method, url, **kwargs, timeout=90) # Increased timeout for potentially long operations
        return response
    except requests.exceptions.ConnectionError as e:
        print(f"CONNECTION ERROR for {method} {url}: {e}")
        return None
    except requests.exceptions.Timeout:
        print(f"TIMEOUT for {method} {url}")
        return None
    except Exception as e:
        print(f"UNEXPECTED REQUEST EXCEPTION for {method} {url}: {e}")
        return None

# --- Test Function Definitions ---

def test_root():
    response = make_request("GET", "/")
    assertion_status = "FAIL"
    if response:
        if response.status_code == 200 :
            try:
                if "message" in response.json():
                    assertion_status = "PASS"
                else:
                    assertion_status = "FAIL ('message' key missing)"
            except json.JSONDecodeError:
                assertion_status = "FAIL (Response not valid JSON)"
        else:
            assertion_status = f"FAIL (Expected 200, got {response.status_code})"
    log_test("GET /", "GET", f"{BASE_URL}/", response=response, assertion_status=assertion_status)

def test_health():
    response = make_request("GET", "/health")
    assertion_status = "FAIL"
    if response:
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get("status") == "healthy" and "shoonya_api_status" in data:
                    assertion_status = "PASS"
                else:
                    assertion_status = "FAIL (Invalid health status structure)"
            except json.JSONDecodeError:
                assertion_status = "FAIL (Response not valid JSON)"
        else:
            assertion_status = f"FAIL (Expected 200, got {response.status_code})"
    log_test("GET /health", "GET", f"{BASE_URL}/health", response=response, assertion_status=assertion_status)

def test_list_available_symbols():
    exchange = DEFAULT_TEST_EXCHANGE
    response = make_request("GET", f"/symbols/{exchange}")
    assertion_status = "FAIL"
    if response:
        if response.status_code == 200:
            try:
                data = response.json()
                if (data.get("exchange") == exchange and 
                    "symbols" in data and isinstance(data["symbols"], list)):
                    assertion_status = "PASS"
                    if data["symbols"]: 
                         if not ("token" in data["symbols"][0] and "symbol" in data["symbols"][0]):
                             assertion_status = "FAIL (Symbol object structure incorrect)"
                else:
                    assertion_status = "FAIL (Invalid response structure)"
            except json.JSONDecodeError:
                assertion_status = "FAIL (Response not valid JSON)"
        else:
            assertion_status = f"FAIL (Expected 200, got {response.status_code})"
    log_test(f"GET /symbols/{exchange}", "GET", f"{BASE_URL}/symbols/{exchange}", response=response, assertion_status=assertion_status)

    exchange_fail = "INVALIDEXCHANGE"
    response_fail = make_request("GET", f"/symbols/{exchange_fail}")
    assertion_status_fail = "FAIL"
    if response_fail:
        if response_fail.status_code == 404: 
            assertion_status_fail = "PASS (Handled invalid exchange as expected with 404)"
        else:
            assertion_status_fail = f"FAIL (Expected 404 for invalid exchange, got {response_fail.status_code})"
    log_test(f"GET /symbols/{exchange_fail} (expected fail)", "GET", f"{BASE_URL}/symbols/{exchange_fail}", response=response_fail, assertion_status=assertion_status_fail)


def test_fetch_historical_data():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    payload = {
        "exchange": DEFAULT_TEST_EXCHANGE, "token": DEFAULT_TEST_TOKEN,
        "start_time": start_date.strftime("%Y-%m-%d"), "end_time": end_date.strftime("%Y-%m-%d"),
        "interval": DEFAULT_TIMEFRAME_DAY
    }
    headers = {"Content-Type": "application/json"}
    response = make_request("POST", "/data/historical", json=payload, headers=headers)
    assertion_status = "FAIL"
    if response:
        if response.status_code == 200:
            try:
                data = response.json()
                # Check if data field is present, is a list, and if count matches data length
                if ("data" in data and isinstance(data["data"], list) and
                        data.get("count") == len(data["data"])):
                    assertion_status = "PASS"
                    if data["data"]: # If data is not empty, check first element structure
                        first_point = data["data"][0]
                        if not all(k in first_point for k in ["time", "open", "high", "low", "close"]):
                            assertion_status = "FAIL (Data point structure incorrect)"
                        # In models.py, OHLCDataPoint.time can be datetime or int.
                        # The /data/historical endpoint (data_module) likely returns it as datetime string or compatible.
                        # For ChartDataResponse, it will be int (timestamp).
                elif data.get("count") == 0 and not data["data"]: # Valid case for no data in range
                    assertion_status = "PASS (No data found for range, as expected by count:0)"
                else:
                    assertion_status = f"FAIL (Invalid data structure or count mismatch. Status: {response.status_code})"
            except json.JSONDecodeError:
                assertion_status = "FAIL (Response not valid JSON)"
        else:
            assertion_status = f"FAIL (Expected 200, got {response.status_code})"
    log_test("POST /data/historical", "POST", f"{BASE_URL}/data/historical", headers=headers, body=payload, response=response, assertion_status=assertion_status)

    # Test for no data (future range)
    payload_no_data = {
        "exchange": DEFAULT_TEST_EXCHANGE, "token": DEFAULT_TEST_TOKEN,
        "start_time": (end_date + timedelta(days=30)).strftime("%Y-%m-%d"),
        "end_time": (end_date + timedelta(days=60)).strftime("%Y-%m-%d"),
        "interval": DEFAULT_TIMEFRAME_DAY
    }
    response_no_data = make_request("POST", "/data/historical", json=payload_no_data, headers=headers)
    assertion_status_no_data = "FAIL"
    if response_no_data:
        if response_no_data.status_code == 200: 
            try:
                data_nd = response_no_data.json()
                if data_nd.get("count") == 0 and isinstance(data_nd.get("data"), list) and not data_nd.get("data") : # and "No data found" in data_nd.get("message", ""):
                    assertion_status_no_data = "PASS (Correctly returned no data)"
                else:
                    assertion_status_no_data = f"FAIL (Expected count 0 & empty data list, got count {data_nd.get('count')}, data len {len(data_nd.get('data', []))}, msg '{data_nd.get('message')}')"
            except json.JSONDecodeError:
                assertion_status_no_data = "FAIL (No data response not valid JSON)"
        else:
            assertion_status_no_data = f"FAIL (Expected 200 for no data case, got {response_no_data.status_code})"
    log_test("POST /data/historical (no data - future)", "POST", f"{BASE_URL}/data/historical", headers=headers, body=payload_no_data, response=response_no_data, assertion_status=assertion_status_no_data)


def test_list_available_strategies():
    response = make_request("GET", "/strategies/available")
    assertion_status = "FAIL"
    if response:
        if response.status_code == 200:
            try:
                data = response.json()
                if "strategies" in data and isinstance(data["strategies"], list):
                    assertion_status = "PASS"
                    if data["strategies"]:
                        first_strategy = data["strategies"][0]
                        if not ("id" in first_strategy and "name" in first_strategy and "parameters" in first_strategy):
                            assertion_status = "FAIL (Strategy object structure incorrect)"
                        # Test for new parameter fields if parameters list is not empty
                        if first_strategy["parameters"]:
                             first_param = first_strategy["parameters"][0]
                             if not ("name" in first_param and "min_opt_range" in first_param): # Check one of the new fields
                                 assertion_status = "FAIL (Strategy parameter structure missing new fields like min_opt_range)"
                else:
                    assertion_status = "FAIL (Invalid response structure)"
            except json.JSONDecodeError:
                assertion_status = "FAIL (Response not valid JSON)"
        else:
            assertion_status = f"FAIL (Expected 200, got {response.status_code})"
    log_test("GET /strategies/available", "GET", f"{BASE_URL}/strategies/available", response=response, assertion_status=assertion_status)


def test_run_backtest():
    end_date_bt = datetime.now()
    start_date_bt = end_date_bt - timedelta(days=90)
    payload = {
        "strategy_id": EMA_CROSSOVER_STRATEGY_ID,
        "exchange": DEFAULT_TEST_EXCHANGE, "token": DEFAULT_TEST_TOKEN,
        "start_date": start_date_bt.strftime("%Y-%m-%d"), "end_date": end_date_bt.strftime("%Y-%m-%d"),
        "timeframe": DEFAULT_TIMEFRAME_DAY, # Ensure this matches a valid interval in HistoricalDataRequest
        "parameters": {"fast_ma_length": 10, "slow_ma_length": 20, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}, # Use updated param names
        "initial_capital": 100000.0, "execution_price_type": "close"
    }
    headers = {"Content-Type": "application/json"}
    response = make_request("POST", "/backtest/run", json=payload, headers=headers)
    assertion_status = "FAIL"
    if response:
        if response.status_code == 200:
            try:
                data = response.json()
                # Check for drawdown_curve and other key fields
                if ("net_pnl" in data and "total_trades" in data and 
                    "equity_curve" in data and "drawdown_curve" in data and
                    isinstance(data["drawdown_curve"], list)):
                    assertion_status = "PASS"
                else:
                    assertion_status = "FAIL (Missing key backtest result fields or drawdown_curve)"
            except json.JSONDecodeError:
                assertion_status = "FAIL (Response not valid JSON)"
        else:
            assertion_status = f"FAIL (Expected 200, got {response.status_code})"
    log_test(f"POST /backtest/run ({EMA_CROSSOVER_STRATEGY_ID})", "POST", f"{BASE_URL}/backtest/run", headers=headers, body=payload, response=response, assertion_status=assertion_status)

    payload_wrong_strategy = {**payload, "strategy_id": "non_existent_strategy_id_12345"}
    response_wrong_strategy = make_request("POST", "/backtest/run", json=payload_wrong_strategy, headers=headers)
    assertion_status_wrong_strat = "FAIL"
    if response_wrong_strategy:
        if response_wrong_strategy.status_code == 404:
            assertion_status_wrong_strat = "PASS (Handled wrong strategy ID)"
        else:
            assertion_status_wrong_strat = f"FAIL (Expected 404, got {response_wrong_strategy.status_code})"
    log_test("POST /backtest/run (wrong strategy_id)", "POST", f"{BASE_URL}/backtest/run", headers=headers, body=payload_wrong_strategy, response=response_wrong_strategy, assertion_status=assertion_status_wrong_strat)

# --- NEW TEST FUNCTION for Chart Data ---
def test_chart_data_with_strategy():
    end_date_chart = datetime.now()
    start_date_chart = end_date_chart - timedelta(days=10) # Shorter period for chart
    headers = {"Content-Type": "application/json"}

    # Case 1: No strategy_id (should return OHLC only)
    payload_no_strategy = {
        "exchange": DEFAULT_TEST_EXCHANGE, "token": DEFAULT_TEST_TOKEN,
        "timeframe": DEFAULT_TIMEFRAME_MIN, # Using 5 min for more granular chart data
        "start_date": start_date_chart.strftime("%Y-%m-%d"),
        "end_date": end_date_chart.strftime("%Y-%m-%d"),
        # "strategy_id": None, # Optional, can be omitted
        # "strategy_params": {}
    }
    response_no_strat = make_request("POST", "/chart_data_with_strategy", json=payload_no_strategy, headers=headers)
    assertion_status_no_strat = "FAIL"
    if response_no_strat:
        if response_no_strat.status_code == 200:
            try:
                data = response_no_strat.json()
                if ("ohlc_data" in data and isinstance(data["ohlc_data"], list) and
                    "indicator_data" in data and isinstance(data["indicator_data"], list) and not data["indicator_data"] and # No indicators
                    "trade_markers" in data and isinstance(data["trade_markers"], list) and not data["trade_markers"] and # No markers
                    "chart_header_info" in data and "timeframe_actual" in data):
                    assertion_status_no_strat = "PASS"
                    if data["ohlc_data"]:
                        if not isinstance(data["ohlc_data"][0].get("time"), int):
                            assertion_status_no_strat = "FAIL (OHLC time is not UNIX timestamp)"
                else:
                    assertion_status_no_strat = "FAIL (Chart data structure incorrect for no strategy)"
            except json.JSONDecodeError:
                assertion_status_no_strat = "FAIL (Response not valid JSON for no strategy)"
        else:
            assertion_status_no_strat = f"FAIL (Expected 200 for no strategy, got {response_no_strat.status_code})"
    log_test("POST /chart_data_with_strategy (no strategy)", "POST", f"{BASE_URL}/chart_data_with_strategy", headers=headers, body=payload_no_strategy, response=response_no_strat, assertion_status=assertion_status_no_strat)

    # Case 2: With EMA Crossover strategy
    payload_with_strategy = {
        "exchange": DEFAULT_TEST_EXCHANGE, "token": DEFAULT_TEST_TOKEN,
        "timeframe": DEFAULT_TIMEFRAME_MIN,
        "start_date": start_date_chart.strftime("%Y-%m-%d"),
        "end_date": end_date_chart.strftime("%Y-%m-%d"),
        "strategy_id": EMA_CROSSOVER_STRATEGY_ID,
        "strategy_params": {"fast_ma_length": 10, "slow_ma_length": 20} # Use UI param names
    }
    response_with_strat = make_request("POST", "/chart_data_with_strategy", json=payload_with_strategy, headers=headers)
    assertion_status_with_strat = "FAIL"
    if response_with_strat:
        if response_with_strat.status_code == 200:
            try:
                data = response_with_strat.json()
                if ("ohlc_data" in data and isinstance(data["ohlc_data"], list) and
                    "indicator_data" in data and isinstance(data["indicator_data"], list) and
                    "trade_markers" in data and isinstance(data["trade_markers"], list) and # Markers can be empty
                    "chart_header_info" in data and EMA_CROSSOVER_STRATEGY_ID in data["chart_header_info"].lower() and # Check strategy in header
                    "timeframe_actual" in data):
                    assertion_status_with_strat = "PASS"
                    if data["ohlc_data"] and not isinstance(data["ohlc_data"][0].get("time"), int):
                        assertion_status_with_strat = "FAIL (OHLC time is not UNIX timestamp with strategy)"
                    if data["indicator_data"]: # If indicators are present
                        first_indicator = data["indicator_data"][0]
                        if not ("name" in first_indicator and "data" in first_indicator and "config" in first_indicator):
                             assertion_status_with_strat = "FAIL (Indicator series structure incorrect)"
                        if first_indicator["data"] and not isinstance(first_indicator["data"][0].get("time"), int):
                             assertion_status_with_strat = "FAIL (Indicator time is not UNIX timestamp)"
                    # Trade markers can be empty, so only check structure if present
                    if data["trade_markers"]:
                        first_marker = data["trade_markers"][0]
                        if not ("time" in first_marker and "position" in first_marker and "shape" in first_marker):
                            assertion_status_with_strat = "FAIL (Trade marker structure incorrect)"
                        if not isinstance(first_marker.get("time"), int):
                             assertion_status_with_strat = "FAIL (Marker time is not UNIX timestamp)"
                else:
                    assertion_status_with_strat = "FAIL (Chart data structure incorrect with strategy)"
            except json.JSONDecodeError:
                assertion_status_with_strat = "FAIL (Response not valid JSON with strategy)"
        else:
            assertion_status_with_strat = f"FAIL (Expected 200 with strategy, got {response_with_strat.status_code})"
    log_test(f"POST /chart_data_with_strategy ({EMA_CROSSOVER_STRATEGY_ID})", "POST", f"{BASE_URL}/chart_data_with_strategy", headers=headers, body=payload_with_strategy, response=response_with_strat, assertion_status=assertion_status_with_strat)


def test_optimization_flow(): # Now includes cancellation test
    optimization_job_id = None
    end_date_opt = datetime.now()
    start_date_opt = end_date_opt - timedelta(days=365) # Shorter for quicker test

    payload_start = {
        "strategy_id": EMA_CROSSOVER_STRATEGY_ID,
        "exchange": DEFAULT_TEST_EXCHANGE, "token": DEFAULT_TEST_TOKEN,
        "start_date": start_date_opt.strftime("%Y-%m-%d"), "end_date": end_date_opt.strftime("%Y-%m-%d"),
        "timeframe": DEFAULT_TIMEFRAME_DAY, # Day timeframe for optimization usually makes sense
        "parameter_ranges": [ # Use UI param names from StrategyInfo
            {"name": "fast_ma_length", "start_value": 2, "end_value": 50, "step": 1}, # small range for quick test
            {"name": "slow_ma_length", "start_value": 5, "end_value": 100, "step": 1}
        ],
        "metric_to_optimize": "net_pnl", 
        "initial_capital": 75000.0,
        "execution_price_type": "close"
    }
    headers = {"Content-Type": "application/json"}
    response_start = make_request("POST", "/optimize/start", json=payload_start, headers=headers)
    
    assertion_status_start = "FAIL"
    if response_start:
        if response_start.status_code == 200:
            try:
                job_data = response_start.json()
                optimization_job_id = job_data.get("job_id")
                if optimization_job_id and job_data.get("status") in ["QUEUED", "PENDING", "RUNNING"]: # RUNNING if immediate
                    assertion_status_start = "PASS (Job Queued/Started)"
                    LOG_BUFFER.append(f"Optimization job started with ID: {optimization_job_id}")
                    print(f"Optimization job submitted... ID: {optimization_job_id}")
                else:
                    assertion_status_start = f"FAIL (Job ID or expected status missing. Status: {job_data.get('status')}, JobID: {optimization_job_id})"
            except json.JSONDecodeError:
                assertion_status_start = "FAIL (Start response not valid JSON)"
        else:
            assertion_status_start = f"FAIL (Expected 200, got {response_start.status_code}. Body: {response_start.text[:200]})"
    log_test("POST /optimize/start", "POST", f"{BASE_URL}/optimize/start", headers=headers, body=payload_start, response=response_start, assertion_status=assertion_status_start)

    # --- Test Optimization Cancellation ---
    job_to_cancel = optimization_job_id # Use the ID from the job we just started
    
    if job_to_cancel:
        print(f"Waiting {OPTIMIZATION_CANCEL_WAIT_TIME}s before attempting to cancel job {job_to_cancel}...")
        time.sleep(OPTIMIZATION_CANCEL_WAIT_TIME)

        response_cancel_running = make_request("POST", f"/optimize/cancel/{job_to_cancel}")
        assertion_status_cancel_running = "FAIL"
        if response_cancel_running:
            if response_cancel_running.status_code == 200:
                try:
                    cancel_data = response_cancel_running.json()
                    if cancel_data.get("status") == "cancellation_requested" and cancel_data.get("job_id") == job_to_cancel:
                        assertion_status_cancel_running = "PASS (Cancellation requested for running job)"
                    else:
                        assertion_status_cancel_running = f"FAIL (Unexpected cancel response: {cancel_data.get('status')})"
                except json.JSONDecodeError:
                     assertion_status_cancel_running = "FAIL (Cancel response not JSON)"
            elif response_cancel_running.status_code == 400 and "already_cancelled" in response_cancel_running.text : # If it cancelled very fast
                assertion_status_cancel_running = "PASS (Job was already cancelled/completed quickly)"
            else:
                assertion_status_cancel_running = f"FAIL (Expected 200 for cancel, got {response_cancel_running.status_code})"
        log_test(f"POST /optimize/cancel/{job_to_cancel} (running job)", "POST", f"{BASE_URL}/optimize/cancel/{job_to_cancel}", response=response_cancel_running, assertion_status=assertion_status_cancel_running)

        # Verify status becomes CANCELLED
        time.sleep(OPTIMIZATION_POLL_INTERVAL / 2) # Give some time for status to update
        response_status_after_cancel = make_request("GET", f"/optimize/status/{job_to_cancel}")
        assertion_status_cancelled_verify = "FAIL"
        if response_status_after_cancel and response_status_after_cancel.status_code == 200:
            try:
                status_data = response_status_after_cancel.json()
                if status_data.get("status") == "CANCELLED":
                    assertion_status_cancelled_verify = "PASS (Job status is CANCELLED)"
                else:
                    assertion_status_cancelled_verify = f"FAIL (Job status is {status_data.get('status')}, expected CANCELLED)"
            except json.JSONDecodeError:
                assertion_status_cancelled_verify = "FAIL (Status after cancel not JSON)"
        log_test(f"GET /optimize/status/{job_to_cancel} (after cancel request)", "GET", f"{BASE_URL}/optimize/status/{job_to_cancel}", response=response_status_after_cancel, assertion_status=assertion_status_cancelled_verify)

    # Test cancelling a non-existent job
    non_existent_cancel_id = str(uuid.uuid4())
    response_cancel_non_existent = make_request("POST", f"/optimize/cancel/{non_existent_cancel_id}")
    assertion_status_cancel_non_existent = "FAIL"
    if response_cancel_non_existent and response_cancel_non_existent.status_code == 404:
        assertion_status_cancel_non_existent = "PASS (Handled cancel non-existent job)"
    log_test(f"POST /optimize/cancel/{non_existent_cancel_id} (non-existent)", "POST", f"{BASE_URL}/optimize/cancel/{non_existent_cancel_id}", response=response_cancel_non_existent, assertion_status=assertion_status_cancel_non_existent)


    # --- Original Polling Logic (might be short-circuited by cancellation) ---
    if optimization_job_id:
        LOG_BUFFER.append(f"Polling for optimization job {optimization_job_id} status (may be cancelled)...")
        print(f"Polling for optimization job {optimization_job_id} status every {OPTIMIZATION_POLL_INTERVAL}s (may be cancelled)...")
        
        job_completed_successfully = False # Reset for this flow
        job_was_cancelled = False
        final_poll_assertion_status = "FAIL (Polling did not complete as expected or job was cancelled)"
        response_status = None # Define for wider scope

        for i in range(OPTIMIZATION_MAX_POLLS):
            time.sleep(OPTIMIZATION_POLL_INTERVAL)
            response_status = make_request("GET", f"/optimize/status/{optimization_job_id}")
            
            current_poll_assertion = "FAIL (Polling Inconclusive)"
            current_job_status_from_api = "UNKNOWN_POLL_ERROR"

            if response_status and response_status.status_code == 200:
                try:
                    status_data = response_status.json()
                    current_job_status_from_api = status_data.get("status")
                    progress = status_data.get("progress", 0.0)
                    message = status_data.get("message", "")
                    print(f"Poll {i+1}/{OPTIMIZATION_MAX_POLLS}: Job {optimization_job_id} status: {current_job_status_from_api}, Progress: {progress*100:.2f}%, Msg: {message}")
                    LOG_BUFFER.append(f"Poll {i+1}: Job Status: {current_job_status_from_api}, Progress: {progress*100:.2f}%, Message: {message}")

                    if current_job_status_from_api == "COMPLETED":
                        current_poll_assertion = "PASS (Job Completed this poll)"
                        job_completed_successfully = True
                        break 
                    elif current_job_status_from_api == "FAILED":
                        current_poll_assertion = f"FAIL (Job Explicitly Failed this poll: {message})"
                        break 
                    elif current_job_status_from_api == "CANCELLED":
                        current_poll_assertion = "PASS (Job confirmed CANCELLED during poll)"
                        job_was_cancelled = True
                        break # Stop polling if cancelled
                    current_poll_assertion = "PASS (Job In Progress this poll)"
                except json.JSONDecodeError:
                    current_poll_assertion = "FAIL (Status response not valid JSON this poll)"
                    break
            elif response_status:
                 current_poll_assertion = f"FAIL (Status API error during poll: {response_status.status_code})"
                 break 
            else:
                current_poll_assertion = "FAIL (No response from status API during poll)"
                break
            
            final_poll_assertion_status = current_poll_assertion

            if i == OPTIMIZATION_MAX_POLLS - 1 and not (job_completed_successfully or job_was_cancelled) :
                LOG_BUFFER.append(f"Optimization job {optimization_job_id} timed out after {OPTIMIZATION_MAX_POLLS * OPTIMIZATION_POLL_INTERVAL}s with status {current_job_status_from_api}.")
                print(f"Optimization job {optimization_job_id} timed out polling.")
                final_poll_assertion_status = f"FAIL (Polling Timeout, last status: {current_job_status_from_api})"
        
        log_test(f"GET /optimize/status/{optimization_job_id} (Final Poll Result)", "GET", f"{BASE_URL}/optimize/status/{optimization_job_id}", response=response_status, assertion_status=final_poll_assertion_status)

        if job_completed_successfully: # Only fetch results if COMPLETED, not if cancelled
            response_results = make_request("GET", f"/optimize/results/{optimization_job_id}")
            assertion_status_results = "FAIL"
            if response_results and response_results.status_code == 200:
                try:
                    results_data = response_results.json()
                    if ("results" in results_data and isinstance(results_data["results"], list) and 
                        results_data.get("job_id") == optimization_job_id and "request_details" in results_data):
                        assertion_status_results = "PASS"
                        LOG_BUFFER.append(f"Optimization results for {optimization_job_id} count: {len(results_data['results'])}")
                    else:
                        assertion_status_results = "FAIL (Results structure incorrect or missing request_details)"
                except json.JSONDecodeError:
                    assertion_status_results = "FAIL (Results response not valid JSON)"
            elif response_results:
                 assertion_status_results = f"FAIL (Results API Error: {response_results.status_code}, {response_results.text[:100]})"
            log_test(f"GET /optimize/results/{optimization_job_id}", "GET", f"{BASE_URL}/optimize/results/{optimization_job_id}", response=response_results, assertion_status=assertion_status_results)

            if assertion_status_results == "PASS": 
                response_download = make_request("GET", f"/optimize/results/{optimization_job_id}/download")
                assertion_status_download = "FAIL"
                if response_download and response_download.status_code == 200:
                    if "text/csv" in response_download.headers.get("Content-Type", "") and len(response_download.content) > 0:
                        assertion_status_download = "PASS (CSV Downloaded)"
                        csv_filename = f"optimization_results_{optimization_job_id}.csv"
                        with open(csv_filename, 'wb') as f: f.write(response_download.content)
                        LOG_BUFFER.append(f"Downloaded optimization results CSV to {csv_filename}")
                    else:
                        assertion_status_download = f"FAIL (CSV not text/csv or empty. Type: {response_download.headers.get('Content-Type', '')})"
                elif response_download:
                     assertion_status_download = f"FAIL (Download API Error: {response_download.status_code}, {response_download.text[:100]})"
                log_test(f"GET /optimize/results/{optimization_job_id}/download", "GET", f"{BASE_URL}/optimize/results/{optimization_job_id}/download", response=response_download, assertion_status=assertion_status_download)
        elif job_was_cancelled:
            LOG_BUFFER.append(f"Skipping fetching/downloading optimization results as job {optimization_job_id} was CANCELLED.")
            print(f"Skipping fetching/downloading optimization results as job {optimization_job_id} was CANCELLED.")
            # Optionally, test that attempting to get results for a CANCELLED job behaves as expected (e.g. 400 or 200 with empty/partial results)
            response_results_cancelled = make_request("GET", f"/optimize/results/{optimization_job_id}")
            assertion_status_results_cancelled = "FAIL"
            if response_results_cancelled and response_results_cancelled.status_code == 200: # Server returns 200 with potentially empty/partial results
                try:
                    res_data = response_results_cancelled.json()
                    if res_data.get("job_id") == optimization_job_id and "results" in res_data and res_data.get("summary_stats",{}).get("status") == "CANCELLED":
                         assertion_status_results_cancelled = "PASS (Results endpoint handled CANCELLED job correctly)"
                    else:
                         assertion_status_results_cancelled = f"FAIL (Results endpoint for CANCELLED job bad structure. Summary: {res_data.get('summary_stats')})"
                except Exception as e:
                    assertion_status_results_cancelled = f"FAIL (Error parsing results for CANCELLED job: {e})"

            elif response_results_cancelled and response_results_cancelled.status_code == 400: # Or server returns 400 if no results for cancelled job
                 assertion_status_results_cancelled = "PASS (Results endpoint returned 400 for CANCELLED job as expected by one design)"
            elif response_results_cancelled:
                 assertion_status_results_cancelled = f"FAIL (Results for CANCELLED job unexpected status: {response_results_cancelled.status_code})"
            log_test(f"GET /optimize/results/{optimization_job_id} (for CANCELLED job)", "GET", f"{BASE_URL}/optimize/results/{optimization_job_id}", response=response_results_cancelled, assertion_status=assertion_status_results_cancelled)

        else: # Job failed or timed out
            LOG_BUFFER.append(f"Skipping fetching/downloading optimization results as job {optimization_job_id} did not complete successfully and was not cancelled.")
            print(f"Skipping fetching/downloading optimization results as job {optimization_job_id} did not complete successfully (not cancelled).")
            # Test attempting to cancel an already FAILED/COMPLETED job (if optimization_job_id is from a completed/failed run)
            # This might be tricky if the job ID is from a previously cancelled run.
            # This part is better tested if we have a definitively completed job ID.
            # For now, this specific sub-test (cancelling already completed/failed) might not trigger reliably here.

    # Test GET for non-existent job ID for status, results, download
    non_existent_get_id = str(uuid.uuid4()) # Different ID from cancel test
    for endpoint_suffix_get in ["status", "results", f"results/{non_existent_get_id}/download"]:
        url_path_get = f"/optimize/{endpoint_suffix_get}".replace(f"/{non_existent_get_id}/download", "/download") # simplify for download
        if "{}" in url_path_get: url_path_get = url_path_get.format(non_existent_get_id)
        elif "results/download" in url_path_get: url_path_get = f"/optimize/results/{non_existent_get_id}/download" # ensure ID for download

        response_nf_get = make_request("GET", url_path_get)
        assertion_status_nf_get = "FAIL"
        if response_nf_get and response_nf_get.status_code == 404:
            assertion_status_nf_get = "PASS (GET Handled non-existent job ID for " + endpoint_suffix_get.split('/')[0] + ")"
        elif response_nf_get:
             assertion_status_nf_get = f"FAIL (GET for non-existent job {endpoint_suffix_get.split('/')[0]} got {response_nf_get.status_code})"
        log_test(f"GET {url_path_get} (expected fail for non-existent job)", "GET", f"{BASE_URL}{url_path_get}", response=response_nf_get, assertion_status=assertion_status_nf_get)


# --- Main Execution Function ---
def main_test_runner():
    LOG_BUFFER.append(f"API Test Run Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    print(f"Starting API tests... Base URL: {BASE_URL}")
    print(f"Using default token: {DEFAULT_TEST_TOKEN} ({DEFAULT_TEST_EXCHANGE})")

    tests_to_run = [
        test_root,
        test_health,
        test_list_available_symbols,
        test_fetch_historical_data,
        test_list_available_strategies,
        test_run_backtest,
        test_chart_data_with_strategy, # Added new test
        test_optimization_flow # Now includes cancellation
    ]

    all_tests_passed_flag = True
    for test_func in tests_to_run:
        print(f"\nRunning test: {test_func.__name__}...")
        try:
            test_func()
            # Check the last log entry for this test's assertion status
            # This is a heuristic; a more robust way would be for test functions to return status.
            # Assuming log_test always appends assertion status last for a test block.
            # Find the block for the current test.
            # This relies on the fact that each test_func() call will make one or more log_test() calls.
            # The overall assertion for `all_tests_passed_flag` will be based on any "FAIL" in logs.
        except AssertionError as ae: # Should not happen if assertions are handled in log_test
            LOG_BUFFER.append(f"ASSERTION ERROR in {test_func.__name__}: {ae}")
            print(f"ASSERTION ERROR in {test_func.__name__}: {ae}")
            # all_tests_passed_flag = False # This will be caught by log buffer check
            log_test(test_func.__name__, "N/A", "N/A", note=f"Assertion error: {ae}", assertion_status="FAIL (Test Logic Assertion)")
        except Exception as e:
            LOG_BUFFER.append(f"UNEXPECTED ERROR in {test_func.__name__}: {e}")
            print(f"UNEXPECTED ERROR in {test_func.__name__}: {e}")
            # all_tests_passed_flag = False # This will be caught by log buffer check
            log_test(test_func.__name__, "N/A", "N/A", note=f"Unexpected error: {e}", assertion_status="FAIL (Test Error)")

    # Final check of all logged assertions
    # It's simpler to just check if "Assertion: FAIL" exists anywhere.
    # The `log_test` already prints detailed status.
    if any("Assertion: FAIL" in log_line for log_line in LOG_BUFFER):
        all_tests_passed_flag = False


    LOG_BUFFER.append(f"\nAPI Test Run Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    LOG_BUFFER.append(f"Overall Test Result: {'PASS' if all_tests_passed_flag else 'FAIL (Check assertions in log)'}")
    
    with open(OUTPUT_FILE, "w") as f:
        f.write("\n".join(LOG_BUFFER))
    
    print(f"\nAll tests completed. Output logged to {OUTPUT_FILE}")
    if not all_tests_passed_flag:
        print("WARNING: One or more tests FAILED. Please review the output log and console messages.")
    else:
        print("SUCCESS: All tests seem to have passed based on logged assertions!")

if __name__ == "__main__":
    main_test_runner()