# test.py (Corrected for Pylance warnings and with previous enhancements)
import requests
import json
import time
from datetime import datetime, timedelta
import uuid

# --- Configuration ---
BASE_URL = "http://localhost:8000"
OUTPUT_FILE = "api_test_output_v5.txt"
LOG_BUFFER = []

DEFAULT_TEST_TOKEN = "3456"
DEFAULT_TEST_EXCHANGE = "NSE"
DEFAULT_TIMEFRAME_DAY = "D"
EMA_CROSSOVER_STRATEGY_ID = "ema_crossover"

OPTIMIZATION_POLL_INTERVAL = 10
OPTIMIZATION_MAX_POLLS = 30

# --- Helper Functions ---
def log_test(endpoint_name, request_method, url, headers=None, body=None, response=None, note=None, assertion_status=None):
    log_entry = [ # Use a list to build messages for clarity
        f"Testing API Endpoint: {endpoint_name}",
        f"Request: {request_method} {url}"
    ]
    if headers:
        log_entry.append(f"Request Headers: {json.dumps(headers, indent=2)}")
    if body:
        log_entry.append(f"Request Body: {json.dumps(body, indent=2) if isinstance(body, dict) else body}")

    status_code_for_print = "N/A (No Response/Error)" # Default for console print
    if response is not None:
        status_code_for_print = response.status_code
        log_entry.append(f"Response Status: {response.status_code}")
        try:
            content_type = response.headers.get("Content-Type", "")
            if "text/csv" in content_type:
                log_entry.append("Response Body: CSV data (first 200 chars): " + response.text[:200])
            elif response.content: # Check if there's content before trying to parse as JSON
                log_entry.append(f"Response Body:\n{json.dumps(response.json(), indent=2)}")
            else:
                log_entry.append("Response Body: No content")
        except json.JSONDecodeError:
            log_entry.append(f"Response Body (Non-JSON):\n{response.text[:500]}{'...' if len(response.text) > 500 else ''}")
        except Exception as e:
            log_entry.append(f"Error processing response body: {e}")
    elif note: # Only show note in buffer if response is None
        log_entry.append(note)
    
    final_assertion_status = assertion_status if assertion_status else "UNKNOWN (No explicit assertion made)"
    # If no response object AND no assertion status was set by exception handling in make_request, it's likely a setup issue
    if response is None and not assertion_status: 
        final_assertion_status = "FAIL (No response from server or connection error)"

    log_entry.append(f"Assertion: {final_assertion_status}")
    log_entry.append("-" * 50)
    
    LOG_BUFFER.extend(log_entry) # Add all parts of the log entry at once
    print(f"Tested: {endpoint_name} - Status: {status_code_for_print} - Assertion: {final_assertion_status}")


def make_request(method, endpoint, **kwargs):
    url = f"{BASE_URL}{endpoint}"
    try:
        response = requests.request(method, url, **kwargs, timeout=90)
        return response # Return response object for all HTTP status codes
    except requests.exceptions.ConnectionError as e:
        # Note: log_test will be called by the test function if response is None
        return None
    except requests.exceptions.Timeout:
        return None
    except Exception as e: # Other requests-level exceptions
        print(f"UNEXPECTED REQUEST EXCEPTION for {method} {url}: {e}") # Print to console immediately
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
                    if data["symbols"]: # Further check if list is not empty
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
        if response_fail.status_code == 404: # Expecting 404 from server log for this case
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
                if ("data" in data and isinstance(data["data"], list) and
                        data.get("count") == len(data["data"])):
                    assertion_status = "PASS"
                else:
                    assertion_status = f"FAIL (Invalid data structure, status {response.status_code})"
            except json.JSONDecodeError:
                assertion_status = "FAIL (Response not valid JSON)"
        else:
            assertion_status = f"FAIL (Expected 200, got {response.status_code})"
    log_test("POST /data/historical", "POST", f"{BASE_URL}/data/historical", headers=headers, body=payload, response=response, assertion_status=assertion_status)

    payload_no_data = {
        "exchange": DEFAULT_TEST_EXCHANGE, "token": DEFAULT_TEST_TOKEN,
        "start_time": (end_date + timedelta(days=30)).strftime("%Y-%m-%d"),
        "end_time": (end_date + timedelta(days=60)).strftime("%Y-%m-%d"),
        "interval": DEFAULT_TIMEFRAME_DAY
    }
    response_no_data = make_request("POST", "/data/historical", json=payload_no_data, headers=headers)
    assertion_status_no_data = "FAIL"
    if response_no_data:
        if response_no_data.status_code == 200: # Backend should return 200 with count 0
            try:
                data_nd = response_no_data.json()
                if data_nd.get("count") == 0 and "No data found" in data_nd.get("message", ""):
                    assertion_status_no_data = "PASS"
                else:
                    assertion_status_no_data = f"FAIL (Expected count 0 & 'No data' msg, got count {data_nd.get('count')}, msg '{data_nd.get('message')}')"
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
                        if not ("id" in data["strategies"][0] and "name" in data["strategies"][0]):
                            assertion_status = "FAIL (Strategy object structure incorrect)"
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
        "timeframe": DEFAULT_TIMEFRAME_DAY,
        "parameters": {"fast_ema_period": 10, "slow_ema_period": 20},
        "initial_capital": 100000.0, "execution_price_type": "close"
    }
    headers = {"Content-Type": "application/json"}
    response = make_request("POST", "/backtest/run", json=payload, headers=headers)
    assertion_status = "FAIL"
    if response:
        if response.status_code == 200:
            try:
                data = response.json()
                if "net_pnl" in data and "total_trades" in data:
                    assertion_status = "PASS"
                else:
                    assertion_status = "FAIL (Missing key backtest result fields)"
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


