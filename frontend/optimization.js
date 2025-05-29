// optimization.js

let currentOptimizationSettings = {
    exchange: 'NSE', token: '3456', symbol: 'TATAMOTORS', timeframe: 'day', // Default timeframe
    strategyId: 'ema_crossover', initialCapital: 100000,
    startDate: '', endDate: '', metricToOptimize: 'net_pnl', parameter_ranges: {}
};
// optimizationJobId and optimizationStatusInterval are global (from ui.js or main script or declared in index.html)
// let optimizationJobId = null; // Ensure these are declared if not already
// let optimizationStatusInterval = null; // Ensure these are declared if not already


let optExchangeSelect, optSymbolSelect, optTimeframeSelect, optStrategySelect,
    optInitialCapitalInput, optStartDateInput, optEndDateInput, optMetricSelect,
    optStrategyParamsGridContainer, // Changed from optStrategyParamsContainer to be more specific
    startOptimizationButton, cancelOptimizationButton,
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
    // Get the direct grid container
    const strategyParamsOuterContainer = document.getElementById('optStrategyParamsContainer');
    if (strategyParamsOuterContainer) {
        optStrategyParamsGridContainer = strategyParamsOuterContainer.querySelector('.parameter-grid');
    }
    startOptimizationButton = document.getElementById('startOptimizationButton');
    cancelOptimizationButton = document.getElementById('cancelOptimizationButton');
    optimizationStatusContainer = document.getElementById('optimizationStatusContainer');
    optimizationResultsContainer = document.getElementById('optimizationResultsContainer');
    optimizationResultsThead = document.getElementById('optimizationResultsThead');
    optimizationResultsTbody = document.getElementById('optimizationResultsTbody');
    downloadCsvButton = document.getElementById('downloadCsvButton');
    bestResultSummaryDiv = document.getElementById('bestResultSummary');

    // Use global currentOptimizationSettings populated from dashboard/backtest if available
    // currentSymbolData or currentBacktestSettings might be copied to currentOptimizationSettings by loadPage in index.html
    
    setDefaultDateInputs(optStartDateInput, optEndDateInput, 365); // Default to 1 year back
    currentOptimizationSettings.startDate = optStartDateInput.value; // Update from default
    currentOptimizationSettings.endDate = optEndDateInput.value; // Update from default

    startOptimizationButton.addEventListener('click', runOptimization);
    cancelOptimizationButton.addEventListener('click', handleCancelOptimization);
    downloadCsvButton.addEventListener('click', handleDownloadCsv);
    optExchangeSelect.addEventListener('change', handleOptExchangeChange);
    optSymbolSelect.addEventListener('change', () => { 
        currentOptimizationSettings.token = optSymbolSelect.value; 
        const selectedOption = optSymbolSelect.options[optSymbolSelect.selectedIndex];
        currentOptimizationSettings.symbol = selectedOption ? selectedOption.text : optSymbolSelect.value;
    });
    optStrategySelect.addEventListener('change', updateOptStrategyParamsUI);
    optTimeframeSelect.addEventListener('change', () => { currentOptimizationSettings.timeframe = optTimeframeSelect.value; });
    optInitialCapitalInput.addEventListener('change', () => { currentOptimizationSettings.initialCapital = parseFloat(optInitialCapitalInput.value); });
    optMetricSelect.addEventListener('change', () => { currentOptimizationSettings.metricToOptimize = optMetricSelect.value; });
    optStartDateInput.addEventListener('change', () => { currentOptimizationSettings.startDate = optStartDateInput.value; });
    optEndDateInput.addEventListener('change', () => { currentOptimizationSettings.endDate = optEndDateInput.value; });


    showLoading(true);
    try {
        if (!availableStrategies || availableStrategies.length === 0) {
            const strategiesData = await getAvailableStrategies();
            if (strategiesData && strategiesData.strategies) {
                 window.availableStrategies = strategiesData.strategies; // Ensure global is updated
            } else {
                window.availableStrategies = [];
            }
        }
        
        populateSelect(optStrategySelect, availableStrategies, 'id', 'name', currentOptimizationSettings.strategyId);
        if (availableStrategies.length > 0 && !currentOptimizationSettings.strategyId) {
            currentOptimizationSettings.strategyId = availableStrategies[0].id; // Default to first if not set
        }
        optStrategySelect.value = currentOptimizationSettings.strategyId;


        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        populateSelect(optExchangeSelect, exchanges, 'id', 'name', currentOptimizationSettings.exchange);
        optExchangeSelect.value = currentOptimizationSettings.exchange;

        await loadOptSymbols(currentOptimizationSettings.exchange, currentOptimizationSettings.token);
        // optSymbolSelect.value will be set by loadOptSymbols

        optTimeframeSelect.value = currentOptimizationSettings.timeframe;
        optInitialCapitalInput.value = currentOptimizationSettings.initialCapital;
        optMetricSelect.value = currentOptimizationSettings.metricToOptimize;
        if(currentOptimizationSettings.startDate) optStartDateInput.value = currentOptimizationSettings.startDate;
        if(currentOptimizationSettings.endDate) optEndDateInput.value = currentOptimizationSettings.endDate;
        
        // This needs to be called after strategy and symbols are potentially set
        await updateOptStrategyParamsUI(); 

    } catch (error) {
        console.error("Error initializing optimization page:", error);
        showModal('Initialization Error', `Failed to initialize optimization page: ${error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}

async function loadOptSymbols(exchange, defaultToken = '') {
    showLoading(true);
    optSymbolSelect.innerHTML = '<option value="">Loading symbols...</option>';
    try {
        const data = await getSymbolsForExchange(exchange);
        const allSymbols = data.symbols || [];
        // Broader filter for optimization, can be adjusted
        const filteredSymbols = allSymbols.filter(s => ['EQ', 'INDEX', 'FUTIDX', 'FUTSTK', 'OPTIDX', 'OPTSTK'].includes(s.instrument) || !s.instrument); 
        populateSelect(optSymbolSelect, filteredSymbols, 'token', 'trading_symbol', defaultToken || (filteredSymbols.length > 0 ? filteredSymbols[0].token : ''));
        
        if (optSymbolSelect.value) {
            currentOptimizationSettings.token = optSymbolSelect.value;
            const selectedOption = optSymbolSelect.options[optSymbolSelect.selectedIndex];
            currentOptimizationSettings.symbol = selectedOption ? selectedOption.text : optSymbolSelect.value;
        } else if (defaultToken) {
             currentOptimizationSettings.token = defaultToken;
             if (!filteredSymbols.some(s => s.token === defaultToken)) { // If defaultToken was filtered out
                const selectedSymbolObj = allSymbols.find(s => s.token === defaultToken);
                if(selectedSymbolObj){
                    const opt = document.createElement('option');
                    opt.value = defaultToken; 
                    opt.textContent = selectedSymbolObj.trading_symbol; 
                    opt.selected = true;
                    optSymbolSelect.appendChild(opt);
                    currentOptimizationSettings.symbol = selectedSymbolObj.trading_symbol;
                } else {
                     currentOptimizationSettings.symbol = defaultToken; // Fallback
                }
             } else {
                const selectedOption = optSymbolSelect.options[optSymbolSelect.selectedIndex];
                currentOptimizationSettings.symbol = selectedOption ? selectedOption.text : defaultToken;
             }
        } else if (filteredSymbols.length > 0) {
            optSymbolSelect.value = filteredSymbols[0].token;
            currentOptimizationSettings.token = filteredSymbols[0].token;
            currentOptimizationSettings.symbol = filteredSymbols[0].trading_symbol;
        } else {
            currentOptimizationSettings.token = '';
            currentOptimizationSettings.symbol = '';
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
    // Reset token and symbol as they belong to the previous exchange
    currentOptimizationSettings.token = ''; 
    currentOptimizationSettings.symbol = '';
    loadOptSymbols(currentOptimizationSettings.exchange); // This will update token and symbol
}

async function updateOptStrategyParamsUI() {
    currentOptimizationSettings.strategyId = optStrategySelect.value;
    const strategyConfig = availableStrategies.find(s => s.id === currentOptimizationSettings.strategyId);

    if (!optStrategyParamsGridContainer) {
        console.error("optStrategyParamsGridContainer is not found in the DOM.");
        return;
    }
    
    if (strategyConfig && strategyConfig.parameters) {
        const paramRangesToLoad = {};
        strategyConfig.parameters.forEach(p => {
            const type = p.type.toLowerCase();
            let defaultVal, stepVal, minVal, maxVal;

            // Determine step value
            if (p.step !== null && p.step !== undefined && parseFloat(p.step) > 0) {
                stepVal = (type === 'integer' || type === 'int') ? parseInt(p.step) : parseFloat(p.step);
            } else {
                stepVal = (type === 'integer' || type === 'int') ? 1 : 0.01; // Default step
            }

            // Determine default value for deriving ranges if min/max are absent
            if (p.default_value !== null && p.default_value !== undefined) {
                defaultVal = (type === 'integer' || type === 'int') ? parseInt(p.default_value) :
                             (type === 'float' ? parseFloat(p.default_value) : p.default_value);
            } else { // Fallback if default_value is also missing (should not happen for well-defined strategies)
                defaultVal = (type === 'integer' || type === 'int') ? 10 : 1.0;
            }
            
            // Determine min value for the range input
            if (p.min_value !== null && p.min_value !== undefined) {
                minVal = (type === 'integer' || type === 'int') ? parseInt(p.min_value) : parseFloat(p.min_value);
            } else {
                // Fallback for min: default - 2*step, or a sensible floor like 0 or 1
                 minVal = (type === 'integer' || type === 'int') ? Math.max(1, defaultVal - stepVal * 5) : Math.max(0.01, defaultVal - stepVal * 5);
                 if (p.name.toLowerCase().includes('period') || p.name.toLowerCase().includes('length')) {
                    minVal = Math.max(1, minVal);
                 } else if (p.name.toLowerCase().includes('_pct')) {
                    minVal = Math.max(0.01, minVal); // Percentages shouldn't be negative
                 }
            }

            // Determine max value for the range input
            if (p.max_value !== null && p.max_value !== undefined) {
                maxVal = (type === 'integer' || type === 'int') ? parseInt(p.max_value) : parseFloat(p.max_value);
            } else {
                // Fallback for max: default + 2*step, or a sensible ceiling
                maxVal = (type === 'integer' || type === 'int') ? (defaultVal + stepVal * 10) : (defaultVal + stepVal * 10);
                if (p.name.toLowerCase().includes('_pct')) {
                     maxVal = Math.min(100.0, maxVal); // Cap percentages at 100
                }
            }
            
            // Ensure min < max, and step is positive
            if (minVal >= maxVal) {
                 maxVal = minVal + stepVal * 5; // Ensure max is greater than min
                 if (minVal >= maxVal && stepVal > 0) maxVal = minVal + stepVal; // Handle edge if stepVal is too small
                 else if (minVal >= maxVal) maxVal = minVal + ((type === 'integer' || type === 'int') ? 1 : 0.1); // Absolute fallback
            }
             if (stepVal <= 0) { // Ensure step is positive
                stepVal = (type === 'integer' || type === 'int') ? 1 : 0.01;
            }


            paramRangesToLoad[p.name] = {
                min: minVal,
                max: maxVal,
                step: stepVal,
                // include the actual default for display/reference if needed by createStrategyParamsInputs
                default_value: defaultVal 
            };
        });
        createStrategyParamsInputs(optStrategyParamsGridContainer, strategyConfig.parameters, paramRangesToLoad, true); // true for range inputs
    } else if (optStrategyParamsGridContainer) {
        optStrategyParamsGridContainer.innerHTML = '<p class="text-sm text-gray-400">Select a strategy to define parameter ranges.</p>';
    }
}

async function runOptimization() {
    showLoading(true);
    optimizationStatusContainer.classList.add('hidden');
    optimizationResultsContainer.classList.add('hidden');
    downloadCsvButton.classList.add('hidden');
    if (optimizationStatusInterval) clearInterval(optimizationStatusInterval);

    // Update all settings from UI just before running
    currentOptimizationSettings.exchange = optExchangeSelect.value;
    currentOptimizationSettings.token = optSymbolSelect.value;
    const selectedOpt = optSymbolSelect.options[optSymbolSelect.selectedIndex];
    currentOptimizationSettings.symbol = selectedOpt ? selectedOpt.text : optSymbolSelect.value;
    currentOptimizationSettings.timeframe = optTimeframeSelect.value;
    currentOptimizationSettings.strategyId = optStrategySelect.value;
    currentOptimizationSettings.initialCapital = parseFloat(optInitialCapitalInput.value);
    currentOptimizationSettings.startDate = optStartDateInput.value;
    currentOptimizationSettings.endDate = optEndDateInput.value;
    currentOptimizationSettings.metricToOptimize = optMetricSelect.value;

    const strategyConfig = availableStrategies.find(s => s.id === currentOptimizationSettings.strategyId);
    if (strategyConfig && strategyConfig.parameters) {
        // getStrategyParamsValues should return a structure like:
        // { "param_name1": {"min": X, "max": Y, "step": Z}, ... }
        // when isRangeInput is true.
        currentOptimizationSettings.parameter_ranges = getStrategyParamsValues(strategyConfig.parameters, true); 
    } else {
        currentOptimizationSettings.parameter_ranges = {}; // Clear if no valid strategy or no params
        if (!strategyConfig) {
            showModal('Error', 'Selected strategy configuration not found.');
            showLoading(false);
            return;
        }
    }
    
    // Validate parameter ranges
    for (const paramName in currentOptimizationSettings.parameter_ranges) {
        const range = currentOptimizationSettings.parameter_ranges[paramName];
        if (typeof range.min !== 'number' || typeof range.max !== 'number' || typeof range.step !== 'number' ||
            isNaN(range.min) || isNaN(range.max) || isNaN(range.step) || range.step <= 0 || range.min > range.max) {
            showModal('Parameter Error', `Invalid range for ${paramName}. Min: ${range.min}, Max: ${range.max}, Step: ${range.step}. Please check inputs.`);
            showLoading(false);
            return;
        }
    }


    const requestBody = {
        strategy_id: currentOptimizationSettings.strategyId,
        exchange: currentOptimizationSettings.exchange, 
        token: currentOptimizationSettings.token,
        start_date: currentOptimizationSettings.startDate, 
        end_date: currentOptimizationSettings.endDate,
        timeframe: currentOptimizationSettings.timeframe, // API might expect 'D' for day
        initial_capital: currentOptimizationSettings.initialCapital,
        parameter_ranges: currentOptimizationSettings.parameter_ranges,
        metric_to_optimize: currentOptimizationSettings.metricToOptimize
    };
    
    // Adjust timeframe for API if needed (e.g., 'day' to 'D')
    if (requestBody.timeframe === 'day') {
        // requestBody.timeframe = 'D'; // Uncomment if your backend expects 'D' for daily
    }

    try {
        const job = await startOptimization(requestBody); // API call
        console.log("Optimization Job Started:", job);
        if (job && job.job_id) {
            optimizationJobId = job.job_id; // Store globally or per instance
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
                        if (status.status === 'COMPLETED' || (status.status === 'CANCELLED' && status.results_available)) { // Check for results_available flag
                            fetchAndDisplayOptimizationResults(optimizationJobId);
                        } else if (status.status === 'FAILED') {
                            showModal('Optimization Failed', status.message || 'The optimization job failed.');
                            optimizationResultsContainer.classList.add('hidden');
                        } else {
                             optimizationResultsContainer.classList.add('hidden');
                        }
                    }
                } catch (pollError) {
                    console.error("Error polling optimization status:", pollError);
                    clearInterval(optimizationStatusInterval); optimizationStatusInterval = null;
                    startOptimizationButton.classList.remove('hidden'); cancelOptimizationButton.classList.add('hidden');
                    updateOptimizationProgressUI({ job_id: optimizationJobId, status: 'ERROR', message: 'Failed to poll status.', progress_percentage: 0 });
                     optimizationResultsContainer.classList.add('hidden');
                }
            }, 3000); 
        } else {
            showModal('Optimization Error', `Failed to start optimization: ${job?.message || job?.detail || 'Unknown error from API'}`);
            showLoading(false); 
        }
    } catch (error) {
        console.error("Error starting optimization:", error);
        showModal('Optimization Start Error', `Failed to start optimization: ${error.data?.detail || error.data?.message || error.message}`);
        showLoading(false); 
    }
}


async function fetchAndDisplayOptimizationResults(jobId) {
    showLoading(true);
    try {
        const resultsData = await getOptimizationResults(jobId);
        console.log("Optimization Results Data:", resultsData);
        if (resultsData && resultsData.results && resultsData.results.length > 0) {
            let paramKeys = [], metricKeys = [];
            // Determine keys from the first result, assuming structure is consistent
            if (resultsData.results[0].parameters) {
                paramKeys = Object.keys(resultsData.results[0].parameters);
            }
            if (resultsData.results[0].performance_metrics) {
                metricKeys = Object.keys(resultsData.results[0].performance_metrics);
            }
            
            populateOptimizationResultsTable(optimizationResultsTbody, optimizationResultsThead, resultsData.results, paramKeys, metricKeys);
            displayBestOptimizationResult(bestResultSummaryDiv, resultsData.best_result, resultsData.request_details?.metric_to_optimize || currentOptimizationSettings.metricToOptimize);
            optimizationResultsContainer.classList.remove('hidden');
            downloadCsvButton.classList.remove('hidden'); 
        } else if (resultsData && resultsData.message) { // Handle cases where API returns a message (e.g. no profitable results)
            showModal('Optimization Results', resultsData.message);
            optimizationResultsContainer.classList.add('hidden');
            downloadCsvButton.classList.add('hidden');
        }
         else {
            showModal('Optimization Results', 'No results data or an empty result set was returned for this optimization job.');
            optimizationResultsContainer.classList.add('hidden');
            downloadCsvButton.classList.add('hidden');
        }
    } catch (error) {
        console.error("Error fetching optimization results:", error);
        showModal('Results Error', `Failed to fetch optimization results: ${error.data?.detail || error.data?.message || error.message}`);
        optimizationResultsContainer.classList.add('hidden');
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
        const response = await cancelOptimization(optimizationJobId); // API call
        showModal('Cancel Request', response.message || `Cancellation status: ${response.status}`);
        // Polling interval will handle UI update mostly.
        // Forcing button state if cancellation is immediate and definitive.
        if (['job_not_found', 'error_cannot_cancel_completed', 'already_completed', 'already_failed', 'cancelled_successfully'].includes(response.status) || response.job_status === 'CANCELLED' || response.job_status === 'FAILED' || response.job_status === 'COMPLETED'  ) {
            if (optimizationStatusInterval) clearInterval(optimizationStatusInterval);
            optimizationStatusInterval = null;
            startOptimizationButton.classList.remove('hidden');
            cancelOptimizationButton.classList.add('hidden');
            // If cancelled but some results might be available
            if ((response.status === 'cancelled_successfully' || response.job_status === 'CANCELLED') && response.results_available) {
                 fetchAndDisplayOptimizationResults(optimizationJobId);
            } else {
                optimizationResultsContainer.classList.add('hidden'); // Hide results if not available
            }
        }
    } catch (error) {
        console.error("Error cancelling optimization:", error);
        showModal('Cancel Error', `Failed to cancel optimization: ${error.data?.detail || error.data?.message || error.message}`);
        // Restore buttons if cancel API call itself fails, polling might still be active or needs reset
        // It's safer to let polling handle this or re-check status.
        // startOptimizationButton.classList.remove('hidden'); // Could be premature
        // cancelOptimizationButton.classList.add('hidden');
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
        const blob = await downloadOptimizationCsv(optimizationJobId); // API call
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

// Ensure helper functions like updateOptimizationProgressUI, populateOptimizationResultsTable, 
// displayBestOptimizationResult, populateSelect, setDefaultDateInputs, showLoading, showModal
// and API call functions (getAvailableStrategies, getSymbolsForExchange, startOptimization, etc.)
// are defined (likely in ui.js or api.js) and correctly imported/available in the scope.