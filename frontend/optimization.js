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
    console.log("DEBUG: Initializing Optimization Page...");
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
    } else {
        console.error("DEBUG: optStrategyParamsContainer not found in DOM during init.");
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
    console.log("DEBUG: currentOptimizationSettings at start of initOptimizationPage:", JSON.stringify(currentOptimizationSettings));

    // Assuming setDefaultDateInputs is defined elsewhere and correctly sets input values
    if (typeof setDefaultDateInputs === 'function') {
        setDefaultDateInputs(optStartDateInput, optEndDateInput, 365); // Default to 1 year back
        console.log(`DEBUG: After setDefaultDateInputs - optStartDateInput.value: "${optStartDateInput.value}", optEndDateInput.value: "${optEndDateInput.value}"`);
    } else {
        console.error("DEBUG: setDefaultDateInputs function is not defined. Date inputs might not be set correctly.");
    }


    currentOptimizationSettings.startDate = optStartDateInput.value; // Update from default
    currentOptimizationSettings.endDate = optEndDateInput.value; // Update from default
    console.log(`DEBUG: currentOptimizationSettings after updating from default dates: startDate: "${currentOptimizationSettings.startDate}", endDate: "${currentOptimizationSettings.endDate}"`);


    startOptimizationButton.addEventListener('click', runOptimization);
    cancelOptimizationButton.addEventListener('click', handleCancelOptimization);
    downloadCsvButton.addEventListener('click', handleDownloadCsv);
    optExchangeSelect.addEventListener('change', handleOptExchangeChange);
    optSymbolSelect.addEventListener('change', () => {
        currentOptimizationSettings.token = optSymbolSelect.value;
        const selectedOption = optSymbolSelect.options[optSymbolSelect.selectedIndex];
        currentOptimizationSettings.symbol = selectedOption ? selectedOption.text : optSymbolSelect.value;
        console.log(`DEBUG: optSymbolSelect changed. Token: ${currentOptimizationSettings.token}, Symbol: ${currentOptimizationSettings.symbol}`);
    });
    optStrategySelect.addEventListener('change', updateOptStrategyParamsUI);
    optTimeframeSelect.addEventListener('change', () => { currentOptimizationSettings.timeframe = optTimeframeSelect.value; console.log(`DEBUG: optTimeframeSelect changed. Timeframe: ${currentOptimizationSettings.timeframe}`); });
    optInitialCapitalInput.addEventListener('change', () => { currentOptimizationSettings.initialCapital = parseFloat(optInitialCapitalInput.value); console.log(`DEBUG: optInitialCapitalInput changed. Initial Capital: ${currentOptimizationSettings.initialCapital}`);});
    optMetricSelect.addEventListener('change', () => { currentOptimizationSettings.metricToOptimize = optMetricSelect.value; console.log(`DEBUG: optMetricSelect changed. Metric: ${currentOptimizationSettings.metricToOptimize}`);});
    optStartDateInput.addEventListener('change', () => { currentOptimizationSettings.startDate = optStartDateInput.value; console.log(`DEBUG: optStartDateInput changed. StartDate: ${currentOptimizationSettings.startDate}`);});
    optEndDateInput.addEventListener('change', () => { currentOptimizationSettings.endDate = optEndDateInput.value; console.log(`DEBUG: optEndDateInput changed. EndDate: ${currentOptimizationSettings.endDate}`);});


    showLoading(true);
    try {
        console.log("DEBUG: Before loading strategies. currentOptimizationSettings.strategyId:", currentOptimizationSettings.strategyId);
        // Ensuring window.availableStrategies is used, assuming it's the global declaration
        if (!window.availableStrategies || window.availableStrategies.length === 0) {
            console.log("DEBUG: Fetching available strategies...");
            const strategiesData = await getAvailableStrategies();
            if (strategiesData && strategiesData.strategies) {
                 window.availableStrategies = strategiesData.strategies; // Ensure global is updated
                 console.log("DEBUG: Strategies fetched:", JSON.stringify(window.availableStrategies));
            } else {
                window.availableStrategies = [];
                console.log("DEBUG: No strategies found or error fetching. strategiesData:", strategiesData);
            }
        } else {
            console.log("DEBUG: Using existing window.availableStrategies:", JSON.stringify(window.availableStrategies));
        }

        populateSelect(optStrategySelect, window.availableStrategies, 'id', 'name', currentOptimizationSettings.strategyId);
        if (window.availableStrategies.length > 0 && !currentOptimizationSettings.strategyId) {
            currentOptimizationSettings.strategyId = window.availableStrategies[0].id; // Default to first if not set
            console.log("DEBUG: Defaulted strategyId to first available:", currentOptimizationSettings.strategyId);
        }
        // Ensure value is actually set if strategyId exists
        if (currentOptimizationSettings.strategyId) {
            optStrategySelect.value = currentOptimizationSettings.strategyId;
        }
        console.log(`DEBUG: optStrategySelect value attempted set to: ${currentOptimizationSettings.strategyId}, actual value: ${optStrategySelect.value}`);


        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        populateSelect(optExchangeSelect, exchanges, 'id', 'name', currentOptimizationSettings.exchange);
        optExchangeSelect.value = currentOptimizationSettings.exchange; // Should be fine as it's from a predefined list
        console.log(`DEBUG: optExchangeSelect value set to: ${optExchangeSelect.value}`);

        console.log(`DEBUG: Calling loadOptSymbols with exchange: ${currentOptimizationSettings.exchange}, token: ${currentOptimizationSettings.token}`);
        await loadOptSymbols(currentOptimizationSettings.exchange, currentOptimizationSettings.token);
        console.log(`DEBUG: After loadOptSymbols. currentToken: ${currentOptimizationSettings.token}, currentSymbol: ${currentOptimizationSettings.symbol}, optSymbolSelect.value: ${optSymbolSelect.value}`);

        // Ensure currentOptimizationSettings has defaults for these properties if not passed
        currentOptimizationSettings.timeframe = currentOptimizationSettings.timeframe || 'day'; // Or another suitable default
        currentOptimizationSettings.initialCapital = currentOptimizationSettings.initialCapital !== undefined ? currentOptimizationSettings.initialCapital : 100000; // Default initial capital
        currentOptimizationSettings.metricToOptimize = currentOptimizationSettings.metricToOptimize || 'net_pnl'; // Default metric

        optTimeframeSelect.value = currentOptimizationSettings.timeframe;
        optInitialCapitalInput.value = currentOptimizationSettings.initialCapital;
        optMetricSelect.value = currentOptimizationSettings.metricToOptimize;

        console.log(`DEBUG: Values before setting date inputs (around original line 93-94) - currentOptimizationSettings.startDate: "${currentOptimizationSettings.startDate}" (Type: ${typeof currentOptimizationSettings.startDate}), currentOptimizationSettings.endDate: "${currentOptimizationSettings.endDate}" (Type: ${typeof currentOptimizationSettings.endDate})`);
        // Check if date inputs exist before trying to set their value
        if (optStartDateInput) {
            if (currentOptimizationSettings.startDate && typeof currentOptimizationSettings.startDate === 'string') {
                console.log(`DEBUG: Attempting to set optStartDateInput.value to: "${currentOptimizationSettings.startDate}"`);
                optStartDateInput.value = currentOptimizationSettings.startDate;
            } else {
                console.warn(`DEBUG: currentOptimizationSettings.startDate is invalid or not a string: "${currentOptimizationSettings.startDate}". Not setting optStartDateInput.value.`);
            }
        } else {
            console.error("DEBUG: optStartDateInput is null.");
        }

        if (optEndDateInput) { // This is effectively original line 94
            if (currentOptimizationSettings.endDate && typeof currentOptimizationSettings.endDate === 'string') {
                console.log(`DEBUG: Attempting to set optEndDateInput.value to: "${currentOptimizationSettings.endDate}"`);
                optEndDateInput.value = currentOptimizationSettings.endDate;
            } else {
                console.warn(`DEBUG: currentOptimizationSettings.endDate is invalid or not a string: "${currentOptimizationSettings.endDate}". Not setting optEndDateInput.value.`);
            }
        } else {
            console.error("DEBUG: optEndDateInput is null.");
        }
        console.log(`DEBUG: optStartDateInput.value after potential set: "${optStartDateInput ? optStartDateInput.value : 'null'}", optEndDateInput.value after potential set: "${optEndDateInput ? optEndDateInput.value : 'null'}"`);


        console.log("DEBUG: Calling updateOptStrategyParamsUI...");
        await updateOptStrategyParamsUI();

    } catch (error) {
        console.error("DEBUG: Error initializing optimization page:", error, error.stack);
        showModal('Initialization Error', `Failed to initialize optimization page: ${error.data?.message || error.message}`);
    } finally {
        showLoading(false);
        console.log("DEBUG: Initialization function finished (successfully or with error).");
    }
}

