// optimization.js

let currentOptimizationSettings = {
    exchange: 'NSE', token: '3045', symbol: 'TATAMOTORS', timeframe: 'day',
    strategyId: 'ema_crossover', initialCapital: 100000,
    startDate: '', endDate: '', metricToOptimize: 'net_pnl', parameter_ranges: {}
};
// optimizationJobId and optimizationStatusInterval are global (from ui.js or main script)

let optExchangeSelect, optSymbolSelect, optTimeframeSelect, optStrategySelect,
    optInitialCapitalInput, optStartDateInput, optEndDateInput, optMetricSelect,
    optStrategyParamsContainer, startOptimizationButton, cancelOptimizationButton,
    optimizationStatusContainer, optimizationResultsContainer,
    optimizationResultsThead, optimizationResultsTbody, downloadCsvButton, bestResultSummaryDiv;

async function initOptimizationPage() {
    console.log("Initializing Optimization Page...");
    optExchangeSelect = document.getElementById('optExchangeSelect');
    optSymbolSelect = document.getElementById('optSymbolSelect');
    optTimeframeSelect = document.getElementById('optTimeframeSelect');
    optStrategySelect = document.getElementById('optStrategySelect');
    optInitialCapitalInput = document.getElementById('optInitialCapital');
    optStartDateInput = document.getElementById('optStartDate');
    optEndDateInput = document.getElementById('optEndDate');
    optMetricSelect = document.getElementById('optMetricSelect');
    optStrategyParamsContainer = document.getElementById('optStrategyParamsContainer'); // This is the container for param range inputs
    startOptimizationButton = document.getElementById('startOptimizationButton');
    cancelOptimizationButton = document.getElementById('cancelOptimizationButton');
    optimizationStatusContainer = document.getElementById('optimizationStatusContainer');
    optimizationResultsContainer = document.getElementById('optimizationResultsContainer');
    optimizationResultsThead = document.getElementById('optimizationResultsThead');
    optimizationResultsTbody = document.getElementById('optimizationResultsTbody');
    downloadCsvButton = document.getElementById('downloadCsvButton');
    bestResultSummaryDiv = document.getElementById('bestResultSummary');

    setDefaultDateInputs(optStartDateInput, optEndDateInput, 365);
    currentOptimizationSettings.startDate = optStartDateInput.value;
    currentOptimizationSettings.endDate = optEndDateInput.value;

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
            if (strategiesData && strategiesData.strategies) availableStrategies = strategiesData.strategies;
        }
        // Corrected: Use 'id' as valueKey for strategies
        populateSelect(optStrategySelect, availableStrategies, 'id', 'name', currentOptimizationSettings.strategyId);

        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        populateSelect(optExchangeSelect, exchanges, 'id', 'name', currentOptimizationSettings.exchange);

        await loadOptSymbols(currentOptimizationSettings.exchange, currentOptimizationSettings.token);
        updateOptStrategyParamsUI(); // Load param range inputs

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
                    opt.value = defaultToken; opt.textContent = selectedSymbolObj.trading_symbol; opt.selected = true;
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
    // Corrected: Find strategy by 'id'
    const strategyConfig = availableStrategies.find(s => s.id === currentOptimizationSettings.strategyId);
    if (strategyConfig && optStrategyParamsContainer) { // optStrategyParamsContainer is the direct container for inputs
        const paramRangesToLoad = {};
        strategyConfig.parameters.forEach(p => {
            // Use provided min/max/step if available, otherwise derive from default
            const defaultVal = p.type === 'integer' ? parseInt(p.default_value) : (p.type === 'float' ? parseFloat(p.default_value) : p.default_value);
            const stepVal = p.step ? (p.type === 'integer' ? parseInt(p.step) : parseFloat(p.step)) : 1;

            paramRangesToLoad[p.name] = {
                min: p.min_value !== null && p.min_value !== undefined ? (p.type === 'integer' ? parseInt(p.min_value) : parseFloat(p.min_value)) : (defaultVal - stepVal * 2),
                max: p.max_value !== null && p.max_value !== undefined ? (p.type === 'integer' ? parseInt(p.max_value) : parseFloat(p.max_value)) : (defaultVal + stepVal * 2),
                step: stepVal
            };
            // Ensure min < max, especially for derived values
            if (paramRangesToLoad[p.name].min >= paramRangesToLoad[p.name].max && p.type !== 'boolean') {
                 paramRangesToLoad[p.name].min = defaultVal; // Reset to default
                 paramRangesToLoad[p.name].max = defaultVal + stepVal; // Ensure max is greater
                 if (paramRangesToLoad[p.name].min >= paramRangesToLoad[p.name].max) { // Final safety for step=0 or odd cases
                    paramRangesToLoad[p.name].max = paramRangesToLoad[p.name].min + (p.step || 1); // Add raw step if available
                 }
            }
        });
        // The container itself is '.parameter-grid', not a child of it.
        createStrategyParamsInputs(optStrategyParamsContainer.querySelector('.parameter-grid') || optStrategyParamsContainer, strategyConfig.parameters, paramRangesToLoad, true); // true for range inputs
    } else if (optStrategyParamsContainer) {
        (optStrategyParamsContainer.querySelector('.parameter-grid') || optStrategyParamsContainer).innerHTML = '<p class="text-sm text-gray-400">Select a strategy.</p>';
    }
}

