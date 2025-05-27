// optimization.js

// State specific to optimization page
let currentOptimizationSettings = { // Will be pre-filled from dashboard or defaults
    exchange: 'NSE',
    token: '3045',
    symbol: 'TATAMOTORS',
    timeframe: 'day',
    strategyId: 'ema_crossover',
    initialCapital: 100000,
    startDate: '',
    endDate: '',
    metricToOptimize: 'net_pnl',
    parameter_ranges: {}
};
// let optimizationJobId = null; // Already global from main script
// let optimizationStatusInterval = null; // Already global

// DOM Elements for Optimization page
let optExchangeSelect, optSymbolSelect, optTimeframeSelect, optStrategySelect,
    optInitialCapitalInput, optStartDateInput, optEndDateInput, optMetricSelect,
    optStrategyParamsContainer, startOptimizationButton, cancelOptimizationButton,
    optimizationStatusContainer, optimizationResultsContainer,
    optimizationResultsThead, optimizationResultsTbody, downloadCsvButton, bestResultSummaryDiv;


/**
 * Initializes the Optimization page.
 */
async function initOptimizationPage() {
    console.log("Initializing Optimization Page...");

    // Assign DOM elements
    optExchangeSelect = document.getElementById('optExchangeSelect');
    optSymbolSelect = document.getElementById('optSymbolSelect');
    optTimeframeSelect = document.getElementById('optTimeframeSelect');
    optStrategySelect = document.getElementById('optStrategySelect');
    optInitialCapitalInput = document.getElementById('optInitialCapital');
    optStartDateInput = document.getElementById('optStartDate');
    optEndDateInput = document.getElementById('optEndDate');
    optMetricSelect = document.getElementById('optMetricSelect');
    optStrategyParamsContainer = document.getElementById('optStrategyParamsContainer');
    startOptimizationButton = document.getElementById('startOptimizationButton');
    cancelOptimizationButton = document.getElementById('cancelOptimizationButton');
    optimizationStatusContainer = document.getElementById('optimizationStatusContainer');
    optimizationResultsContainer = document.getElementById('optimizationResultsContainer');
    optimizationResultsThead = document.getElementById('optimizationResultsThead');
    optimizationResultsTbody = document.getElementById('optimizationResultsTbody');
    downloadCsvButton = document.getElementById('downloadCsvButton');
    bestResultSummaryDiv = document.getElementById('bestResultSummary');


    setDefaultDateInputs(optStartDateInput, optEndDateInput, 365); // Default 1 year for optimization
    currentOptimizationSettings.startDate = optStartDateInput.value;
    currentOptimizationSettings.endDate = optEndDateInput.value;

    // Event Listeners
    startOptimizationButton.addEventListener('click', runOptimization);
    cancelOptimizationButton.addEventListener('click', handleCancelOptimization);
    downloadCsvButton.addEventListener('click', handleDownloadCsv);
    optExchangeSelect.addEventListener('change', handleOptExchangeChange);
    optSymbolSelect.addEventListener('change', () => { currentOptimizationSettings.token = optSymbolSelect.value; });
    optStrategySelect.addEventListener('change', updateOptStrategyParamsUI);


    showLoading(true);
    try {
        if (!availableStrategies || availableStrategies.length === 0) {
            const strategiesData = await getAvailableStrategies();
            if (strategiesData && strategiesData.strategies) {
                availableStrategies = strategiesData.strategies;
            }
        }
        populateSelect(optStrategySelect, availableStrategies, 'strategy_id', 'name', currentOptimizationSettings.strategyId);

        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        populateSelect(optExchangeSelect, exchanges, 'id', 'name', currentOptimizationSettings.exchange);

        await loadOptSymbols(currentOptimizationSettings.exchange, currentOptimizationSettings.token);
        updateOptStrategyParamsUI(); // Load param range inputs

        // Pre-fill other controls
        optTimeframeSelect.value = currentOptimizationSettings.timeframe;
        optInitialCapitalInput.value = currentOptimizationSettings.initialCapital;
        optMetricSelect.value = currentOptimizationSettings.metricToOptimize;
        if(currentOptimizationSettings.startDate) optStartDateInput.value = currentOptimizationSettings.startDate;
        if(currentOptimizationSettings.endDate) optEndDateInput.value = currentOptimizationSettings.endDate;


    } catch (error) {
        console.error("Error initializing optimization page:", error);
        showModal('Initialization Error', `Failed to initialize optimization page: ${error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}

async function loadOptSymbols(exchange, defaultToken = '') {
    showLoading(true);
    try {
        const data = await getSymbolsForExchange(exchange);
        const allSymbols = data.symbols || [];
        const filteredSymbols = allSymbols.filter(s => ['EQ', 'INDEX', 'FUTIDX', 'FUTSTK'].includes(s.instrument) || !s.instrument);

        populateSelect(optSymbolSelect, filteredSymbols, 'token', 'trading_symbol', defaultToken || (filteredSymbols.length > 0 ? filteredSymbols[0].token : ''));
        if (optSymbolSelect.value) {
            currentOptimizationSettings.token = optSymbolSelect.value;
        } else if (defaultToken) {
             currentOptimizationSettings.token = defaultToken;
             if (!filteredSymbols.some(s => s.token === defaultToken)) {
                const selectedSymbolObj = allSymbols.find(s => s.token === defaultToken);
                if(selectedSymbolObj){
                    const opt = document.createElement('option');
                    opt.value = defaultToken;
                    opt.textContent = selectedSymbolObj.trading_symbol;
                    opt.selected = true;
                    optSymbolSelect.appendChild(opt);
                }
             }
        }
    } catch (error) {
        console.error(`Error fetching symbols for optimization ${exchange}:`, error);
        showModal('Symbol Error', `Could not load symbols for optimization: ${error.data?.detail || error.message}`);
        optSymbolSelect.innerHTML = '<option value="">Error loading</option>';
    } finally {
        showLoading(false);
    }
}

function handleOptExchangeChange() {
    currentOptimizationSettings.exchange = optExchangeSelect.value;
    loadOptSymbols(currentOptimizationSettings.exchange);
}

function updateOptStrategyParamsUI() {
    currentOptimizationSettings.strategyId = optStrategySelect.value;
    const strategyConfig = availableStrategies.find(s => s.strategy_id === currentOptimizationSettings.strategyId);
    if (strategyConfig && optStrategyParamsContainer) {
        // For optimization, we need min/max/step inputs
        // Default values for ranges can come from strategyConfig.parameters (min_value, max_value, step, default_value)
        const paramRangesToLoad = {};
        strategyConfig.parameters.forEach(p => {
            paramRangesToLoad[p.name] = {
                min: p.min_value !== null ? p.min_value : (p.default_value - (p.step || 1) * 5), // Example default range logic
                max: p.max_value !== null ? p.max_value : (p.default_value + (p.step || 1) * 5),
                step: p.step !== null ? p.step : 1
            };
             // Ensure min < max
            if (paramRangesToLoad[p.name].min >= paramRangesToLoad[p.name].max) {
                paramRangesToLoad[p.name].min = p.default_value;
                paramRangesToLoad[p.name].max = p.default_value + (p.step || 1);
                if (paramRangesToLoad[p.name].min >= paramRangesToLoad[p.name].max && p.type !== 'boolean') { // one last check for safety
                     paramRangesToLoad[p.name].max = paramRangesToLoad[p.name].min + (p.step || 1);
                }
            }
        });
        createStrategyParamsInputs(optStrategyParamsContainer, strategyConfig.parameters, paramRangesToLoad, true);
    } else if (optStrategyParamsContainer) {
        optStrategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Select a strategy.</p>';
    }
}

async function runOptimization() {
    showLoading(true);
    optimizationStatusContainer.classList.add('hidden');
    optimizationResultsContainer.classList.add('hidden');
    if (optimizationStatusInterval) clearInterval(optimizationStatusInterval);

    // Collect parameters
    currentOptimizationSettings.exchange = optExchangeSelect.value;
    currentOptimizationSettings.token = optSymbolSelect.value;
    currentOptimizationSettings.timeframe = optTimeframeSelect.value;
    currentOptimizationSettings.strategyId = optStrategySelect.value;
    currentOptimizationSettings.initialCapital = parseFloat(optInitialCapitalInput.value);
    currentOptimizationSettings.startDate = optStartDateInput.value;
    currentOptimizationSettings.endDate = optEndDateInput.value;
    currentOptimizationSettings.metricToOptimize = optMetricSelect.value;

    const strategyConfig = availableStrategies.find(s => s.strategy_id === currentOptimizationSettings.strategyId);
    if (strategyConfig) {
        currentOptimizationSettings.parameter_ranges = getStrategyParamsValues(strategyConfig.parameters, true);
    }

    const requestBody = {
        strategy_id: currentOptimizationSettings.strategyId,
        exchange: currentOptimizationSettings.exchange,
        token: currentOptimizationSettings.token,
        start_date: currentOptimizationSettings.startDate,
        end_date: currentOptimizationSettings.endDate,
        timeframe: currentOptimizationSettings.timeframe,
        initial_capital: currentOptimizationSettings.initialCapital,
        parameter_ranges: currentOptimizationSettings.parameter_ranges,
        metric_to_optimize: currentOptimizationSettings.metricToOptimize
    };

    try {
        const job = await startOptimization(requestBody);
        console.log("Optimization Job Started:", job);
        if (job && job.job_id) {
            optimizationJobId = job.job_id;
            updateOptimizationProgressUI(job); // Initial status
            optimizationStatusContainer.classList.remove('hidden');
            startOptimizationButton.classList.add('hidden'); // Hide start, show cancel

            // Start polling for status
            optimizationStatusInterval = setInterval(async () => {
                try {
                    const status = await getOptimizationStatus(optimizationJobId);
                    updateOptimizationProgressUI(status);
                    if (status.status === 'COMPLETED' || status.status === 'FAILED' || status.status === 'CANCELLED') {
                        clearInterval(optimizationStatusInterval);
                        optimizationStatusInterval = null;
                        startOptimizationButton.classList.remove('hidden');
                        cancelOptimizationButton.classList.add('hidden');
                        if (status.status === 'COMPLETED' || (status.status === 'CANCELLED' && status.current_iteration > 0) ) {
                            fetchAndDisplayOptimizationResults(optimizationJobId);
                        } else if (status.status === 'FAILED') {
                            showModal('Optimization Failed', status.message || 'The optimization job failed.');
                        }
                    }
                } catch (pollError) {
                    console.error("Error polling optimization status:", pollError);
                    clearInterval(optimizationStatusInterval);
                    optimizationStatusInterval = null;
                    startOptimizationButton.classList.remove('hidden');
                    cancelOptimizationButton.classList.add('hidden');
                    // Optionally show error in status UI
                    const errorStatus = { job_id: optimizationJobId, status: 'ERROR', message: 'Failed to poll status.', progress_percentage: 0 };
                    updateOptimizationProgressUI(errorStatus);
                }
            }, 3000); // Poll every 3 seconds
        } else {
            showModal('Optimization Error', `Failed to start optimization: ${job.message || 'Unknown error'}`);
        }
    } catch (error) {
        console.error("Error starting optimization:", error);
        showModal('Optimization Start Error', `Failed to start optimization: ${error.data?.detail || error.data?.message || error.message}`);
    } finally {
        // showLoading(false); // Loading is for initial call, polling handles UI updates
    }
     showLoading(false); // Ensure loading is hidden after the initial start attempt
}

async function fetchAndDisplayOptimizationResults(jobId) {
    showLoading(true);
    try {
        const resultsData = await getOptimizationResults(jobId);
        console.log("Optimization Results Data:", resultsData);
        if (resultsData && resultsData.results) {
            // Determine dynamic headers for the table
            let paramKeys = [];
            let metricKeys = [];
            if (resultsData.results.length > 0) {
                paramKeys = Object.keys(resultsData.results[0].parameters || {});
                metricKeys = Object.keys(resultsData.results[0].performance_metrics || {});
            } else if (resultsData.request_details && resultsData.request_details.parameter_ranges) {
                // Fallback to keys from request if results are empty but job completed
                paramKeys = Object.keys(resultsData.request_details.parameter_ranges);
                // Metric keys might be harder to guess if no results, but common ones can be listed
                // For now, rely on first result or leave empty if no results.
            }


            populateOptimizationResultsTable(optimizationResultsTbody, optimizationResultsThead, resultsData.results, paramKeys, metricKeys);
            displayBestOptimizationResult(bestResultSummaryDiv, resultsData.best_result, resultsData.request_details.metric_to_optimize);
            optimizationResultsContainer.classList.remove('hidden');
        } else {
            showModal('Optimization Results', 'No results data found for this optimization job.');
        }
    } catch (error) {
        console.error("Error fetching optimization results:", error);
        showModal('Results Error', `Failed to fetch optimization results: ${error.data?.detail || error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}

async function handleCancelOptimization() {
    if (!optimizationJobId) {
        showModal('Error', 'No active optimization job to cancel.');
        return;
    }
    showLoading(true);
    try {
        const response = await cancelOptimization(optimizationJobId);
        showModal('Cancel Request', response.message || `Cancellation status: ${response.status}`);
        if (response.status !== 'job_not_found' && response.status !== 'error_cannot_cancel_completed' && response.status !== 'already_completed' && response.status !== 'already_failed') {
            // Status will update via polling if successful
        } else {
            // If it's definitively not cancellable, stop polling and reset UI
            if (optimizationStatusInterval) clearInterval(optimizationStatusInterval);
            optimizationStatusInterval = null;
            startOptimizationButton.classList.remove('hidden');
            cancelOptimizationButton.classList.add('hidden');
        }
    } catch (error) {
        console.error("Error cancelling optimization:", error);
        showModal('Cancel Error', `Failed to cancel optimization: ${error.data?.detail || error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}

async function handleDownloadCsv() {
    if (!optimizationJobId) {
        showModal('Error', 'No optimization job ID available to download results.');
        return;
    }
    showLoading(true);
    try {
        const blob = await downloadOptimizationCsv(optimizationJobId);
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = `optimization_results_${optimizationJobId}.csv`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
    } catch (error) {
        console.error("Error downloading CSV:", error);
        showModal('Download Error', `Failed to download CSV: ${error.data?.detail || error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}
