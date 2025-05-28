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
        // Backend should be sending UTC epoch seconds.
        // Lightweight Charts expects seconds. If backend accidentally sends ms, convert.
        if (timeValue > 2000000000000) { // Heuristic: if timestamp is for year > 2033 (approx 2 * 10^12 ms), likely ms
            console.warn("Received a large timestamp, assuming milliseconds and converting to seconds:", timeValue);
            return Math.floor(timeValue / 1000);
        }
        return timeValue; // Assume seconds
    }
    // Log an error if the backend sends something other than a number for chart time values.
    console.error(`formatTimeForLightweightCharts expected a number (UTC timestamp), but received: ${timeValue} (type: ${typeof timeValue})`);
    // Fallback for unexpected types - this might lead to chart errors
    // Attempt to parse if it's a string that new Date might handle as UTC (e.g. ISO with Z)
    if (typeof timeValue === 'string') {
        const d = new Date(timeValue);
        if (!isNaN(d.getTime())) {
            console.warn(`formatTimeForLightweightCharts received string, attempting parse: ${timeValue}`);
            return Math.floor(d.getTime() / 1000);
        }
    }
    // If it's not a number and not a parseable string, it's problematic.
    // Returning original value might break the chart. Consider returning undefined or a specific error marker.
    return timeValue;
}