async function loadOptSymbols(exchange, defaultToken = '') {
    console.log(`DEBUG: loadOptSymbols called with exchange: ${exchange}, defaultToken: ${defaultToken}`); // Added DEBUG
    showLoading(true);
    optSymbolSelect.innerHTML = '<option value="">Loading symbols...</option>';
    try {
        const data = await getSymbolsForExchange(exchange);
        console.log(`DEBUG: Symbols data for ${exchange}:`, data); // Added DEBUG
        const allSymbols = data.symbols || [];
        // Broader filter for optimization, can be adjusted
        const filteredSymbols = allSymbols.filter(s => ['EQ', 'INDEX', 'FUTIDX', 'FUTSTK', 'OPTIDX', 'OPTSTK'].includes(s.instrument) || !s.instrument);
        populateSelect(optSymbolSelect, filteredSymbols, 'token', 'trading_symbol', defaultToken || (filteredSymbols.length > 0 ? filteredSymbols[0].token : ''));
        console.log(`DEBUG: optSymbolSelect populated. Selected value: ${optSymbolSelect.value}`); // Added DEBUG

        if (optSymbolSelect.value) {
            currentOptimizationSettings.token = optSymbolSelect.value;
            const selectedOption = optSymbolSelect.options[optSymbolSelect.selectedIndex];
            currentOptimizationSettings.symbol = selectedOption ? selectedOption.text : optSymbolSelect.value;
        } else if (defaultToken) {
             currentOptimizationSettings.token = defaultToken;
             // Ensure the symbol text is also updated if defaultToken was used and found/added
             const selectedSymbolObj = allSymbols.find(s => s.token === defaultToken);
             if(selectedSymbolObj){
                 currentOptimizationSettings.symbol = selectedSymbolObj.trading_symbol;
                 // If the defaultToken was not in filteredSymbols but now added to select
                 if (!filteredSymbols.some(s => s.token === defaultToken)) {
                    let exists = false;
                    for(let i=0; i < optSymbolSelect.options.length; i++) {
                        if(optSymbolSelect.options[i].value === defaultToken) {
                            exists = true; break;
                        }
                    }
                    if(!exists) {
                        const opt = document.createElement('option');
                        opt.value = defaultToken;
                        opt.textContent = selectedSymbolObj.trading_symbol;
                        opt.selected = true; // Select it
                        optSymbolSelect.appendChild(opt);
                        optSymbolSelect.value = defaultToken; // Ensure select reflects this
                    }
                 } else {
                    optSymbolSelect.value = defaultToken; // Ensure select reflects this
                 }
             } else {
                  currentOptimizationSettings.symbol = defaultToken; // Fallback
             }
        } else if (filteredSymbols.length > 0) {
            optSymbolSelect.value = filteredSymbols[0].token;
            currentOptimizationSettings.token = filteredSymbols[0].token;
            currentOptimizationSettings.symbol = filteredSymbols[0].trading_symbol;
        } else {
            currentOptimizationSettings.token = '';
            currentOptimizationSettings.symbol = '';
            console.log("DEBUG: No symbols loaded or selected for exchange:", exchange); // Added DEBUG
        }
        console.log(`DEBUG: loadOptSymbols finished. Token: ${currentOptimizationSettings.token}, Symbol: ${currentOptimizationSettings.symbol}`); // Added DEBUG
    } catch (error) {
        console.error(`DEBUG: Error fetching symbols for optimization ${exchange}:`, error, error.stack);
        showModal('Symbol Error', `Could not load symbols for optimization: ${error.data?.detail || error.message}`);
        optSymbolSelect.innerHTML = '<option value="">Error loading</option>';
    } finally {
        showLoading(false);
    }
}