async function runOptimization() {
    showLoading(true);
    optimizationStatusContainer.classList.add('hidden');
    optimizationResultsContainer.classList.add('hidden');
    if (optimizationStatusInterval) clearInterval(optimizationStatusInterval);

    currentOptimizationSettings.exchange = optExchangeSelect.value;
    currentOptimizationSettings.token = optSymbolSelect.value;
    currentOptimizationSettings.timeframe = optTimeframeSelect.value;
    currentOptimizationSettings.strategyId = optStrategySelect.value;
    currentOptimizationSettings.initialCapital = parseFloat(optInitialCapitalInput.value);
    currentOptimizationSettings.startDate = optStartDateInput.value;
    currentOptimizationSettings.endDate = optEndDateInput.value;
    currentOptimizationSettings.metricToOptimize = optMetricSelect.value;

    // Corrected: Find strategy by 'id'
    const strategyConfig = availableStrategies.find(s => s.id === currentOptimizationSettings.strategyId);
    if (strategyConfig) {
        currentOptimizationSettings.parameter_ranges = getStrategyParamsValues(strategyConfig.parameters, true); // true for range inputs
    } else {
        currentOptimizationSettings.parameter_ranges = {}; // Clear if no valid strategy
    }

    const requestBody = {
        strategy_id: currentOptimizationSettings.strategyId,
        exchange: currentOptimizationSettings.exchange, token: currentOptimizationSettings.token,
        start_date: currentOptimizationSettings.startDate, end_date: currentOptimizationSettings.endDate,
        timeframe: currentOptimizationSettings.timeframe, initial_capital: currentOptimizationSettings.initialCapital,
        parameter_ranges: currentOptimizationSettings.parameter_ranges,
        metric_to_optimize: currentOptimizationSettings.metricToOptimize
    };

    try {
        const job = await startOptimization(requestBody);
        console.log("Optimization Job Started:", job);
        if (job && job.job_id) {
            optimizationJobId = job.job_id;
            updateOptimizationProgressUI(job); 
            optimizationStatusContainer.classList.remove('hidden');
            startOptimizationButton.classList.add('hidden'); 
            cancelOptimizationButton.classList.remove('hidden');

            optimizationStatusInterval = setInterval(async () => {
                try {
                    const status = await getOptimizationStatus(optimizationJobId);
                    updateOptimizationProgressUI(status);
                    if (status.status === 'COMPLETED' || status.status === 'FAILED' || status.status === 'CANCELLED') {
                        clearInterval(optimizationStatusInterval); optimizationStatusInterval = null;
                        startOptimizationButton.classList.remove('hidden'); cancelOptimizationButton.classList.add('hidden');
                        if (status.status === 'COMPLETED' || (status.status === 'CANCELLED' && status.current_iteration > 0) ) {
                            fetchAndDisplayOptimizationResults(optimizationJobId);
                        } else if (status.status === 'FAILED') {
                            showModal('Optimization Failed', status.message || 'The optimization job failed.');
                        }
                    }
                } catch (pollError) {
                    console.error("Error polling optimization status:", pollError);
                    clearInterval(optimizationStatusInterval); optimizationStatusInterval = null;
                    startOptimizationButton.classList.remove('hidden'); cancelOptimizationButton.classList.add('hidden');
                    updateOptimizationProgressUI({ job_id: optimizationJobId, status: 'ERROR', message: 'Failed to poll status.', progress_percentage: 0 });
                }
            }, 3000); 
        } else {
            showModal('Optimization Error', `Failed to start optimization: ${job.message || job.detail || 'Unknown error'}`);
            showLoading(false); // Hide loading if job start fails immediately
        }
    } catch (error) {
        console.error("Error starting optimization:", error);
        showModal('Optimization Start Error', `Failed to start optimization: ${error.data?.detail || error.data?.message || error.message}`);
        showLoading(false); // Hide loading on catch
    }
    // Do not hide loading here if polling starts, polling will manage UI
    // showLoading(false); // Removed this line
}
// Ensure showLoading(false) is called if the 'try' block for startOptimization itself throws before polling can start.
// Added showLoading(false) in the catch blocks for startOptimization and if job.job_id is not found.