async function initDashboardPage() {
    console.log("Initializing Dashboard Page...");
    exchangeSelect = document.getElementById('exchangeSelect');
    symbolSelect = document.getElementById('symbolSelect');
    timeframeSelect = document.getElementById('timeframeSelect');
    strategySelect = document.getElementById('strategySelect');
    strategyParamsContainer = document.getElementById('strategyParamsContainer');
    applyChartButton = document.getElementById('applyChartButton');
    chartHeader = document.getElementById('chartHeader');
    goToBacktestButton = document.getElementById('goToBacktestButton');
    goToOptimizeButton = document.getElementById('goToOptimizeButton');

    timeframeSelect.value = currentSymbolData.timeframe;

    exchangeSelect.addEventListener('change', handleExchangeChange);
    symbolSelect.addEventListener('change', handleSymbolChange);
    strategySelect.addEventListener('change', handleStrategyChangeOnDashboard);
    applyChartButton.addEventListener('click', applySettingsToChart);
    goToBacktestButton.addEventListener('click', () => {
        currentBacktestSettings = { ...currentSymbolData, strategyParams: { ...currentSymbolData.strategyParams } };
        loadPage('backtesting');
    });
    goToOptimizeButton.addEventListener('click', () => {
        currentOptimizationSettings = { ...currentSymbolData, strategyParams: { ...currentSymbolData.strategyParams } }; // Pass current dashboard state
        loadPage('optimization');
    });

    showLoading(true);
    try {
        if (window.chartInstance) { 
            clearChart(window.chartInstance);
            window.chartInstance = null; 
        }
        window.chartInstance = initChart('chartContainer'); // initChart now handles IST localization
        if (!window.chartInstance) {
            showModal('Chart Error', 'Could not initialize the main chart.');
            showLoading(false);
            return;
        }
        new ResizeObserver(() => {
            if (window.chartInstance && document.getElementById('chartContainer')) {
                resizeChart(window.chartInstance, 'chartContainer');
            }
        }).observe(document.getElementById('chartContainerWrapper'));

        const strategiesData = await getAvailableStrategies();
        if (strategiesData && strategiesData.strategies) {
            availableStrategies = strategiesData.strategies;
            populateSelect(strategySelect, availableStrategies, 'id', 'name', currentSymbolData.strategyId);
            if (strategySelect.value) {
                currentSymbolData.strategyId = strategySelect.value;
            } else if (availableStrategies.length > 0) {
                currentSymbolData.strategyId = availableStrategies[0].id; 
                strategySelect.value = currentSymbolData.strategyId;
            } else {
                currentSymbolData.strategyId = null; 
            }
        } else {
            showModal('Error', 'Could not load strategies.');
            availableStrategies = []; 
            currentSymbolData.strategyId = null;
        }

        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        populateSelect(exchangeSelect, exchanges, 'id', 'name', currentSymbolData.exchange);

        if (!symbolSelect) {
            console.error("Symbol select element not found during init.");
            showModal('Error', 'Symbol selection UI element is missing.');
            showLoading(false);
            return;
        }
        await loadSymbolsForExchange(currentSymbolData.exchange, currentSymbolData.token);
        await updateDashboardStrategyParamsUI(); // This also triggers initial chart load
    } catch (error) {
        console.error("Error initializing dashboard:", error);
        showModal('Initialization Error', `Failed to initialize dashboard: ${error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}

async function loadSymbolsForExchange(exchange, defaultToken = '') {
    if (!symbolSelect) {
        console.error("loadSymbolsForExchange: symbolSelect element is not available.");
        return;
    }
    showLoading(true);
    try {
        const data = await getSymbolsForExchange(exchange);
        availableSymbols = data.symbols || [];
        const filteredSymbols = availableSymbols.filter(s => ['EQ', 'INDEX', 'FUTIDX', 'FUTSTK', 'OPTIDX', 'OPTSTK'].includes(s.instrument) || !s.instrument);
        populateSelect(symbolSelect, filteredSymbols, 'token', 'trading_symbol', defaultToken || (filteredSymbols.length > 0 ? filteredSymbols[0].token : ''));
        
        if (symbolSelect.value) {
             const selectedSymbolObj = availableSymbols.find(s => s.token === symbolSelect.value);
             currentSymbolData.token = symbolSelect.value;
             currentSymbolData.symbol = selectedSymbolObj ? selectedSymbolObj.symbol : symbolSelect.options[symbolSelect.selectedIndex]?.text || '';
        } else if (defaultToken) {
            const selectedSymbolObj = availableSymbols.find(s => s.token === defaultToken);
            if (selectedSymbolObj) {
                 currentSymbolData.token = defaultToken;
                 currentSymbolData.symbol = selectedSymbolObj.symbol;
                 // Ensure the option is added if it was filtered out but is the default
                 if (![...symbolSelect.options].some(opt => opt.value === defaultToken) && filteredSymbols.every(s => s.token !== defaultToken)) {
                    const opt = document.createElement('option');
                    opt.value = selectedSymbolObj.token;
                    opt.textContent = selectedSymbolObj.trading_symbol;
                    opt.selected = true; // Select it
                    symbolSelect.appendChild(opt); // Or insert appropriately if list should be sorted
                    symbolSelect.value = defaultToken; // Ensure it's set
                }
            } else {
                currentSymbolData.token = ''; currentSymbolData.symbol = '';
            }
        } else if (filteredSymbols.length > 0) {
            const firstSymbol = filteredSymbols[0];
            currentSymbolData.token = firstSymbol.token; currentSymbolData.symbol = firstSymbol.symbol;
            symbolSelect.value = firstSymbol.token;
        } else {
            currentSymbolData.token = ''; currentSymbolData.symbol = '';
        }
    } catch (error) {
        console.error(`Error fetching symbols for ${exchange}:`, error);
        showModal('Symbol Error', `Could not load symbols for ${exchange}: ${error.data?.detail || error.message}`);
        symbolSelect.innerHTML = '<option value="">Error loading</option>';
        currentSymbolData.token = ''; currentSymbolData.symbol = '';
    } finally {
        showLoading(false);
    }
}

async function handleExchangeChange() {
    currentSymbolData.exchange = exchangeSelect.value;
    // Reset symbol and token before loading new symbols
    currentSymbolData.token = ''; 
    currentSymbolData.symbol = '';
    symbolSelect.innerHTML = '<option value="">Loading symbols...</option>'; // Clear previous symbols
    await loadSymbolsForExchange(currentSymbolData.exchange); 
    // updateDashboardStrategyParamsUI will be called if loadSymbols triggers a change or if explicitly called after symbol selection
    // If loadSymbolsForExchange sets a default symbol, it should ideally trigger handleSymbolChange or similar logic
    // For now, let's rely on the apply button or explicit call after full selection.
    // Or, if a symbol is auto-selected, directly call:
    if(currentSymbolData.token){
        await updateDashboardStrategyParamsUI();
    } else {
        // Clear chart and params if no symbol selected
        if (strategyParamsContainer) strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Select symbol and strategy.</p>';
        if (window.chartInstance) clearChart(window.chartInstance);
        if (chartHeader) chartHeader.textContent = 'Please select symbol and strategy.';
    }
}

function handleSymbolChange() {
    const selectedToken = symbolSelect.value;
    const selectedSymbolObj = availableSymbols.find(s => s.token === selectedToken);
    if (selectedSymbolObj) {
        currentSymbolData.token = selectedToken;
        currentSymbolData.symbol = selectedSymbolObj.symbol;
    } else { // Fallback if symbol not in availableSymbols (e.g. custom input)
        currentSymbolData.token = selectedToken; 
        currentSymbolData.symbol = symbolSelect.options[symbolSelect.selectedIndex]?.text || selectedToken;
    }
    // Fetch optimal params for new symbol and reload chart
    // This implies that changing symbol should auto-apply. If not desired, remove this call.
    if(currentSymbolData.token && currentSymbolData.strategyId){
         updateDashboardStrategyParamsUI();
    }
}

async function handleStrategyChangeOnDashboard() {
    currentSymbolData.strategyId = strategySelect.value;
    if(currentSymbolData.token && currentSymbolData.strategyId){
        await updateDashboardStrategyParamsUI(); 
    }
}

async function updateDashboardStrategyParamsUI() {
    const selectedStrategyId = strategySelect.value || currentSymbolData.strategyId; 
    if (!selectedStrategyId) {
        if (strategyParamsContainer) strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Please select a strategy.</p>';
        // Don't clear chart here, let applySettingsToChart handle it based on overall state
        return;
    }
    currentSymbolData.strategyId = selectedStrategyId; 
    const strategyConfig = availableStrategies.find(s => s.id === selectedStrategyId);

    if (strategyConfig && strategyParamsContainer) {
        strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Fetching optimal parameters...</p>';
        showLoading(true);
        try {
            // ... (rest of the quick optimization logic from your existing file, it's quite complex)
            // This part for fetching optimal parameters is kept as is from your provided file
            // Ensure it correctly uses selectedStrategyId, currentSymbolData.exchange, currentSymbolData.token, etc.
            // And that `currentSymbolData.strategyParams` is populated with typed parameters.
            const paramRangesForPayload = []; 
            let hasNumericParamsForOpt = false;

            strategyConfig.parameters.forEach(p => {
                if (p.type === 'integer' || p.type === 'float') {
                    hasNumericParamsForOpt = true;
                    const step = p.step || 1;
                    const defaultVal = p.type === 'integer' ? parseInt(p.default) : parseFloat(p.default); 
                    
                    let minVal = defaultVal - step * 2;
                    let maxVal = defaultVal + step * 2;

                    if (p.min_value !== null && p.min_value !== undefined) minVal = Math.max(minVal, (p.type === 'integer' ? parseInt(p.min_value) : parseFloat(p.min_value)));
                    if (p.max_value !== null && p.max_value !== undefined) maxVal = Math.min(maxVal, (p.type === 'integer' ? parseInt(p.max_value) : parseFloat(p.max_value)));
                    
                    if (minVal >= maxVal) {
                        minVal = defaultVal;
                        maxVal = defaultVal + step;
                        if (p.max_value !== null && p.max_value !== undefined) maxVal = Math.min(maxVal, (p.type === 'integer' ? parseInt(p.max_value) : parseFloat(p.max_value)));
                        if (minVal >= maxVal && p.type !== 'boolean') maxVal = minVal + step;
                    }
                    paramRangesForPayload.push({
                        name: p.name,
                        start_value: p.type === 'integer' ? Math.round(minVal) : minVal,
                        end_value: p.type === 'integer' ? Math.round(maxVal) : maxVal,  
                        step: p.type === 'integer' ? Math.max(1, Math.round(step)) : step 
                    });
                }
            });

            if (hasNumericParamsForOpt && currentSymbolData.token) { 
                const endDate = new Date();
                const startDate = new Date();
                startDate.setDate(endDate.getDate() - 90); 

                const optRequest = {
                    strategy_id: selectedStrategyId,
                    exchange: currentSymbolData.exchange,
                    token: currentSymbolData.token,
                    timeframe: currentSymbolData.timeframe === 'day' ? 'D' : currentSymbolData.timeframe, 
                    start_date: formatDateForAPI(startDate),
                    end_date: formatDateForAPI(endDate),
                    initial_capital: 100000,
                    parameter_ranges: paramRangesForPayload, 
                    metric_to_optimize: 'net_pnl' // Or a configurable default
                };
                console.log("[updateDashboardStrategyParamsUI] optRequest payload:", JSON.parse(JSON.stringify(optRequest)));

                const optJob = await startOptimization(optRequest);
                if (optJob && optJob.job_id && optJob.status !== "FAILED") {
                    let jobStatus = await getOptimizationStatus(optJob.job_id);
                    let attempts = 0;
                    const maxAttempts = 15; 
                    while (jobStatus && (jobStatus.status === 'QUEUED' || jobStatus.status === 'RUNNING') && attempts < maxAttempts) {
                        await new Promise(resolve => setTimeout(resolve, 2000)); // Poll less aggressively
                        jobStatus = await getOptimizationStatus(optJob.job_id);
                        attempts++;
                    }

                    if (jobStatus && jobStatus.status === 'COMPLETED') {
                        const optResults = await getOptimizationResults(optJob.job_id);
                        if (optResults && optResults.best_result && optResults.best_result.parameters) {
                            const bestParamsTyped = {};
                            for (const key in optResults.best_result.parameters) {
                                const paramConfig = strategyConfig.parameters.find(p => p.name === key);
                                const value = optResults.best_result.parameters[key];
                                if (paramConfig && paramConfig.type === 'integer') {
                                    bestParamsTyped[key] = parseInt(value);
                                } else if (paramConfig && paramConfig.type === 'float') {
                                    bestParamsTyped[key] = parseFloat(value);
                                } else { // boolean or string
                                    bestParamsTyped[key] = value;
                                }
                            }
                            currentSymbolData.strategyParams = bestParamsTyped;
                        } else { // Fallback to defaults if no best result
                             currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                                acc[p.name] = p.type === 'integer' ? parseInt(p.default) : p.type === 'float' ? parseFloat(p.default) : p.default; return acc;}, {});
                        }
                    } else { // Opt not completed or failed
                        console.warn(`Quick optimization status: ${jobStatus?.status}. Using default strategy params (typed).`);
                        currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                            acc[p.name] = p.type === 'integer' ? parseInt(p.default) : p.type === 'float' ? parseFloat(p.default) : p.default; return acc; }, {});
                    }
                } else {  // Opt job start failed
                    console.warn("Quick optimization job could not be started or failed immediately. Using default strategy params (typed). Job response:", optJob);
                    currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                         acc[p.name] = p.type === 'integer' ? parseInt(p.default) : p.type === 'float' ? parseFloat(p.default) : p.default; return acc; }, {});
                }
            } else { // No numeric params or no token
                 console.log("No numeric parameters to optimize or no token selected. Using default strategy params (typed).");
                 currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                    acc[p.name] = p.type === 'integer' ? parseInt(p.default) : p.type === 'float' ? parseFloat(p.default) : p.default; return acc; }, {});
            }
        } catch (error) {
            console.error("Error during quick optimization for default params:", error);
            const errorMessage = error.data?.detail || error.data?.message || error.message || (error.statusText ? `${error.status} ${error.statusText}`: "Unknown error during optimization.");
            showModal("Parameter Error", `Could not fetch optimal parameters. Using defaults. Error: ${errorMessage}`);
            currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                acc[p.name] = p.type === 'integer' ? parseInt(p.default) : p.type === 'float' ? parseFloat(p.default) : p.default; return acc;}, {});
        } finally {
            const paramsForUI = { ...currentSymbolData.strategyParams }; 
            strategyConfig.parameters.forEach(p => {
                if (paramsForUI[p.name] === undefined) {
                    paramsForUI[p.name] = p.type === 'integer' ? parseInt(p.default) : p.type === 'float' ? parseFloat(p.default) : p.default;
                }
                if (p.type === 'integer') paramsForUI[p.name] = Math.round(parseFloat(paramsForUI[p.name]));
                else if (p.type === 'float' && typeof paramsForUI[p.name] !== 'number') paramsForUI[p.name] = parseFloat(paramsForUI[p.name]);
            });
            createStrategyParamsInputs(strategyParamsContainer, strategyConfig.parameters, paramsForUI, false); // 'false' for single value inputs
            showLoading(false);
            // Automatically apply to chart after params are updated
            // This makes the dashboard more dynamic. Remove if apply button is strictly required.
            if(currentSymbolData.token && currentSymbolData.strategyId){
                 await applySettingsToChart();
            }
        }
    } else if (strategyParamsContainer) {
        strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Select a strategy to see its parameters.</p>';
        // Optionally clear chart if strategy becomes invalid or unselected
        // if (window.chartInstance) clearChart(window.chartInstance);
        // if (chartHeader) chartHeader.textContent = 'Select strategy and symbol.';
    }
}


async function applySettingsToChart() {
    if (!window.chartInstance) {
        showModal('Chart Error', 'Chart is not initialized.');
        return;
    }
    
    currentSymbolData.exchange = exchangeSelect.value;
    currentSymbolData.token = symbolSelect.value;
    const selectedSymbolObj = availableSymbols.find(s => s.token === currentSymbolData.token);
    currentSymbolData.symbol = selectedSymbolObj ? selectedSymbolObj.symbol : (symbolSelect.options[symbolSelect.selectedIndex]?.text || currentSymbolData.token);
    
    let apiTimeframe = timeframeSelect.value;
    if (apiTimeframe === 'day') apiTimeframe = 'D'; 
    currentSymbolData.timeframe = timeframeSelect.value; 
    
    let newStrategyId = strategySelect.value;
    if (newStrategyId === "" && availableStrategies.length > 0) { // If "None" or empty option selected
        newStrategyId = currentSymbolData.strategyId || null; // Use stored or null
    }
    currentSymbolData.strategyId = newStrategyId;

    const strategyConfig = availableStrategies.find(s => s.id === currentSymbolData.strategyId); 
    const finalStrategyParams = {};

    if (strategyConfig) { // If a valid strategy is selected
        const uiParams = getStrategyParamsValues(strategyConfig.parameters, false); // Get from UI
        strategyConfig.parameters.forEach(p_conf => {
            const paramName = p_conf.name;
            let paramValue = uiParams[paramName]; 

            if (paramValue === undefined || paramValue === "") { // If UI has no value, use stored or default
                paramValue = currentSymbolData.strategyParams[paramName] !== undefined 
                           ? currentSymbolData.strategyParams[paramName] 
                           : p_conf.default;
            }
            // Type casting
            if (p_conf.type === 'integer') finalStrategyParams[paramName] = parseInt(paramValue);
            else if (p_conf.type === 'float') finalStrategyParams[paramName] = parseFloat(paramValue);
            else finalStrategyParams[paramName] = paramValue; // String or boolean
        });
        currentSymbolData.strategyParams = { ...finalStrategyParams }; // Update stored params
    } else { // No strategy selected or "None"
        currentSymbolData.strategyParams = {}; // Clear params if no strategy
    }
    
    const finalStrategyIdForAPI = (currentSymbolData.strategyId && currentSymbolData.strategyId !== "None" && currentSymbolData.strategyId !== "") ? currentSymbolData.strategyId : null;
    
    if (!currentSymbolData.token) {
        showModal('Input Error', 'Please select a symbol.');
        chartHeader.textContent = 'Please select a symbol to load chart.';
        if (window.chartInstance) clearChart(window.chartInstance);
        return;
    }

    showLoading(true);
    chartHeader.textContent = `Loading ${currentSymbolData.symbol || currentSymbolData.token} (${currentSymbolData.timeframe})...`;
    if (window.chartInstance) clearChart(window.chartInstance); // Clear previous series and markers

    try {
        const chartRequest = {
            exchange: currentSymbolData.exchange,
            token: currentSymbolData.token,
            timeframe: apiTimeframe, 
            strategy_id: finalStrategyIdForAPI, 
            strategy_params: finalStrategyIdForAPI ? currentSymbolData.strategyParams : {}, 
            start_date: formatDateForAPI(new Date(new Date().setDate(new Date().getDate() - 365))), 
            end_date: formatDateForAPI(new Date())
        };
        console.log("[applySettingsToChart] chartRequest payload:", JSON.parse(JSON.stringify(chartRequest))); 

        const data = await getChartData(chartRequest);

        if (data && data.ohlc_data && data.ohlc_data.length > 0) {
            const ohlcForChart = data.ohlc_data.map(d => ({
                time: formatTimeForLightweightCharts(d.time), // Expects d.time to be UTC epoch seconds
                open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume 
            }));
            window.candlestickSeries = addOrUpdateCandlestickSeries(window.chartInstance, ohlcForChart);

            if (data.indicator_data && Array.isArray(data.indicator_data) && data.indicator_data.length > 0) {
                const indicatorColors = { fast_ema: 'rgba(0, 150, 136, 0.8)', slow_ema: 'rgba(255, 82, 82, 0.8)' }; 
                const transformedIndicatorData = {};
                data.indicator_data.forEach(indicatorSeries => {
                    if (indicatorSeries.name && Array.isArray(indicatorSeries.data)) {
                        let simpleKey = indicatorSeries.name.toLowerCase().replace(/\s*\(.*\)/, '').replace(/\s+/g, '_');
                        transformedIndicatorData[simpleKey] = indicatorSeries.data.map(indPt => ({
                            time: formatTimeForLightweightCharts(indPt.time), // Expects indPt.time as UTC epoch seconds
                            value: indPt.value
                        }));
                    }
                });
                addOrUpdateIndicatorSeries(window.chartInstance, transformedIndicatorData, indicatorColors);
            }

            if (data.trade_markers && window.candlestickSeries && data.trade_markers.length > 0) {
                 const markersForChart = data.trade_markers.map(m => ({
                    ...m,
                    time: formatTimeForLightweightCharts(m.time), // Expects m.time as UTC epoch seconds
                }));
                addTradeMarkers(window.candlestickSeries, markersForChart);
            }
            fitChartContent(window.chartInstance);
            chartHeader.textContent = `${data.chart_header_info || (currentSymbolData.symbol + ' (' + currentSymbolData.timeframe + ')')}`;
        } else {
            chartHeader.textContent = `No data available for ${currentSymbolData.symbol || currentSymbolData.token}.`;
            showModal('No Data', `No chart data found for the selected criteria. ${data.message || ''}`);
        }
    } catch (error) {
        console.error("Error applying settings to chart:", error);
        chartHeader.textContent = `Error loading chart for ${currentSymbolData.symbol || currentSymbolData.token}.`;
        const errorMessage = error.data?.detail || error.data?.message || error.message || (error.statusText ? `${error.status} ${error.statusText}`: "Unknown error loading chart.");
        showModal('Chart Error', `Failed to load chart data: ${errorMessage}`);
    } finally {
        showLoading(false);
    }
}