function handleOptExchangeChange() {
    console.log("DEBUG: handleOptExchangeChange called."); // Added DEBUG
    currentOptimizationSettings.exchange = optExchangeSelect.value;
    // Reset token and symbol as they belong to the previous exchange
    currentOptimizationSettings.token = '';
    currentOptimizationSettings.symbol = '';
    console.log(`DEBUG: Exchange changed to ${currentOptimizationSettings.exchange}. Token/Symbol reset. Calling loadOptSymbols.`); // Added DEBUG
    loadOptSymbols(currentOptimizationSettings.exchange); // This will update token and symbol
}

async function updateOptStrategyParamsUI() {
    console.log("DEBUG: updateOptStrategyParamsUI called."); // Added DEBUG
    currentOptimizationSettings.strategyId = optStrategySelect.value;
    console.log(`DEBUG: Strategy ID set to: ${currentOptimizationSettings.strategyId}`); // Added DEBUG
    const strategyConfig = window.availableStrategies.find(s => s.id === currentOptimizationSettings.strategyId);

    if (!optStrategyParamsGridContainer) {
        console.error("DEBUG: optStrategyParamsGridContainer is not found in the DOM for updateOptStrategyParamsUI.");
        return;
    }
     console.log("DEBUG: optStrategyParamsGridContainer found:", optStrategyParamsGridContainer); // Added DEBUG

    if (strategyConfig && strategyConfig.parameters) {
        console.log("DEBUG: Strategy config found with parameters:", JSON.stringify(strategyConfig.parameters)); // Added DEBUG
        const paramRangesToLoad = {};
        strategyConfig.parameters.forEach(p => {
            console.log(`DEBUG: Processing parameter for UI: ${p.name}`, p); // Added DEBUG
            const type = p.type.toLowerCase();
            let defaultVal, stepVal, minVal, maxVal;

            // Determine step value
            if (p.step !== null && p.step !== undefined && parseFloat(p.step) > 0) {
                stepVal = (type === 'integer' || type === 'int') ? parseInt(p.step) : parseFloat(p.step);
            } else {
                stepVal = (type === 'integer' || type === 'int') ? 1 : 0.01; // Default step
            }

            // Determine default value for deriving ranges if min/max are absent
            // Determine default value for deriving ranges if min/max are absent
            if (p.default !== null && p.default !== undefined) { // <<<< CORRECTED
                defaultVal = (type === 'integer' || type === 'int') ? parseInt(p.default) : // <<<< CORRECTED
                            (type === 'float' ? parseFloat(p.default) : p.default); // <<<< CORRECTED
            } else {
                // Fallback if default is also missing (should not happen for well-defined strategies)
                defaultVal = (type === 'integer' || type === 'int') ? 10 : 1.0;
                console.warn(`DEBUG: Parameter ${p.name} missing 'default' property or its value is null/undefined. Using fallback: ${defaultVal}`);
            }
            
            // Determine min value for the range input
            if (p.min_value !== null && p.min_value !== undefined) {
                minVal = (type === 'integer' || type === 'int') ? parseInt(p.min_value) : parseFloat(p.min_value);
            } else {
                 minVal = (type === 'integer' || type === 'int') ? Math.max(1, defaultVal - stepVal * 5) : Math.max(0.01, defaultVal - stepVal * 5);
                 if (p.name.toLowerCase().includes('period') || p.name.toLowerCase().includes('length')) {
                    minVal = Math.max(1, minVal);
                 } else if (p.name.toLowerCase().includes('_pct')) {
                    minVal = Math.max(0.01, minVal);
                 }
                 console.warn(`DEBUG: Parameter ${p.name} missing min_value. Calculated fallback: ${minVal}`); // Added DEBUG
            }

            // Determine max value for the range input
            if (p.max_value !== null && p.max_value !== undefined) {
                maxVal = (type === 'integer' || type === 'int') ? parseInt(p.max_value) : parseFloat(p.max_value);
            } else {
                maxVal = (type === 'integer' || type === 'int') ? (defaultVal + stepVal * 10) : (defaultVal + stepVal * 10);
                if (p.name.toLowerCase().includes('_pct')) {
                     maxVal = Math.min(100.0, maxVal);
                }
                 console.warn(`DEBUG: Parameter ${p.name} missing max_value. Calculated fallback: ${maxVal}`); // Added DEBUG
            }
            
            // Ensure min < max, and step is positive
            if (minVal >= maxVal) {
                 console.warn(`DEBUG: For ${p.name}, initial minVal (${minVal}) >= maxVal (${maxVal}). Adjusting maxVal.`); // Added DEBUG
                 maxVal = minVal + stepVal * 5;
                 if (minVal >= maxVal && stepVal > 0) maxVal = minVal + stepVal;
                 else if (minVal >= maxVal) maxVal = minVal + ((type === 'integer' || type === 'int') ? 1 : 0.1);
                 console.warn(`DEBUG: Adjusted maxVal for ${p.name} to ${maxVal}.`); // Added DEBUG
            }
             if (stepVal <= 0) {
                console.warn(`DEBUG: For ${p.name}, initial stepVal (${stepVal}) is <= 0. Adjusting stepVal.`); // Added DEBUG
                stepVal = (type === 'integer' || type === 'int') ? 1 : 0.01;
                console.warn(`DEBUG: Adjusted stepVal for ${p.name} to ${stepVal}.`); // Added DEBUG
            }

            paramRangesToLoad[p.name] = {
                min: minVal,
                max: maxVal,
                step: stepVal,
                default_value: defaultVal
            };
            console.log(`DEBUG: paramRangesToLoad for ${p.name}:`, paramRangesToLoad[p.name]); // Added DEBUG
        });
        // Assuming createStrategyParamsInputs is defined elsewhere
        if (typeof createStrategyParamsInputs === 'function') {
            createStrategyParamsInputs(optStrategyParamsGridContainer, strategyConfig.parameters, paramRangesToLoad, true); // true for range inputs
            console.log("DEBUG: createStrategyParamsInputs called."); // Added DEBUG
        } else {
            console.error("DEBUG: createStrategyParamsInputs function is not defined. Parameter inputs cannot be created.");
             optStrategyParamsGridContainer.innerHTML = '<p class="text-sm text-red-500">Error: UI function to create parameter inputs is missing.</p>';
        }
    } else if (optStrategyParamsGridContainer) {
        console.log("DEBUG: No strategy selected or strategy has no parameters. Clearing params container."); // Added DEBUG
        optStrategyParamsGridContainer.innerHTML = '<p class="text-sm text-gray-400">Select a strategy to define parameter ranges.</p>';
    }
}

