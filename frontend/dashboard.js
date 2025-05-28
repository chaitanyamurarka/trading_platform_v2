// dashboard.js

let availableStrategies = [];
let availableSymbols = [];

let exchangeSelect, symbolSelect, timeframeSelect, strategySelect,
    strategyParamsContainer, applyChartButton, chartHeader,
    goToBacktestButton, goToOptimizeButton;

/**
 * Helper function to format time for Lightweight Charts.
 * Now expects backend to send UTC epoch second timestamps for chart data.
 * @param {number} timeValue - The UTC epoch second timestamp from the API.
 * @returns {number} - Formatted time suitable for Lightweight Charts (UTC epoch seconds).
 */
function formatTimeForLightweightCharts(timeValue) {
    if (typeof timeValue === 'number') {
        if (timeValue > 2000000000000) { // Heuristic for ms
            console.warn("[dashboard.js:formatTime] Received a large timestamp, assuming milliseconds and converting to seconds:", timeValue);
            return Math.floor(timeValue / 1000);
        }
        return timeValue;
    }
    console.error(`[dashboard.js:formatTime] Expected a number (UTC timestamp), but received: ${timeValue} (type: ${typeof timeValue})`);
    if (typeof timeValue === 'string') {
        const d = new Date(timeValue);
        if (!isNaN(d.getTime())) {
            console.warn(`[dashboard.js:formatTime] Received string, attempting parse: ${timeValue}`);
            return Math.floor(d.getTime() / 1000);
        }
    }
    return timeValue;
}


async function initDashboardPage() {
    console.log("[dashboard.js:initDashboardPage] Initializing Dashboard Page...");
    exchangeSelect = document.getElementById('exchangeSelect');
    symbolSelect = document.getElementById('symbolSelect');
    timeframeSelect = document.getElementById('timeframeSelect');
    strategySelect = document.getElementById('strategySelect');
    strategyParamsContainer = document.getElementById('strategyParamsContainer');
    applyChartButton = document.getElementById('applyChartButton');
    chartHeader = document.getElementById('chartHeader');
    goToBacktestButton = document.getElementById('goToBacktestButton');
    goToOptimizeButton = document.getElementById('goToOptimizeButton');

    console.log("[dashboard.js:initDashboardPage] currentSymbolData at start:", JSON.parse(JSON.stringify(currentSymbolData)));
    timeframeSelect.value = currentSymbolData.timeframe;

    exchangeSelect.addEventListener('change', handleExchangeChange);
    symbolSelect.addEventListener('change', handleSymbolChange);
    strategySelect.addEventListener('change', handleStrategyChangeOnDashboard);
    applyChartButton.addEventListener('click', applySettingsToChart);
    goToBacktestButton.addEventListener('click', () => {
        console.log("[dashboard.js] Go To Backtest button clicked. currentSymbolData:", JSON.parse(JSON.stringify(currentSymbolData)));
        currentBacktestSettings = { ...currentSymbolData, strategyParams: { ...currentSymbolData.strategyParams } };
        loadPage('backtesting');
    });
    goToOptimizeButton.addEventListener('click', () => {
        console.log("[dashboard.js] Go To Optimize button clicked. currentSymbolData:", JSON.parse(JSON.stringify(currentSymbolData)));
        currentOptimizationSettings = { ...currentSymbolData, strategyParams: { ...currentSymbolData.strategyParams } };
        loadPage('optimization');
    });

    showLoading(true);
    try {
        if (window.chartInstance) {
            console.log("[dashboard.js:initDashboardPage] Clearing existing chart instance.");
            clearChart(window.chartInstance); //
            window.chartInstance = null;
        }
        console.log("[dashboard.js:initDashboardPage] Initializing new chart.");
        window.chartInstance = initChart('chartContainer'); //
        if (!window.chartInstance) {
            showModal('Chart Error', 'Could not initialize the main chart.');
            showLoading(false);
            return;
        }
        new ResizeObserver(() => {
            if (window.chartInstance && document.getElementById('chartContainer')) {
                resizeChart(window.chartInstance, 'chartContainer'); //
            }
        }).observe(document.getElementById('chartContainerWrapper'));

        console.log("[dashboard.js:initDashboardPage] Fetching available strategies...");
        const strategiesData = await getAvailableStrategies(); //
        if (strategiesData && strategiesData.strategies) {
            availableStrategies = strategiesData.strategies;
            console.log("[dashboard.js:initDashboardPage] Available strategies:", JSON.parse(JSON.stringify(availableStrategies)));
            populateSelect(strategySelect, availableStrategies, 'id', 'name', currentSymbolData.strategyId); //
            if (strategySelect.value) {
                currentSymbolData.strategyId = strategySelect.value;
            } else if (availableStrategies.length > 0) {
                currentSymbolData.strategyId = availableStrategies[0].id;
                strategySelect.value = currentSymbolData.strategyId;
            } else {
                currentSymbolData.strategyId = null;
            }
            console.log("[dashboard.js:initDashboardPage] currentSymbolData.strategyId set to:", currentSymbolData.strategyId);
        } else {
            showModal('Error', 'Could not load strategies.');
            availableStrategies = [];
            currentSymbolData.strategyId = null;
        }

        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        populateSelect(exchangeSelect, exchanges, 'id', 'name', currentSymbolData.exchange); //

        if (!symbolSelect) {
            console.error("[dashboard.js:initDashboardPage] Symbol select element not found!");
            showModal('Error', 'Symbol selection UI element is missing.');
            showLoading(false);
            return;
        }
        console.log("[dashboard.js:initDashboardPage] Loading symbols for exchange:", currentSymbolData.exchange, "Default token:", currentSymbolData.token);
        await loadSymbolsForExchange(currentSymbolData.exchange, currentSymbolData.token);
        console.log("[dashboard.js:initDashboardPage] Calling updateDashboardStrategyParamsUI().");
        await updateDashboardStrategyParamsUI();
    } catch (error) {
        console.error("[dashboard.js:initDashboardPage] Error initializing dashboard:", error);
        showModal('Initialization Error', `Failed to initialize dashboard: ${error.data?.message || error.message}`);
    } finally {
        console.log("[dashboard.js:initDashboardPage] Initialization complete.");
        showLoading(false);
    }
}

