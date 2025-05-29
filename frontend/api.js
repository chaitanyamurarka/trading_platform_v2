// api.js

/**
 * Fetches data from the API.
 * @param {string} endpoint - The API endpoint to call.
 * @param {string} method - HTTP method (GET, POST, etc.).
 * @param {object} [body=null] - The request body for POST/PUT requests.
 * @param {boolean} [isBlob=false] - Whether the expected response is a blob (e.g., for CSV download).
 * @returns {Promise<any>} - The JSON response or Blob from the API.
 */
async function fetchData(endpoint, method = 'GET', body = null, isBlob = false) {
    const url = `${API_BASE_URL}${endpoint}`;
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json',
            // Add any other headers like Authorization if needed in the future
        },
    };

    if (body && method !== 'GET') {
        options.body = JSON.stringify(body);
    }

    try {
        const response = await fetch(url, options);

        if (!response.ok) {
            let errorData;
            try {
                errorData = await response.json();
            } catch (e) {
                errorData = { message: response.statusText };
            }
            console.error(`API Error (${response.status}) for ${method} ${url}:`, errorData);
            throw { status: response.status, data: errorData };
        }

        if (isBlob) {
            return await response.blob();
        }
        // Handle cases where response might be empty (e.g., 204 No Content)
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) {
            return await response.json();
        } else {
            return await response.text(); // Or handle as appropriate if not JSON
        }

    } catch (error) {
        console.error(`Network or API call error for ${method} ${url}:`, error);
        // If it's our custom error object, rethrow it, otherwise wrap it
        if (error.status) {
            throw error;
        }
        throw { status: 'NETWORK_ERROR', data: { message: error.message || 'Network error occurred.' } };
    }
}

// --- API Service Functions ---

/**
 * Fetches available strategies.
 * @returns {Promise<object>} API response.
 */
async function getAvailableStrategies() {
    return fetchData('/strategies/available');
}

/**
 * Fetches available symbols for a given exchange.
 * @param {string} exchange - The exchange code (e.g., 'NSE').
 * @returns {Promise<object>} API response.
 */
async function getSymbolsForExchange(exchange) {
    return fetchData(`/symbols/${exchange.toUpperCase()}`);
}

/**
 * Fetches chart data (OHLC, indicators, trade markers).
 * @param {object} requestBody - The request payload for /chart_data_with_strategy.
 * @returns {Promise<object>} API response.
 */
async function getChartData(requestBody) {
    return fetchData('/chart_data_with_strategy', 'POST', requestBody);
}

/**
 * Starts an optimization job.
 * @param {object} requestBody - The request payload for /optimize/start.
 * @returns {Promise<object>} API response.
 */
async function startOptimization(requestBody) {
    return fetchData('/optimize/start', 'POST', requestBody);
}

/**
 * Gets the status of an optimization job.
 * @param {string} jobId - The ID of the optimization job.
 * @returns {Promise<object>} API response.
 */
async function getOptimizationStatus(jobId) {
    return fetchData(`/optimize/status/${jobId}`);
}

/**
 * Gets the results of an optimization job.
 * @param {string} jobId - The ID of the optimization job.
 * @returns {Promise<object>} API response.
 */
async function getOptimizationResults(jobId) {
    return fetchData(`/optimize/results/${jobId}`);
}

/**
 * Gets the best result of an optimization job.
 * @param {string} jobId - The ID of the optimization job.
 * @returns {Promise<object>} API response (OptimizationBestResultResponse).
 */
async function getOptimizationBestResultApi(jobId) { // New function
    return fetchData(`/optimize/results/best/${jobId}`);
}

/**
 * Downloads optimization results as CSV.
 * @param {string} jobId - The ID of the optimization job.
 * @returns {Promise<Blob>} CSV data as a Blob.
 */
async function downloadOptimizationCsv(jobId) {
    return fetchData(`/optimize/results/${jobId}/download`, 'GET', null, true);
}

/**
 * Cancels an optimization job.
 * @param {string} jobId - The ID of the optimization job.
 * @returns {Promise<object>} API response.
 */
async function cancelOptimization(jobId) {
    return fetchData(`/optimize/cancel/${jobId}`, 'POST');
}

// Health check - useful for initial setup verification
async function healthCheck() {
    return fetchData('/health');
}

// This function is called by backtesting.js
async function runBacktest(requestBody) {
    const response = await fetch(`${API_BASE_URL}/backtest/run`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
    });
    if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to parse error response' }));
        console.error("API Error in runBacktest:", response.status, errorData);
        // Throw an error that includes details from the backend if possible
        const err = new Error(`Backtest API request failed with status ${response.status}: ${errorData.detail || errorData.message || response.statusText}`);
        err.data = errorData; // Attach full error data
        throw err;
    }
    return response.json();
}