async function runOptimization() {
    console.log("DEBUG: runOptimization called");
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
    currentOptimizationSettings.initialCapital = parseFloat(optInitialCapitalInput.value); // Already parsed
    currentOptimizationSettings.startDate = optStartDateInput.value;
    currentOptimizationSettings.endDate = optEndDateInput.value;
    currentOptimizationSettings.metricToOptimize = optMetricSelect.value;
    console.log("DEBUG: currentOptimizationSettings at start of runOptimization:", JSON.stringify(currentOptimizationSettings, null, 2));

    const strategyConfig = window.availableStrategies.find(s => s.id === currentOptimizationSettings.strategyId);
    if (strategyConfig && strategyConfig.parameters) {
        console.log("DEBUG: Strategy config found with parameters:", JSON.stringify(strategyConfig.parameters, null, 2));
        // Assuming getStrategyParamsValues is defined elsewhere
        if (typeof getStrategyParamsValues === 'function') {
            currentOptimizationSettings.parameter_ranges = getStrategyParamsValues(strategyConfig.parameters, true);
            console.log("DEBUG: parameter_ranges from getStrategyParamsValues:", JSON.stringify(currentOptimizationSettings.parameter_ranges, null, 2));
        } else {
            console.error("DEBUG: getStrategyParamsValues function is not defined. Cannot get parameter ranges.");
            showModal('Error', 'Internal error: Function to retrieve parameter values is missing.');
            showLoading(false);
            return;
        }
    } else {
        currentOptimizationSettings.parameter_ranges = {};
        if (!strategyConfig) {
            showModal('Error', 'Selected strategy configuration not found.');
            showLoading(false);
            console.error("DEBUG: Selected strategy configuration not found for ID:", currentOptimizationSettings.strategyId);
            return;
        }
        console.log("DEBUG: No parameters for strategy or strategy config not found. parameter_ranges set to {}. Strategy ID:", currentOptimizationSettings.strategyId);
    }

    console.log("DEBUG: Validating parameter_ranges...");
    for (const paramName in currentOptimizationSettings.parameter_ranges) {
        const range = currentOptimizationSettings.parameter_ranges[paramName];
        console.log(`DEBUG: Validating param: "${paramName}", range: ${JSON.stringify(range)}`);
        console.log(`  Min: Value=${range.min}, Type=${typeof range.min}, isNaN=${isNaN(range.min)}`);
        console.log(`  Max: Value=${range.max}, Type=${typeof range.max}, isNaN=${isNaN(range.max)}`);
        console.log(`  Step: Value=${range.step}, Type=${typeof range.step}, isNaN=${isNaN(range.step)}`);
        console.log(`  Condition: step <= 0 is ${range.step <= 0}`);
        console.log(`  Condition: min > max is ${range.min > range.max}`);

        if (typeof range.min !== 'number' || typeof range.max !== 'number' || typeof range.step !== 'number' ||
            isNaN(range.min) || isNaN(range.max) || isNaN(range.step) || range.step <= 0 || range.min > range.max) {
            const errorMessage = `Invalid range for ${paramName}. Min: ${range.min} (type: ${typeof range.min}), Max: ${range.max} (type: ${typeof range.max}), Step: ${range.step} (type: ${typeof range.step}). Please check inputs.`;
            console.error("DEBUG: Parameter validation failed:", errorMessage);
            showModal('Parameter Error', errorMessage); // Show detailed types in modal
            showLoading(false);
            return;
        }
    }
    console.log("DEBUG: Parameter validation successful.");


    // ... inside runOptimization, after currentOptimizationSettings.parameter_ranges is populated

    console.log("DEBUG: Original parameter_ranges from UI/getStrategyParamsValues:", JSON.stringify(currentOptimizationSettings.parameter_ranges, null, 2));

    // Transform parameter_ranges to the list format expected by the API
    const apiParameterRanges = [];
    for (const paramName in currentOptimizationSettings.parameter_ranges) {
        if (Object.hasOwnProperty.call(currentOptimizationSettings.parameter_ranges, paramName)) {
            const rangeDetails = currentOptimizationSettings.parameter_ranges[paramName];
            apiParameterRanges.push({
                name: paramName,
                start_value: rangeDetails.min, // Map 'min' to 'start_value'
                end_value: rangeDetails.max,   // Map 'max' to 'end_value'
                step: rangeDetails.step
            });
        }
    }
    console.log("DEBUG: Transformed apiParameterRanges for request:", JSON.stringify(apiParameterRanges, null, 2));


    const requestBody = {
        strategy_id: currentOptimizationSettings.strategyId,
        exchange: currentOptimizationSettings.exchange,
        token: currentOptimizationSettings.token,
        start_date: currentOptimizationSettings.startDate,
        end_date: currentOptimizationSettings.endDate,
        timeframe: currentOptimizationSettings.timeframe,
        initial_capital: currentOptimizationSettings.initialCapital,
        parameter_ranges: apiParameterRanges, // <--- USE THE TRANSFORMED LIST
        metric_to_optimize: currentOptimizationSettings.metricToOptimize
    };
    console.log("DEBUG: Optimization requestBody to be sent:", JSON.stringify(requestBody, null, 2)); // Log the final body

    // Adjust timeframe for API if needed (e.g., 'day' to 'D')
    // if (requestBody.timeframe === 'day') {
    // requestBody.timeframe = 'D'; // Uncomment if your backend expects 'D' for daily
    // }

    try {
        const job = await startOptimization(requestBody); // API call
        console.log("DEBUG: Optimization Job Started API response:", job); // Added DEBUG
        if (job && job.job_id) {
            optimizationJobId = job.job_id;
            updateOptimizationProgressUI(job);
            optimizationStatusContainer.classList.remove('hidden');
            startOptimizationButton.classList.add('hidden');
            cancelOptimizationButton.classList.remove('hidden');

            optimizationStatusInterval = setInterval(async () => {
                try {
                    // console.log(`DEBUG: Polling status for job_id: ${optimizationJobId}`); // Can be too noisy
                    const status = await getOptimizationStatus(optimizationJobId);
                    // console.log(`DEBUG: Polled status:`, status); // Can be too noisy
                    updateOptimizationProgressUI(status);
                    if (status.status === 'COMPLETED' || status.status === 'FAILED' || status.status === 'CANCELLED') {
                        console.log(`DEBUG: Optimization job ${optimizationJobId} ended with status: ${status.status}`); // Added DEBUG
                        clearInterval(optimizationStatusInterval); optimizationStatusInterval = null;
                        startOptimizationButton.classList.remove('hidden'); cancelOptimizationButton.classList.add('hidden');
                        if (status.status === 'COMPLETED' || (status.status === 'CANCELLED' && status.results_available)) {
                            fetchAndDisplayOptimizationResults(optimizationJobId);
                        } else if (status.status === 'FAILED') {
                            showModal('Optimization Failed', status.message || 'The optimization job failed.');
                            optimizationResultsContainer.classList.add('hidden');
                        } else {
                             optimizationResultsContainer.classList.add('hidden');
                        }
                    }
                } catch (pollError) {
                    console.error("DEBUG: Error polling optimization status:", pollError, pollError.stack); // Added DEBUG
                    clearInterval(optimizationStatusInterval); optimizationStatusInterval = null;
                    startOptimizationButton.classList.remove('hidden'); cancelOptimizationButton.classList.add('hidden');
                    updateOptimizationProgressUI({ job_id: optimizationJobId, status: 'ERROR', message: 'Failed to poll status.', progress_percentage: 0 });
                     optimizationResultsContainer.classList.add('hidden');
                }
            }, 3000);
        } else {
            const errorMsg = `Failed to start optimization: ${job?.message || job?.detail || 'Unknown error from API'}`;
            console.error("DEBUG:", errorMsg, "API Response:", job); // Added DEBUG
            showModal('Optimization Error', errorMsg);
            showLoading(false);
        }
    } catch (error) {
        console.error("DEBUG: Error starting optimization API call:", error, error.stack); // Added DEBUG
        showModal('Optimization Start Error', `Failed to start optimization: ${error.data?.detail || error.data?.message || error.message}`);
        showLoading(false);
    }
}