def test_optimization_flow():
    optimization_job_id = None
    end_date_opt = datetime.now()
    start_date_opt = end_date_opt - timedelta(days=60) # Adjusted days

    payload_start = {
        "strategy_id": EMA_CROSSOVER_STRATEGY_ID,
        "exchange": DEFAULT_TEST_EXCHANGE, "token": DEFAULT_TEST_TOKEN,
        "start_date": start_date_opt.strftime("%Y-%m-%d"), "end_date": end_date_opt.strftime("%Y-%m-%d"),
        "timeframe": DEFAULT_TIMEFRAME_DAY,
        "parameter_ranges": [
            {"name": "fast_ema_period", "start_value": 5, "end_value": 10, "step": 5},
            {"name": "slow_ema_period", "start_value": 15, "end_value": 20, "step": 5}
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
                if optimization_job_id and job_data.get("status") in ["QUEUED", "PENDING"]:
                    assertion_status_start = "PASS (Job Queued)"
                    LOG_BUFFER.append(f"Optimization job started with ID: {optimization_job_id}")
                    print(f"Optimization job submitted... ID: {optimization_job_id}")
                else:
                    assertion_status_start = f"FAIL (Job ID or expected status missing. Status: {job_data.get('status')}, JobID: {optimization_job_id})"
            except json.JSONDecodeError:
                assertion_status_start = "FAIL (Start response not valid JSON)"
        else:
            assertion_status_start = f"FAIL (Expected 200, got {response_start.status_code}. Body: {response_start.text[:200]})"
    log_test("POST /optimize/start", "POST", f"{BASE_URL}/optimize/start", headers=headers, body=payload_start, response=response_start, assertion_status=assertion_status_start)

    if optimization_job_id:
        LOG_BUFFER.append(f"Polling for optimization job {optimization_job_id} status...")
        print(f"Polling for optimization job {optimization_job_id} status every {OPTIMIZATION_POLL_INTERVAL}s...")
        
        job_completed_successfully = False
        final_poll_assertion_status = "FAIL (Polling did not complete as expected)"

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
                        job_completed_successfully = False # Ensure this is set
                        break 
                    current_poll_assertion = "PASS (Job In Progress this poll)"
                except json.JSONDecodeError:
                    current_poll_assertion = "FAIL (Status response not valid JSON this poll)"
                    break
            elif response_status: # e.g. 500 error from status API
                 current_poll_assertion = f"FAIL (Status API error during poll: {response_status.status_code})"
                 break 
            else: # No response from make_request
                current_poll_assertion = "FAIL (No response from status API during poll)"
                break
            
            final_poll_assertion_status = current_poll_assertion # Store last meaningful poll status

            if i == OPTIMIZATION_MAX_POLLS - 1 and not job_completed_successfully :
                LOG_BUFFER.append(f"Optimization job {optimization_job_id} timed out after {OPTIMIZATION_MAX_POLLS * OPTIMIZATION_POLL_INTERVAL}s with status {current_job_status_from_api}.")
                print(f"Optimization job {optimization_job_id} timed out polling.")
                final_poll_assertion_status = f"FAIL (Polling Timeout, last status: {current_job_status_from_api})"
        
        log_test(f"GET /optimize/status/{optimization_job_id} (Final Poll Result)", "GET", f"{BASE_URL}/optimize/status/{optimization_job_id}", response=response_status, assertion_status=final_poll_assertion_status)

        if job_completed_successfully:
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
        else:
            LOG_BUFFER.append(f"Skipping fetching/downloading optimization results as job {optimization_job_id} did not complete successfully.")
            print(f"Skipping fetching/downloading optimization results as job {optimization_job_id} did not complete successfully.")
    
    non_existent_job_id = str(uuid.uuid4())
    for endpoint_suffix in ["status", "results", "results/{}/download".format(non_existent_job_id)]: # Corrected format
        url_path = f"/optimize/{endpoint_suffix}".replace("{}/download", "download") # simpler replacement
        if "{}" in url_path : url_path = url_path.format(non_existent_job_id) # Only format if placeholder exists
        
        response_nf = make_request("GET", url_path)
        assertion_status_nf = "FAIL"
        if response_nf and response_nf.status_code == 404:
            assertion_status_nf = "PASS (Handled non-existent job ID)"
        log_test(f"GET {url_path} (expected fail)", "GET", f"{BASE_URL}{url_path}", response=response_nf, assertion_status=assertion_status_nf)

# --- Main Execution Function ---
def main_test_runner():
    LOG_BUFFER.append(f"API Test Run Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    print(f"Starting API tests... Base URL: {BASE_URL}")
    print(f"Using default token: {DEFAULT_TEST_TOKEN} ({DEFAULT_TEST_EXCHANGE}), Timeframe: {DEFAULT_TIMEFRAME_DAY}")

    tests_to_run = [
        test_root,
        test_health,
        test_list_available_symbols,
        test_fetch_historical_data,
        test_list_available_strategies,
        test_run_backtest,
        test_optimization_flow 
    ]

    all_tests_passed_flag = True # Track overall status
    for test_func in tests_to_run:
        current_assertion_status_for_overall_check = "UNKNOWN"
        # Temporarily capture LOG_BUFFER length to isolate assertion status for this test_func
        # This is a bit of a workaround; ideally, test functions would return their status.
        # For now, we check the last assertion status logged by log_test.
        
        try:
            print(f"\nRunning test: {test_func.__name__}...")
            # Reset a temporary status for the current test function
            # The log_test function will set assertion_status which we want to capture
            
            # Call the test function
            test_func()

            # Check the last logged assertion status for this test
            # This is a heuristic: find the last "Assertion: " line for the current test's log block
            # A better way is for test functions to return a status or for log_test to update a shared status object.
            # For simplicity, if any "FAIL" is printed by log_test for this function, assume failure.
            # This is inferred by checking the console output from log_test for "Assertion: FAIL"
            
            # The `log_test` function now prints the assertion status.
            # We can't easily get it back here without modifying log_test to return it or test_func to return it.
            # So, the `all_tests_passed_flag` will be managed by exceptions for now.

        except AssertionError as ae:
            LOG_BUFFER.append(f"ASSERTION ERROR in {test_func.__name__}: {ae}")
            print(f"ASSERTION ERROR in {test_func.__name__}: {ae}")
            all_tests_passed_flag = False
        except Exception as e:
            LOG_BUFFER.append(f"UNEXPECTED ERROR in {test_func.__name__}: {e}")
            print(f"UNEXPECTED ERROR in {test_func.__name__}: {e}")
            all_tests_passed_flag = False
            # Log a FAIL assertion status if an unexpected error occurred
            log_test(test_func.__name__, "N/A", "N/A", note=f"Unexpected error: {e}", assertion_status="FAIL (Test Error)")


    # Check log buffer for any "Assertion: FAIL" to set all_tests_passed_flag
    # This is still a heuristic and less robust than explicit return values.
    for log_line in LOG_BUFFER:
        if log_line.startswith("Assertion: FAIL"):
            all_tests_passed_flag = False
            break

    LOG_BUFFER.append(f"\nAPI Test Run Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    LOG_BUFFER.append(f"Overall Test Result: {'PASS' if all_tests_passed_flag else 'FAIL (Check assertions in log)'}")
    
    with open(OUTPUT_FILE, "w") as f:
        f.write("\n".join(LOG_BUFFER))
    
    print(f"\nAll tests completed. Output logged to {OUTPUT_FILE}")
    if not all_tests_passed_flag:
        print("WARNING: Some tests may have failed or had issues. Please review the output log and console carefully.")

if __name__ == "__main__":
    main_test_runner()