async function loadSymbolsForExchange(exchange, defaultToken = '') {
    console.log(`[dashboard.js:loadSymbolsForExchange] Loading symbols for ${exchange}, defaultToken: ${defaultToken}`);
    if (!symbolSelect) {
        console.error("[dashboard.js:loadSymbolsForExchange] symbolSelect element is not available.");
        return;
    }
    showLoading(true);
    try {
        const data = await getSymbolsForExchange(exchange); //
        availableSymbols = data.symbols || [];
        console.log(`[dashboard.js:loadSymbolsForExchange] ${availableSymbols.length} symbols fetched for ${exchange}.`);
        const filteredSymbols = availableSymbols.filter(s => ['EQ', 'INDEX', 'FUTIDX', 'FUTSTK', 'OPTIDX', 'OPTSTK'].includes(s.instrument) || !s.instrument);
        console.log(`[dashboard.js:loadSymbolsForExchange] ${filteredSymbols.length} symbols after filtering.`);
        populateSelect(symbolSelect, filteredSymbols, 'token', 'trading_symbol', defaultToken || (filteredSymbols.length > 0 ? filteredSymbols[0].token : '')); //

        if (symbolSelect.value) {
             const selectedSymbolObj = availableSymbols.find(s => s.token === symbolSelect.value);
             currentSymbolData.token = symbolSelect.value;
             currentSymbolData.symbol = selectedSymbolObj ? selectedSymbolObj.symbol : symbolSelect.options[symbolSelect.selectedIndex]?.text || '';
        } else if (defaultToken) {
            const selectedSymbolObj = availableSymbols.find(s => s.token === defaultToken);
            if (selectedSymbolObj) {
                 currentSymbolData.token = defaultToken;
                 currentSymbolData.symbol = selectedSymbolObj.symbol;
                 if (![...symbolSelect.options].some(opt => opt.value === defaultToken) && filteredSymbols.every(s => s.token !== defaultToken)) {
                    console.log(`[dashboard.js:loadSymbolsForExchange] Default token ${defaultToken} was filtered out, adding it back.`);
                    const opt = document.createElement('option');
                    opt.value = selectedSymbolObj.token;
                    opt.textContent = selectedSymbolObj.trading_symbol;
                    opt.selected = true;
                    symbolSelect.appendChild(opt);
                    symbolSelect.value = defaultToken;
                }
            } else {
                console.warn(`[dashboard.js:loadSymbolsForExchange] Default token ${defaultToken} not found in fetched symbols.`);
                currentSymbolData.token = ''; currentSymbolData.symbol = '';
            }
        } else if (filteredSymbols.length > 0) {
            const firstSymbol = filteredSymbols[0];
            currentSymbolData.token = firstSymbol.token; currentSymbolData.symbol = firstSymbol.symbol;
            symbolSelect.value = firstSymbol.token;
        } else {
            console.warn(`[dashboard.js:loadSymbolsForExchange] No symbols available for ${exchange} after filtering and no default.`);
            currentSymbolData.token = ''; currentSymbolData.symbol = '';
        }
        console.log(`[dashboard.js:loadSymbolsForExchange] currentSymbolData updated: token=${currentSymbolData.token}, symbol=${currentSymbolData.symbol}`);
    } catch (error) {
        console.error(`[dashboard.js:loadSymbolsForExchange] Error fetching symbols for ${exchange}:`, error);
        showModal('Symbol Error', `Could not load symbols for ${exchange}: ${error.data?.detail || error.message}`);
        symbolSelect.innerHTML = '<option value="">Error loading</option>';
        currentSymbolData.token = ''; currentSymbolData.symbol = '';
    } finally {
        showLoading(false);
    }
}

async function handleExchangeChange() {
    console.log("[dashboard.js:handleExchangeChange] Exchange changed to:", exchangeSelect.value);
    currentSymbolData.exchange = exchangeSelect.value;
    currentSymbolData.token = ''; 
    currentSymbolData.symbol = '';
    symbolSelect.innerHTML = '<option value="">Loading symbols...</option>';
    await loadSymbolsForExchange(currentSymbolData.exchange);
    if(currentSymbolData.token){
        console.log("[dashboard.js:handleExchangeChange] Token exists, updating strategy params UI.");
        await updateDashboardStrategyParamsUI();
    } else {
        console.log("[dashboard.js:handleExchangeChange] No token, clearing params and chart.");
        if (strategyParamsContainer) strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Select symbol and strategy.</p>';
        if (window.chartInstance) clearChart(window.chartInstance); //
        if (chartHeader) chartHeader.textContent = 'Please select symbol and strategy.';
    }
}