async function fetchAndDisplayOptimizationResults(jobId) {
    console.log(`DEBUG: fetchAndDisplayOptimizationResults called for job ID: ${jobId}`); // Added DEBUG
    showLoading(true);
    try {
        const resultsData = await getOptimizationResults(jobId);
        console.log("DEBUG: Optimization Results Data from API:", JSON.stringify(resultsData, null, 2)); // Added DEBUG
        if (resultsData && resultsData.results && resultsData.results.length > 0) {
            let paramKeys = [], metricKeys = [];
            if (resultsData.results[0].parameters) {
                paramKeys = Object.keys(resultsData.results[0].parameters);
            }
            if (resultsData.results[0].performance_metrics) {
                metricKeys = Object.keys(resultsData.results[0].performance_metrics);
            }
            console.log("DEBUG: paramKeys:", paramKeys, "metricKeys:", metricKeys); // Added DEBUG
            
            populateOptimizationResultsTable(optimizationResultsTbody, optimizationResultsThead, resultsData.results, paramKeys, metricKeys);
            displayBestOptimizationResult(bestResultSummaryDiv, resultsData.best_result, resultsData.request_details?.metric_to_optimize || currentOptimizationSettings.metricToOptimize);
            optimizationResultsContainer.classList.remove('hidden');
            downloadCsvButton.classList.remove('hidden');
        } else if (resultsData && resultsData.message) {
            console.log("DEBUG: Optimization results API returned a message:", resultsData.message); // Added DEBUG
            showModal('Optimization Results', resultsData.message);
            optimizationResultsContainer.classList.add('hidden');
            downloadCsvButton.classList.add('hidden');
        } else {
            console.log("DEBUG: No results data or an empty result set was returned."); // Added DEBUG
            showModal('Optimization Results', 'No results data or an empty result set was returned for this optimization job.');
            optimizationResultsContainer.classList.add('hidden');
            downloadCsvButton.classList.add('hidden');
        }
    } catch (error) {
        console.error("DEBUG: Error fetching optimization results:", error, error.stack); // Added DEBUG
        showModal('Results Error', `Failed to fetch optimization results: ${error.data?.detail || error.data?.message || error.message}`);
        optimizationResultsContainer.classList.add('hidden');
        downloadCsvButton.classList.add('hidden');
    } finally {
        showLoading(false);
    }
}