async function fetchAndDisplayOptimizationResults(jobId) {
    showLoading(true);
    try {
        const resultsData = await getOptimizationResults(jobId);
        console.log("Optimization Results Data:", resultsData);
        if (resultsData && resultsData.results) {
            let paramKeys = [], metricKeys = [];
            if (resultsData.results.length > 0) {
                paramKeys = Object.keys(resultsData.results[0].parameters || {});
                metricKeys = Object.keys(resultsData.results[0].performance_metrics || {});
            } else if (resultsData.request_details && resultsData.request_details.parameter_ranges) {
                paramKeys = Object.keys(resultsData.request_details.parameter_ranges);
            }
            populateOptimizationResultsTable(optimizationResultsTbody, optimizationResultsThead, resultsData.results, paramKeys, metricKeys);
            displayBestOptimizationResult(bestResultSummaryDiv, resultsData.best_result, resultsData.request_details.metric_to_optimize);
            optimizationResultsContainer.classList.remove('hidden');
            downloadCsvButton.classList.remove('hidden'); // Show download button
        } else {
            showModal('Optimization Results', 'No results data found for this optimization job.');
            downloadCsvButton.classList.add('hidden'); // Hide if no results
        }
    } catch (error) {
        console.error("Error fetching optimization results:", error);
        showModal('Results Error', `Failed to fetch optimization results: ${error.data?.detail || error.data?.message || error.message}`);
        downloadCsvButton.classList.add('hidden');
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
        // Polling will eventually stop and update UI, but can force UI update here for some statuses
        if (response.status === 'job_not_found' || response.status === 'error_cannot_cancel_completed' || 
            response.status === 'already_completed' || response.status === 'already_failed' || response.status === 'cancelled') {
            if (optimizationStatusInterval) clearInterval(optimizationStatusInterval);
            optimizationStatusInterval = null;
            startOptimizationButton.classList.remove('hidden');
            cancelOptimizationButton.classList.add('hidden');
            // If cancelled and some results might exist, try fetching
            if (response.status === 'cancelled' && (response.current_iteration > 0 || (typeof response.message === 'string' && response.message.includes("some results might be available")) ) ) {
                 fetchAndDisplayOptimizationResults(optimizationJobId);
            }
        }
    } catch (error) {
        console.error("Error cancelling optimization:", error);
        showModal('Cancel Error', `Failed to cancel optimization: ${error.data?.detail || error.data?.message || error.message}`);
        // Restore buttons if cancel API fails
        startOptimizationButton.classList.remove('hidden');
        cancelOptimizationButton.classList.add('hidden');
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
        a.style.display = 'none'; a.href = url;
        a.download = `optimization_results_${optimizationJobId}.csv`;
        document.body.appendChild(a); a.click();
        window.URL.revokeObjectURL(url); a.remove();
    } catch (error) {
        console.error("Error downloading CSV:", error);
        showModal('Download Error', `Failed to download CSV: ${error.data?.detail || error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}