function handleSymbolChange() {
    const selectedToken = symbolSelect.value;
    console.log("[dashboard.js:handleSymbolChange] Symbol changed to token:", selectedToken);
    const selectedSymbolObj = availableSymbols.find(s => s.token === selectedToken);
    if (selectedSymbolObj) {
        currentSymbolData.token = selectedToken;
        currentSymbolData.symbol = selectedSymbolObj.symbol;
    } else { 
        currentSymbolData.token = selectedToken; 
        currentSymbolData.symbol = symbolSelect.options[symbolSelect.selectedIndex]?.text || selectedToken;
    }
    console.log(`[dashboard.js:handleSymbolChange] currentSymbolData updated: token=${currentSymbolData.token}, symbol=${currentSymbolData.symbol}`);
    if(currentSymbolData.token && currentSymbolData.strategyId){
        console.log("[dashboard.js:handleSymbolChange] Token and strategyId exist, updating strategy params UI.");
        updateDashboardStrategyParamsUI();
    }
}

async function handleStrategyChangeOnDashboard() {
    currentSymbolData.strategyId = strategySelect.value;
    console.log("[dashboard.js:handleStrategyChangeOnDashboard] Strategy changed to:", currentSymbolData.strategyId);
    if(currentSymbolData.token && currentSymbolData.strategyId){
        console.log("[dashboard.js:handleStrategyChangeOnDashboard] Token and strategyId exist, updating strategy params UI.");
        await updateDashboardStrategyParamsUI();
    }
}