async function handleCancelOptimization() {
    console.log("DEBUG: handleCancelOptimization called."); // Added DEBUG
    if (!optimizationJobId) {
        console.warn("DEBUG: No active optimization job ID to cancel."); // Added DEBUG
        showModal('Error', 'No active optimization job to cancel.');
        return;
    }
    showLoading(true);
    try {
        const response = await cancelOptimization(optimizationJobId); // API call
        console.log("DEBUG: Cancel optimization API response:", response); // Added DEBUG
        showModal('Cancel Request', response.message || `Cancellation status: ${response.status}`);
        if (['job_not_found', 'error_cannot_cancel_completed', 'already_completed', 'already_failed', 'cancelled_successfully'].includes(response.status) || response.job_status === 'CANCELLED' || response.job_status === 'FAILED' || response.job_status === 'COMPLETED'  ) {
            if (optimizationStatusInterval) clearInterval(optimizationStatusInterval);
            optimizationStatusInterval = null;
            startOptimizationButton.classList.remove('hidden');
            cancelOptimizationButton.classList.add('hidden');
            if ((response.status === 'cancelled_successfully' || response.job_status === 'CANCELLED') && response.results_available) {
                 console.log("DEBUG: Cancellation successful, results available. Fetching results."); // Added DEBUG
                 fetchAndDisplayOptimizationResults(optimizationJobId);
            } else {
                optimizationResultsContainer.classList.add('hidden');
            }
        }
    } catch (error) {
        console.error("DEBUG: Error cancelling optimization API call:", error, error.stack); // Added DEBUG
        showModal('Cancel Error', `Failed to cancel optimization: ${error.data?.detail || error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}

async function handleDownloadCsv() {
    console.log("DEBUG: handleDownloadCsv called."); // Added DEBUG
    if (!optimizationJobId) {
        console.warn("DEBUG: No optimization job ID available to download CSV."); // Added DEBUG
        showModal('Error', 'No optimization job ID available to download results.');
        return;
    }
    showLoading(true);
    try {
        const blob = await downloadOptimizationCsv(optimizationJobId); // API call
        console.log("DEBUG: CSV Blob received:", blob); // Added DEBUG
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none'; a.href = url;
        a.download = `optimization_results_${optimizationJobId}.csv`;
        document.body.appendChild(a); a.click();
        window.URL.revokeObjectURL(url); a.remove();
        console.log("DEBUG: CSV download initiated."); // Added DEBUG
    } catch (error) {
        console.error("DEBUG: Error downloading CSV:", error, error.stack); // Added DEBUG
        showModal('Download Error', `Failed to download CSV: ${error.data?.detail || error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}

// Ensure helper functions like updateOptimizationProgressUI, populateOptimizationResultsTable,
// displayBestOptimizationResult, populateSelect, setDefaultDateInputs, showLoading, showModal,
// createStrategyParamsInputs, getStrategyParamsValues
// and API call functions (getAvailableStrategies, getSymbolsForExchange, startOptimization, etc.)
// are defined (likely in ui.js or api.js) and correctly imported/available in the scope.

// Adding a log to indicate the script has been parsed.
console.log("DEBUG: optimization.js script parsed and executed.");