async function updateDashboardStrategyParamsUI() {
    console.log("[dashboard.js:updateDashboardStrategyParamsUI] Started.");
    const selectedStrategyId = strategySelect.value || currentSymbolData.strategyId;
    console.log("[dashboard.js:updateDashboardStrategyParamsUI] Selected strategy ID:", selectedStrategyId);

    if (!selectedStrategyId) {
        if (strategyParamsContainer) strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Please select a strategy.</p>';
        console.log("[dashboard.js:updateDashboardStrategyParamsUI] No strategy selected, exiting.");
        return;
    }
    currentSymbolData.strategyId = selectedStrategyId;
    const strategyConfig = availableStrategies.find(s => s.id === selectedStrategyId);
    console.log("[dashboard.js:updateDashboardStrategyParamsUI] Strategy config found:", strategyConfig ? JSON.parse(JSON.stringify(strategyConfig)) : "Not found");

    if (strategyConfig && strategyParamsContainer) {
        strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Determining optimal parameters based on data...</p>';
        showLoading(true);

        try {
            console.log("[dashboard.js:updateDashboardStrategyParamsUI] Starting optimization logic block.");
            // 1. Define Date Range with improved heuristic
            console.log("[dashboard.js:updateDashboardStrategyParamsUI] Determining endDateForData...");
            const now = new Date();
            let endDateForData = new Date(now); 
            const currentDayOfWeek = now.getDay(); // 0=Sunday, 1=Monday, ..., 6=Saturday
            const currentHour = now.getHours(); // User's local hour

            // Heuristic for NSE (India - generally UTC+5:30). 
            // Cutoff 17:00 (5 PM) local time, assuming this is after market close and data settlement.
            if (currentDayOfWeek === 0) { // Sunday
                endDateForData.setDate(now.getDate() - 2); // Set to Friday
                console.log(`[dashboard.js:updateDashboardStrategyParamsUI] It's Sunday. Setting endDateForData to last Friday.`);
            } else if (currentDayOfWeek === 6) { // Saturday
                endDateForData.setDate(now.getDate() - 1); // Set to Friday
                console.log(`[dashboard.js:updateDashboardStrategyParamsUI] It's Saturday. Setting endDateForData to last Friday.`);
            } else { // Weekday (Monday to Friday)
                if (currentHour < 17) { // Before 5 PM (local) on a weekday
                    endDateForData.setDate(now.getDate() - 1); // Use yesterday's data
                    console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Weekday before 5 PM. Setting endDateForData to yesterday.`);
                } else { // After 5 PM on a weekday (or if exact time logic is complex, this path means today)
                    console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Weekday after 5 PM. Using today as endDateForData.`);
                }
            }

            const startDateForData = new Date(endDateForData);
            startDateForData.setDate(endDateForData.getDate() - 365); // Using 365 days prior
            console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Final date range for data/optimization: ${formatDateForAPI(startDateForData)} to ${formatDateForAPI(endDateForData)}`); //


            let datasetLength = 252; // Default/fallback
            console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Initial fallback datasetLength: ${datasetLength}`);

            if (currentSymbolData.token) {
                try {
                    const preliminaryChartRequest = {
                        exchange: currentSymbolData.exchange,
                        token: currentSymbolData.token,
                        timeframe: currentSymbolData.timeframe === 'day' ? 'D' : currentSymbolData.timeframe,
                        strategy_id: null, strategy_params: {},
                        start_date: formatDateForAPI(startDateForData), //
                        end_date: formatDateForAPI(endDateForData) //
                    };
                    console.log("[dashboard.js:updateDashboardStrategyParamsUI] Fetching preliminary data for length. Request:", JSON.parse(JSON.stringify(preliminaryChartRequest)));
                    const preliminaryData = await getChartData(preliminaryChartRequest); //
                    if (preliminaryData && preliminaryData.ohlc_data && preliminaryData.ohlc_data.length > 0) {
                        datasetLength = preliminaryData.ohlc_data.length;
                        console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Actual dataset length for parameter range calculation: ${datasetLength}`);
                    } else {
                        console.warn("[dashboard.js:updateDashboardStrategyParamsUI] Could not fetch preliminary OHLC data (or it was empty), using fallback datasetLength:", datasetLength, "Response:", preliminaryData);
                    }
                } catch (dataError) {
                    console.warn("[dashboard.js:updateDashboardStrategyParamsUI] Error fetching preliminary data for length, using fallback datasetLength:", datasetLength, dataError);
                }
            } else {
                console.log("[dashboard.js:updateDashboardStrategyParamsUI] No token selected, cannot fetch dataset length. Using fallback:", datasetLength);
            }

            const paramRangesForPayload = [];
            let hasNumericParamsForOpt = false;
            console.log("[dashboard.js:updateDashboardStrategyParamsUI] Processing strategy parameters for optimization ranges. Strategy parameters:", JSON.parse(JSON.stringify(strategyConfig.parameters)));

            strategyConfig.parameters.forEach(p => {
                console.log(`[dashboard.js:updateDashboardStrategyParamsUI] --- Iterating for param: ${p.name}, type: ${p.type} ---`);
                console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Param config (p):`, JSON.parse(JSON.stringify(p)));

                if (p.type === 'integer' || p.type === 'int' || p.type === 'float') { // CORRECTED type check
                    hasNumericParamsForOpt = true;
                    let minVal, maxVal;
                    let step = p.step; 
                    if (typeof step !== 'number' || step <= 0) { 
                        step = (p.type === 'integer' || p.type === 'int' ? 1 : 0.01); // Fallback step
                        console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Param ${p.name} had invalid/missing step ${p.step}, using default step: ${step}`);
                    }
                    console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Effective step for ${p.name}: ${step} (from p.step: ${p.step})`);

                    if (p.name === 'slow_ema_period' || p.name.toLowerCase().includes('slow')) {
                        minVal = (p.min_value !== null && p.min_value !== undefined) ?
                                 ((p.type === 'integer' || p.type === 'int') ? parseInt(p.min_value) : parseFloat(p.min_value)) :
                                 ((p.type === 'integer' || p.type === 'int') ? 10 : 1.0);
                        maxVal = Math.floor(datasetLength / 3);
                        if (p.max_value !== null && p.max_value !== undefined) {
                            maxVal = Math.min(maxVal, ((p.type === 'integer' || p.type === 'int') ? parseInt(p.max_value) : parseFloat(p.max_value)));
                        }
                        if (maxVal <= minVal) maxVal = minVal + step * 5;
                        console.log(`[dashboard.js:updateDashboardStrategyParamsUI] SLOW EMA logic: initial minVal=${minVal}, initial maxVal=${maxVal} (datasetLength/3 ~ ${Math.floor(datasetLength / 3)})`);
                    } else if (p.name === 'fast_ema_period' || p.name.toLowerCase().includes('fast')) {
                        minVal = (p.min_value !== null && p.min_value !== undefined) ?
                                 ((p.type === 'integer' || p.type === 'int') ? parseInt(p.min_value) : parseFloat(p.min_value)) :
                                 ((p.type === 'integer' || p.type === 'int') ? 2 : 0.2);
                        maxVal = Math.floor(datasetLength / 5);
                        if (p.max_value !== null && p.max_value !== undefined) {
                             maxVal = Math.min(maxVal, ((p.type === 'integer' || p.type === 'int') ? parseInt(p.max_value) : parseFloat(p.max_value)));
                        }
                        if (maxVal <= minVal) maxVal = minVal + step * 5;
                        console.log(`[dashboard.js:updateDashboardStrategyParamsUI] FAST EMA logic: initial minVal=${minVal}, initial maxVal=${maxVal} (datasetLength/5 ~ ${Math.floor(datasetLength / 5)})`);
                    } else if (p.name === 'stop_loss_pct') {
                        minVal = 0.0; maxVal = 0.50; 
                        step = (p.step !== null && p.step !== undefined && p.step > 0) ? p.step : 0.05; // Fallback to 5% step if config step invalid
                        console.log(`[dashboard.js:updateDashboardStrategyParamsUI] SL_PCT logic: minVal=${minVal}, maxVal=${maxVal}, step=${step} (p.step was ${p.step}, default fallback 0.05)`);
                    } else if (p.name === 'take_profit_pct') {
                        minVal = 0.0; maxVal = 0.50; 
                        step = (p.step !== null && p.step !== undefined && p.step > 0) ? p.step : 0.05; // Fallback to 5% step
                        console.log(`[dashboard.js:updateDashboardStrategyParamsUI] TP_PCT logic: minVal=${minVal}, maxVal=${maxVal}, step=${step} (p.step was ${p.step}, default fallback 0.05)`);
                    } else { 
                        const defaultPVal = (p.type === 'integer' || p.type === 'int') ? parseInt(p.default) : parseFloat(p.default);
                        minVal = (p.min_value !== null && p.min_value !== undefined) ?
                                 ((p.type === 'integer' || p.type === 'int') ? parseInt(p.min_value) : parseFloat(p.min_value)) :
                                 ((p.type === 'integer' || p.type === 'int') ? Math.max(1, defaultPVal - step * 5) : defaultPVal - step * 5);
                        maxVal = (p.max_value !== null && p.max_value !== undefined) ?
                                 ((p.type === 'integer' || p.type === 'int') ? parseInt(p.max_value) : parseFloat(p.max_value)) :
                                 ((p.type === 'integer' || p.type === 'int') ? defaultPVal + step * 10 : defaultPVal + step * 10);

                        if (minVal <= 0 && (p.name.includes('period') || p.name.includes('length'))) minVal = Math.max(1, step);
                        if (maxVal <= minVal) maxVal = minVal + Math.max(step, ((p.type === 'integer' || p.type === 'int') ? 1 : 0.1)) * 10;
                        console.log(`[dashboard.js:updateDashboardStrategyParamsUI] OTHER NUMERIC (${p.name}) logic: initial minVal=${minVal}, initial maxVal=${maxVal}`);
                    }

                    let finalStartValue, finalEndValue, finalStep;
                    finalStep = (p.type === 'integer' || p.type === 'int') ? Math.max(1, Math.round(step)) : Math.max(step > 0 ? step : 0.0001, 0.00001); 

                    if (p.type === 'integer' || p.type === 'int') {
                        finalStartValue = Math.round(minVal);
                        finalEndValue = Math.round(maxVal);
                        if (p.name.includes('period') || p.name.includes('length')) {
                           finalStartValue = Math.max(p.min_value !== null && p.min_value !== undefined ? parseInt(p.min_value) : 1, finalStartValue);
                           finalStartValue = Math.max(1, finalStartValue);
                        }
                    } else { // float
                        finalStartValue = minVal;
                        finalEndValue = maxVal;
                        if (p.name.includes('_pct')) {
                            finalStartValue = Math.max(0, finalStartValue);
                        }
                    }
                    
                    if (finalEndValue < finalStartValue) {
                        console.warn(`[dashboard.js:updateDashboardStrategyParamsUI] Corrected finalEndValue for ${p.name} as it was less than finalStartValue. Was ${finalEndValue}, now ${finalStartValue}. Setting step to ensure one iteration if possible or backend handles.`);
                        finalEndValue = finalStartValue;
                        finalStep = (finalStartValue === finalEndValue) ? Math.max(1, finalStep) : finalStep; // if they are equal, step should allow one iteration
                    }

                    console.log(`[dashboard.js:updateDashboardStrategyParamsUI] For param ${p.name}: finalStartValue=${finalStartValue}, finalEndValue=${finalEndValue}, finalStep=${finalStep}`);

                    if (typeof finalStartValue !== 'number' || typeof finalEndValue !== 'number' || typeof finalStep !== 'number' ||
                        isNaN(finalStartValue) || isNaN(finalEndValue) || isNaN(finalStep) || finalStep <= 0) {
                        console.error(`[dashboard.js:updateDashboardStrategyParamsUI] SKIPPING parameter ${p.name} due to invalid numeric values post-processing. Start: ${finalStartValue}, End: ${finalEndValue}, Step: ${finalStep}`);
                    } else {
                        paramRangesForPayload.push({
                            name: p.name,
                            start_value: finalStartValue,
                            end_value: finalEndValue,
                            step: finalStep
                        });
                        console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Pushed to paramRangesForPayload for ${p.name}:`, JSON.parse(JSON.stringify(paramRangesForPayload[paramRangesForPayload.length-1])));
                    }
                } else {
                     console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Parameter ${p.name} is type ${p.type}, not numeric (or failed primary check). Skipping for optimization range generation.`);
                }
            });
            console.log("[dashboard.js:updateDashboardStrategyParamsUI] Final paramRangesForPayload before optimization call:", JSON.parse(JSON.stringify(paramRangesForPayload)));

            if (hasNumericParamsForOpt && currentSymbolData.token) {
                if (paramRangesForPayload.length === 0) {
                    console.warn("[dashboard.js:updateDashboardStrategyParamsUI] hasNumericParamsForOpt was true, but paramRangesForPayload is empty. Using defaults.");
                    currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                        acc[p.name] = (p.type === 'integer' || p.type === 'int') ? parseInt(p.default) : (p.type === 'float' ? parseFloat(p.default) : (p.type === 'boolean' ? (String(p.default).toLowerCase() === 'true') :p.default)); return acc;}, {});
                } else {
                    const optRequest = {
                        strategy_id: selectedStrategyId,
                        exchange: currentSymbolData.exchange,
                        token: currentSymbolData.token,
                        timeframe: currentSymbolData.timeframe === 'day' ? 'D' : currentSymbolData.timeframe,
                        start_date: formatDateForAPI(startDateForData), //
                        end_date: formatDateForAPI(endDateForData),   //
                        initial_capital: 100000,
                        parameter_ranges: paramRangesForPayload,
                        metric_to_optimize: 'net_pnl'
                    };
                    console.log("[dashboard.js:updateDashboardStrategyParamsUI] optRequest payload (broad with SL/TP logic & detailed logs):", JSON.parse(JSON.stringify(optRequest)));

                    const optJob = await startOptimization(optRequest); //
                    if (optJob && optJob.job_id && optJob.status !== "FAILED") {
                        console.log("[dashboard.js:updateDashboardStrategyParamsUI] Optimization job started/queued:", JSON.parse(JSON.stringify(optJob)));
                        let jobStatus = await getOptimizationStatus(optJob.job_id); //
                        let attempts = 0;
                        const maxAttempts = 60; 
                        console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Polling for job ${optJob.job_id} completion (max ${maxAttempts} attempts).`);
                        while (jobStatus && (jobStatus.status === 'QUEUED' || jobStatus.status === 'RUNNING') && attempts < maxAttempts) {
                            await new Promise(resolve => setTimeout(resolve, 2000)); 
                            jobStatus = await getOptimizationStatus(optJob.job_id); //
                            attempts++;
                            console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Opt job ${optJob.job_id} status: ${jobStatus?.status}, attempt: ${attempts}/${maxAttempts}`);
                        }

                        if (jobStatus && jobStatus.status === 'COMPLETED') {
                            console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Optimization job ${optJob.job_id} COMPLETED. Fetching results.`);
                            const optResults = await getOptimizationResults(optJob.job_id); //
                            console.log(`[dashboard.js:updateDashboardStrategyParamsUI] Optimization results for job ${optJob.job_id}:`, optResults ? JSON.parse(JSON.stringify(optResults)) : "No results object");
                            if (optResults && optResults.best_result && optResults.best_result.parameters) {
                                const bestParamsTyped = {};
                                for (const key in optResults.best_result.parameters) {
                                    const paramConfig = strategyConfig.parameters.find(p => p.name === key);
                                    const value = optResults.best_result.parameters[key];
                                    if (paramConfig) {
                                        if (paramConfig.type === 'integer' || paramConfig.type === 'int') bestParamsTyped[key] = parseInt(value);
                                        else if (paramConfig.type === 'float') bestParamsTyped[key] = parseFloat(value);
                                        else if (paramConfig.type === 'boolean') bestParamsTyped[key] = (String(value).toLowerCase() === 'true');
                                        else bestParamsTyped[key] = value;
                                    } else { bestParamsTyped[key] = value; }
                                }
                                currentSymbolData.strategyParams = bestParamsTyped;
                                console.log("[dashboard.js:updateDashboardStrategyParamsUI] Optimal parameters applied from optimization:", JSON.parse(JSON.stringify(currentSymbolData.strategyParams)));
                            } else {
                                 console.warn("[dashboard.js:updateDashboardStrategyParamsUI] Optimization completed but no best_result found or parameters missing. Using defaults. OptResults:", optResults ? JSON.parse(JSON.stringify(optResults.best_result)) : "null");
                                 currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                                    acc[p.name] = (p.type === 'integer' || p.type === 'int') ? parseInt(p.default) : (p.type === 'float' ? parseFloat(p.default) : (p.type === 'boolean' ? (String(p.default).toLowerCase() === 'true') :p.default)); return acc;}, {});
                                 console.log("[dashboard.js:updateDashboardStrategyParamsUI] Applied default params due to no best_result:", JSON.parse(JSON.stringify(currentSymbolData.strategyParams)));
                            }
                        } else {
                            console.warn(`[dashboard.js:updateDashboardStrategyParamsUI] Optimization did not complete successfully or timed out. Status: ${jobStatus?.status}. Using default strategy params.`);
                            currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                                acc[p.name] = (p.type === 'integer' || p.type === 'int') ? parseInt(p.default) : (p.type === 'float' ? parseFloat(p.default) : (p.type === 'boolean' ? (String(p.default).toLowerCase() === 'true') :p.default)); return acc; }, {});
                            console.log("[dashboard.js:updateDashboardStrategyParamsUI] Applied default params due to opt failure/timeout:", JSON.parse(JSON.stringify(currentSymbolData.strategyParams)));
                        }
                    } else { 
                        console.warn("[dashboard.js:updateDashboardStrategyParamsUI] Optimization job could not be started or failed immediately. Using default strategy params. Job response:", optJob ? JSON.parse(JSON.stringify(optJob)) : "null");
                        currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                             acc[p.name] = (p.type === 'integer' || p.type === 'int') ? parseInt(p.default) : (p.type === 'float' ? parseFloat(p.default) : (p.type === 'boolean' ? (String(p.default).toLowerCase() === 'true') :p.default)); return acc; }, {});
                        console.log("[dashboard.js:updateDashboardStrategyParamsUI] Applied default params due to opt job start failure:", JSON.parse(JSON.stringify(currentSymbolData.strategyParams)));
                    }
                } 
            } else { 
                 console.log("[dashboard.js:updateDashboardStrategyParamsUI] No numeric parameters to optimize OR no token selected. Using default strategy params.");
                 currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                    acc[p.name] = (p.type === 'integer' || p.type === 'int') ? parseInt(p.default) : (p.type === 'float' ? parseFloat(p.default) : (p.type === 'boolean' ? (String(p.default).toLowerCase() === 'true') :p.default)); return acc; }, {});
                 console.log("[dashboard.js:updateDashboardStrategyParamsUI] Applied default params (no numeric/token):", JSON.parse(JSON.stringify(currentSymbolData.strategyParams)));
            }
        } catch (error) {
            console.error("[dashboard.js:updateDashboardStrategyParamsUI] Major error during initial optimization logic:", error);
            const errorMessage = error.data?.detail || error.data?.message || error.message || (error.statusText ? `${error.status} ${error.statusText}`: "Unknown error during optimization.");
            showModal("Parameter Error", `Could not fetch/determine optimal parameters. Using defaults. Error: ${errorMessage}`);
            currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                acc[p.name] = (p.type === 'integer' || p.type === 'int') ? parseInt(p.default) : (p.type === 'float' ? parseFloat(p.default) : (p.type === 'boolean' ? (String(p.default).toLowerCase() === 'true') :p.default)); return acc;}, {});
            console.log("[dashboard.js:updateDashboardStrategyParamsUI] Applied default params due to major error:", JSON.parse(JSON.stringify(currentSymbolData.strategyParams)));
        } finally {
            console.log("[dashboard.js:updateDashboardStrategyParamsUI] Preparing to update UI input fields with final params:", JSON.parse(JSON.stringify(currentSymbolData.strategyParams)));
            const paramsForUI = { ...currentSymbolData.strategyParams };
            strategyConfig.parameters.forEach(p => { 
                if (paramsForUI[p.name] === undefined) {
                    console.warn(`[dashboard.js:updateDashboardStrategyParamsUI] Param ${p.name} was undefined in final paramsForUI, using default: ${p.default}`);
                    paramsForUI[p.name] = (p.type === 'integer' || p.type === 'int') ? parseInt(p.default) : (p.type === 'float' ? parseFloat(p.default) : (p.type === 'boolean' ? (String(p.default).toLowerCase() === 'true') :p.default));
                }
                if ((p.type === 'integer' || p.type === 'int') && typeof paramsForUI[p.name] !== 'number') paramsForUI[p.name] = parseInt(paramsForUI[p.name]);
                else if (p.type === 'float' && typeof paramsForUI[p.name] !== 'number') paramsForUI[p.name] = parseFloat(paramsForUI[p.name]);
                else if (p.type === 'boolean' && typeof paramsForUI[p.name] !== 'boolean') paramsForUI[p.name] = (String(paramsForUI[p.name]).toLowerCase() === 'true');
            });
            console.log("[dashboard.js:updateDashboardStrategyParamsUI] Final params being sent to createStrategyParamsInputs:", JSON.parse(JSON.stringify(paramsForUI)));
            createStrategyParamsInputs(strategyParamsContainer, strategyConfig.parameters, paramsForUI, false); //
            showLoading(false);
            console.log("[dashboard.js:updateDashboardStrategyParamsUI] UI params updated. Calling applySettingsToChart if token and strategy exist.");
            if(currentSymbolData.token && currentSymbolData.strategyId){
                 await applySettingsToChart();
            }
        }
    } else if (strategyParamsContainer) {
        strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Select a strategy to see its parameters.</p>';
        console.log("[dashboard.js:updateDashboardStrategyParamsUI] No strategyConfig or strategyParamsContainer found.");
    }
    console.log("[dashboard.js:updateDashboardStrategyParamsUI] Finished.");
}


async function applySettingsToChart() {
    console.log("[dashboard.js:applySettingsToChart] Started. Current state:", JSON.parse(JSON.stringify(currentSymbolData)));
    if (!window.chartInstance) {
        showModal('Chart Error', 'Chart is not initialized.');
        console.error("[dashboard.js:applySettingsToChart] Chart instance not found!");
        return;
    }

    currentSymbolData.exchange = exchangeSelect.value;
    currentSymbolData.token = symbolSelect.value;
    const selectedSymbolObj = availableSymbols.find(s => s.token === currentSymbolData.token);
    currentSymbolData.symbol = selectedSymbolObj ? selectedSymbolObj.symbol : (symbolSelect.options[symbolSelect.selectedIndex]?.text || currentSymbolData.token);
    currentSymbolData.timeframe = timeframeSelect.value;
    currentSymbolData.strategyId = strategySelect.value;
    console.log("[dashboard.js:applySettingsToChart] currentSymbolData after reading UI:", JSON.parse(JSON.stringify(currentSymbolData)));

    const strategyConfig = availableStrategies.find(s => s.id === currentSymbolData.strategyId);
    const finalStrategyParams = {};
    console.log("[dashboard.js:applySettingsToChart] strategyConfig for param processing:", strategyConfig ? JSON.parse(JSON.stringify(strategyConfig.parameters)) : "No strategy config");

    if (strategyConfig) {
        const uiParams = getStrategyParamsValues(strategyConfig.parameters, false); //
        console.log("[dashboard.js:applySettingsToChart] Params from UI (getStrategyParamsValues):", JSON.parse(JSON.stringify(uiParams)));
        strategyConfig.parameters.forEach(p_conf => {
            const paramName = p_conf.name;
            let paramValue = uiParams[paramName];
            console.log(`[dashboard.js:applySettingsToChart] Processing param ${paramName}. UI Value: ${paramValue} (type: ${typeof paramValue})`);

            if (paramValue === undefined || String(paramValue).trim() === "") {
                paramValue = currentSymbolData.strategyParams[paramName] !== undefined 
                           ? currentSymbolData.strategyParams[paramName] 
                           : p_conf.default;
                console.log(`[dashboard.js:applySettingsToChart] Param ${paramName} was empty in UI, using stored/default: ${paramValue}`);
            }
            
            if ((p_conf.type === 'integer' || p_conf.type === 'int')) finalStrategyParams[paramName] = parseInt(paramValue);
            else if (p_conf.type === 'float') finalStrategyParams[paramName] = parseFloat(paramValue);
            else if (p_conf.type === 'boolean') finalStrategyParams[paramName] = (String(paramValue).toLowerCase() === 'true');
            else finalStrategyParams[paramName] = paramValue; // String
            console.log(`[dashboard.js:applySettingsToChart] Param ${paramName} final value for API: ${finalStrategyParams[paramName]} (type: ${typeof finalStrategyParams[paramName]})`);
        });
        currentSymbolData.strategyParams = { ...finalStrategyParams }; 
        console.log("[dashboard.js:applySettingsToChart] Updated currentSymbolData.strategyParams:", JSON.parse(JSON.stringify(currentSymbolData.strategyParams)));
    } else {
        currentSymbolData.strategyParams = {}; 
        console.log("[dashboard.js:applySettingsToChart] No strategy selected, cleared currentSymbolData.strategyParams.");
    }

    const finalStrategyIdForAPI = (currentSymbolData.strategyId && currentSymbolData.strategyId !== "None" && currentSymbolData.strategyId !== "") ? currentSymbolData.strategyId : null;
    console.log("[dashboard.js:applySettingsToChart] finalStrategyIdForAPI:", finalStrategyIdForAPI);

    if (!currentSymbolData.token) {
        showModal('Input Error', 'Please select a symbol.');
        chartHeader.textContent = 'Please select a symbol to load chart.';
        if (window.chartInstance) clearChart(window.chartInstance); //
        console.log("[dashboard.js:applySettingsToChart] No token selected, aborting chart load.");
        return;
    }

    showLoading(true);
    chartHeader.textContent = `Loading ${currentSymbolData.symbol || currentSymbolData.token} (${currentSymbolData.timeframe})...`;
    if (window.chartInstance) {
        console.log("[dashboard.js:applySettingsToChart] Clearing chart before loading new data.");
        clearChart(window.chartInstance); //
    }

    try {
        let apiTimeframe = currentSymbolData.timeframe;
        if (apiTimeframe === 'day') apiTimeframe = 'D';

        const chartRequest = {
            exchange: currentSymbolData.exchange,
            token: currentSymbolData.token,
            timeframe: apiTimeframe,
            strategy_id: finalStrategyIdForAPI,
            strategy_params: finalStrategyIdForAPI ? currentSymbolData.strategyParams : {},
            start_date: formatDateForAPI(new Date(new Date().setDate(new Date().getDate() - 365))), // Default chart view period //
            end_date: formatDateForAPI(new Date()) //
        };
        console.log("[dashboard.js:applySettingsToChart] chartRequest payload:", JSON.parse(JSON.stringify(chartRequest)));

        const data = await getChartData(chartRequest); //
        console.log("[dashboard.js:applySettingsToChart] Received chart data from API:", data ? "Data received" : "No data object", data ? JSON.parse(JSON.stringify(data)) : "");


        if (data && data.ohlc_data && data.ohlc_data.length > 0) {
            const ohlcForChart = data.ohlc_data.map(d => ({
                time: formatTimeForLightweightCharts(d.time),
                open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume
            }));
            console.log(`[dashboard.js:applySettingsToChart] Processed ${ohlcForChart.length} OHLC data points for chart.`);
            window.candlestickSeries = addOrUpdateCandlestickSeries(window.chartInstance, ohlcForChart); //

            if (data.indicator_data && Array.isArray(data.indicator_data) && data.indicator_data.length > 0) {
                console.log("[dashboard.js:applySettingsToChart] Processing indicator data:", JSON.parse(JSON.stringify(data.indicator_data)));
                const indicatorColors = { fast_ema: 'rgba(0, 150, 136, 0.8)', slow_ema: 'rgba(255, 82, 82, 0.8)' };
                const transformedIndicatorData = {};
                data.indicator_data.forEach(indicatorSeries => {
                    if (indicatorSeries.name && Array.isArray(indicatorSeries.data)) {
                        let simpleKey = indicatorSeries.name.toLowerCase().replace(/\s*\(.*\)/, '').replace(/\s+/g, '_');
                        transformedIndicatorData[simpleKey] = indicatorSeries.data.map(indPt => ({
                            time: formatTimeForLightweightCharts(indPt.time),
                            value: indPt.value
                        }));
                    }
                });
                addOrUpdateIndicatorSeries(window.chartInstance, transformedIndicatorData, indicatorColors); //
            } else {
                console.log("[dashboard.js:applySettingsToChart] No indicator data present in API response.");
            }

            if (data.trade_markers && window.candlestickSeries && data.trade_markers.length > 0) {
                 console.log("[dashboard.js:applySettingsToChart] Processing trade markers:", JSON.parse(JSON.stringify(data.trade_markers)));
                 const markersForChart = data.trade_markers.map(m => ({
                    ...m,
                    time: formatTimeForLightweightCharts(m.time),
                }));
                addTradeMarkers(window.candlestickSeries, markersForChart); //
            } else {
                console.log("[dashboard.js:applySettingsToChart] No trade markers present in API response.");
            }
            fitChartContent(window.chartInstance); //
            chartHeader.textContent = `${data.chart_header_info || (currentSymbolData.symbol + ' (' + currentSymbolData.timeframe + ')')}`;
        } else {
            chartHeader.textContent = `No data available for ${currentSymbolData.symbol || currentSymbolData.token}.`;
            showModal('No Data', `No chart data found for the selected criteria. ${data?.message || ''}`);
            console.log(`[dashboard.js:applySettingsToChart] No OHLC data available for ${currentSymbolData.symbol}. API response message: ${data?.message}`);
        }
    } catch (error) {
        console.error("[dashboard.js:applySettingsToChart] Error applying settings to chart:", error);
        chartHeader.textContent = `Error loading chart for ${currentSymbolData.symbol || currentSymbolData.token}.`;
        const errorMessage = error.data?.detail || error.data?.message || error.message || (error.statusText ? `${error.status} ${error.statusText}`: "Unknown error loading chart.");
        showModal('Chart Error', `Failed to load chart data: ${errorMessage}`);
    } finally {
        showLoading(false);
        console.log("[dashboard.js:applySettingsToChart] Finished.");
    }
}