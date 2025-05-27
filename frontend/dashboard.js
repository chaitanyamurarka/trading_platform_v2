// dashboard.js

let availableStrategies = []; // To store strategy configurations
let availableSymbols = []; // To store symbols for the selected exchange

// DOM Elements specific to dashboard (will be accessed after page load)
let exchangeSelect, symbolSelect, timeframeSelect, strategySelect,
    strategyParamsContainer, applyChartButton, chartHeader,
    goToBacktestButton, goToOptimizeButton;


/**
 * Helper function to format time for Lightweight Charts.
 * Accepts ISO strings (extracts<y_bin_46>-MM-DD),<y_bin_46>-MM-DD strings, or Unix timestamps (assumed seconds).
 * @param {string|number} timeValue - The time value from the API.
 * @returns {string|number} - Formatted time suitable for Lightweight Charts.
 */
function formatTimeForLightweightCharts(timeValue) {
    if (typeof timeValue === 'string') {
        if (timeValue.includes('T')) {
            return timeValue.split('T')[0]; // Convert<y_bin_46>-MM-DDTHH:MM:SS to<y_bin_46>-MM-DD
        }
        // Check if it's already in<y_bin_46>-MM-DD format
        if (/^\d{4}-\d{2}-\d{2}$/.test(timeValue)) {
            return timeValue;
        }
        // If it's a string but not in expected format, try parsing as date then formatting
        const date = new Date(timeValue);
        if (!isNaN(date.getTime())) {
            return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
        }
        console.warn(`Unparseable string time format: ${timeValue}`);
        return timeValue; // Fallback
    } else if (typeof timeValue === 'number') {
        // Assuming the number is a Unix timestamp in seconds or milliseconds.
        // Lightweight Charts expects seconds.
        if (timeValue > 2000000000000) { // Heuristic: if timestamp is for year > 2033 (approx 2 * 10^12 ms), likely ms
            return Math.floor(timeValue / 1000);
        }
        return timeValue; // Assume seconds
    }
    console.warn(`Unexpected time format: ${timeValue}, type: ${typeof timeValue}. Passing as is.`);
    return timeValue; // Fallback for other types
}


/**
 * Initializes the Dashboard page.
 * This function is called when the dashboard page is loaded.
 */
async function initDashboardPage() {
    console.log("Initializing Dashboard Page...");
    // Assign DOM elements
    exchangeSelect = document.getElementById('exchangeSelect');
    symbolSelect = document.getElementById('symbolSelect');
    timeframeSelect = document.getElementById('timeframeSelect');
    strategySelect = document.getElementById('strategySelect');
    strategyParamsContainer = document.getElementById('strategyParamsContainer');
    applyChartButton = document.getElementById('applyChartButton');
    chartHeader = document.getElementById('chartHeader');
    goToBacktestButton = document.getElementById('goToBacktestButton');
    goToOptimizeButton = document.getElementById('goToOptimizeButton');

    // Set default values from currentSymbolData state
    timeframeSelect.value = currentSymbolData.timeframe;

    // Add event listeners
    exchangeSelect.addEventListener('change', handleExchangeChange);
    symbolSelect.addEventListener('change', handleSymbolChange);
    strategySelect.addEventListener('change', handleStrategyChangeOnDashboard);
    applyChartButton.addEventListener('click', applySettingsToChart);
    goToBacktestButton.addEventListener('click', () => {
        currentBacktestSettings = { ...currentSymbolData }; // Pass current dashboard state
        loadPage('backtesting');
    });
    goToOptimizeButton.addEventListener('click', () => {
        currentOptimizationSettings = { ...currentSymbolData }; // Pass current dashboard state
        loadPage('optimization');
    });


    showLoading(true);
    try {
        if (window.chartInstance) { // If chart exists from another page, clear it
            clearChart(window.chartInstance);
            window.chartInstance = null; // Ensure it's re-initialized for dashboard
        }
        window.chartInstance = initChart('chartContainer');
        if (!window.chartInstance) {
            showModal('Chart Error', 'Could not initialize the main chart.');
            showLoading(false);
            return;
        }
        // Handle chart resize
        new ResizeObserver(() => {
            if (window.chartInstance && document.getElementById('chartContainer')) {
                resizeChart(window.chartInstance, 'chartContainer');
            }
        }).observe(document.getElementById('chartContainerWrapper'));


        const strategiesData = await getAvailableStrategies();
        if (strategiesData && strategiesData.strategies) {
            availableStrategies = strategiesData.strategies;
            // Use 'id' from models.StrategyInfo, not 'strategy_id'
            populateSelect(strategySelect, availableStrategies, 'id', 'name', currentSymbolData.strategyId);
            // Ensure currentSymbolData.strategyId is updated if a selection was made or defaulted
            if (strategySelect.value) {
                currentSymbolData.strategyId = strategySelect.value;
            } else if (availableStrategies.length > 0) {
                currentSymbolData.strategyId = availableStrategies[0].id; // Default to first if no specific default
                strategySelect.value = currentSymbolData.strategyId;
            } else {
                currentSymbolData.strategyId = null; // No strategies available
            }
        } else {
            showModal('Error', 'Could not load strategies.');
            availableStrategies = []; // Ensure it's an array
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

        // This will also trigger initial optimization for best params AND initial chart load
        await updateDashboardStrategyParamsUI();

    } catch (error) {
        console.error("Error initializing dashboard:", error);
        showModal('Initialization Error', `Failed to initialize dashboard: ${error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}

/**
 * Fetches and populates symbols for the selected exchange.
 * @param {string} exchange - The selected exchange.
 * @param {string} [defaultToken=''] - Optional token to select by default.
 */
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
                 if (![...symbolSelect.options].some(opt => opt.value === defaultToken)) {
                    console.warn(`Default token ${defaultToken} was not in filtered list but found in all symbols. Ensure populateSelect handles this case.`);
                 }
            } else {
                currentSymbolData.token = '';
                currentSymbolData.symbol = '';
            }
        } else if (filteredSymbols.length > 0) {
            const firstSymbol = filteredSymbols[0];
            currentSymbolData.token = firstSymbol.token;
            currentSymbolData.symbol = firstSymbol.symbol;
            symbolSelect.value = firstSymbol.token; // Explicitly set select value
        } else {
            currentSymbolData.token = '';
            currentSymbolData.symbol = '';
        }
    } catch (error) {
        console.error(`Error fetching symbols for ${exchange}:`, error);
        showModal('Symbol Error', `Could not load symbols for ${exchange}: ${error.data?.detail || error.message}`);
        symbolSelect.innerHTML = '<option value="">Error loading</option>';
        currentSymbolData.token = '';
        currentSymbolData.symbol = '';
    } finally {
        showLoading(false);
    }
}

/**
 * Handles exchange selection change.
 */
async function handleExchangeChange() {
    currentSymbolData.exchange = exchangeSelect.value;
    await loadSymbolsForExchange(currentSymbolData.exchange); 
    // await updateDashboardStrategyParamsUI(); // Re-fetch optimal params for new default symbol and reload chart
}

/**
 * Handles symbol selection change.
 */
function handleSymbolChange() {
    const selectedToken = symbolSelect.value;
    const selectedSymbolObj = availableSymbols.find(s => s.token === selectedToken);
    if (selectedSymbolObj) {
        currentSymbolData.token = selectedToken;
        currentSymbolData.symbol = selectedSymbolObj.symbol;
    } else {
        currentSymbolData.token = selectedToken; 
        currentSymbolData.symbol = symbolSelect.options[symbolSelect.selectedIndex]?.text || selectedToken;
    }
    // await updateDashboardStrategyParamsUI(); // Re-fetch optimal params for new symbol and reload chart
}

/**
 * Handles strategy selection change on the dashboard.
 * Updates the strategy parameters UI and reloads the chart with new optimal params.
 */
async function handleStrategyChangeOnDashboard() {
    currentSymbolData.strategyId = strategySelect.value;
    await updateDashboardStrategyParamsUI(); 
}

/**
 * Updates the strategy parameters UI on the dashboard.
 * Fetches best parameters via optimization if required, then applies to chart.
 */
async function updateDashboardStrategyParamsUI() {
    const selectedStrategyId = strategySelect.value || currentSymbolData.strategyId; 
    if (!selectedStrategyId) {
        console.warn("No strategy selected, cannot update params or chart.");
        if (strategyParamsContainer) strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Please select a strategy.</p>';
        if (window.chartInstance) clearChart(window.chartInstance);
        if (chartHeader) chartHeader.textContent = 'Please select a strategy.';
        return;
    }
    currentSymbolData.strategyId = selectedStrategyId; 

    const strategyConfig = availableStrategies.find(s => s.id === selectedStrategyId); // Use 'id' here

    if (strategyConfig && strategyParamsContainer) {
        strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Fetching optimal parameters...</p>';
        showLoading(true);

        try {
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
                    metric_to_optimize: 'net_pnl'
                };
                console.log("[updateDashboardStrategyParamsUI] optRequest payload:", JSON.parse(JSON.stringify(optRequest)));

                const optJob = await startOptimization(optRequest);
                if (optJob && optJob.job_id && optJob.status !== "FAILED") {
                    let jobStatus = await getOptimizationStatus(optJob.job_id);
                    let attempts = 0;
                    const maxAttempts = 15; 
                    while (jobStatus && (jobStatus.status === 'QUEUED' || jobStatus.status === 'RUNNING') && attempts < maxAttempts) {
                        await new Promise(resolve => setTimeout(resolve, 2000));
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
                                } else {
                                    bestParamsTyped[key] = value;
                                }
                            }
                            currentSymbolData.strategyParams = bestParamsTyped;
                        } else {
                            currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                                acc[p.name] = p.type === 'integer' ? parseInt(p.default) 
                                            : p.type === 'float' ? parseFloat(p.default) 
                                            : p.default;
                                return acc;
                            }, {}); 
                        }
                    } else {
                        console.warn(`Quick optimization status: ${jobStatus?.status}. Using default strategy params (typed).`);
                        currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                            acc[p.name] = p.type === 'integer' ? parseInt(p.default) 
                                        : p.type === 'float' ? parseFloat(p.default) 
                                        : p.default;
                            return acc;
                        }, {}); 
                    }
                } else { 
                    console.warn("Quick optimization job could not be started or failed immediately. Using default strategy params (typed). Job response:", optJob);
                    currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                        acc[p.name] = p.type === 'integer' ? parseInt(p.default) 
                                    : p.type === 'float' ? parseFloat(p.default) 
                                    : p.default;
                        return acc;
                    }, {}); 
                }
            } else { 
                 console.log("No numeric parameters to optimize or no token selected. Using default strategy params (typed).");
                 currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                    acc[p.name] = p.type === 'integer' ? parseInt(p.default) 
                                : p.type === 'float' ? parseFloat(p.default) 
                                : p.default;
                    return acc;
                }, {}); 
            }

        } catch (error) {
            console.error("Error during quick optimization for default params:", error);
            const errorMessage = error.data?.detail || error.data?.message || error.message || (error.statusText ? `${error.status} ${error.statusText}`: "Unknown error during optimization.");
            showModal("Parameter Error", `Could not fetch optimal parameters. Using defaults. Error: ${errorMessage}`);
            currentSymbolData.strategyParams = strategyConfig.parameters.reduce((acc, p) => {
                acc[p.name] = p.type === 'integer' ? parseInt(p.default) 
                            : p.type === 'float' ? parseFloat(p.default) 
                            : p.default;
                return acc;
            }, {}); 
        } finally {
            const paramsForUI = { ...currentSymbolData.strategyParams }; 
            strategyConfig.parameters.forEach(p => {
                if (paramsForUI[p.name] === undefined) {
                    paramsForUI[p.name] = p.type === 'integer' ? parseInt(p.default) 
                                        : p.type === 'float' ? parseFloat(p.default) 
                                        : p.default;
                }
                // Ensure types for UI inputs 
                if (p.type === 'integer') {
                     paramsForUI[p.name] = Math.round(parseFloat(paramsForUI[p.name])); // Ensure it's a whole number for UI
                } else if (p.type === 'float' && typeof paramsForUI[p.name] !== 'number') {
                     paramsForUI[p.name] = parseFloat(paramsForUI[p.name]);
                }
            });

            createStrategyParamsInputs(strategyParamsContainer, strategyConfig.parameters, paramsForUI, false);
            showLoading(false);
            await applySettingsToChart();
        }
    } else if (strategyParamsContainer) {
        strategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Select a strategy to see its parameters.</p>';
        if (window.chartInstance) clearChart(window.chartInstance);
        if (chartHeader) chartHeader.textContent = 'Select a strategy.';
    }
}


/**
 * Applies current selections (symbol, timeframe, strategy, params) to the chart.
 */
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
    if (apiTimeframe === 'day') {
        apiTimeframe = 'D'; 
    }
    currentSymbolData.timeframe = timeframeSelect.value; 
    
    let newStrategyId = strategySelect.value;
    if (newStrategyId === "" && availableStrategies.length > 0) {
        newStrategyId = currentSymbolData.strategyId || availableStrategies[0].id; 
    }
    currentSymbolData.strategyId = newStrategyId;

    const strategyConfig = availableStrategies.find(s => s.id === currentSymbolData.strategyId); 
    
    const finalStrategyParams = {};
    if (strategyConfig) {
        const uiParams = getStrategyParamsValues(strategyConfig.parameters, false);
        strategyConfig.parameters.forEach(p_conf => {
            const paramName = p_conf.name;
            let paramValue = uiParams[paramName]; 

            if (paramValue === undefined) { 
                paramValue = currentSymbolData.strategyParams[paramName] !== undefined 
                           ? currentSymbolData.strategyParams[paramName] 
                           : p_conf.default;
            }

            if (p_conf.type === 'integer') {
                finalStrategyParams[paramName] = parseInt(paramValue);
            } else if (p_conf.type === 'float') {
                finalStrategyParams[paramName] = parseFloat(paramValue);
            } else { 
                finalStrategyParams[paramName] = paramValue;
            }
        });
    } else {
        Object.assign(finalStrategyParams, currentSymbolData.strategyParams); 
        if (currentSymbolData.strategyId) { 
             console.warn(`Strategy config not found for ID: '${currentSymbolData.strategyId}' during applySettingsToChart. Params will be based on currentSymbolData or empty.`);
        }
    }

    const finalStrategyId = currentSymbolData.strategyId && currentSymbolData.strategyId !== "" ? currentSymbolData.strategyId : null;
    
    if (!currentSymbolData.token) {
        showModal('Input Error', 'Please select a symbol.');
        chartHeader.textContent = 'Please select a symbol to load chart.';
        if (window.chartInstance) clearChart(window.chartInstance);
        return;
    }

    showLoading(true);
    chartHeader.textContent = `Loading ${currentSymbolData.symbol || currentSymbolData.token} (${currentSymbolData.timeframe})...`;
    if (window.chartInstance) clearChart(window.chartInstance);

    try {
        const chartRequest = {
            exchange: currentSymbolData.exchange,
            token: currentSymbolData.token,
            timeframe: apiTimeframe, 
            strategy_id: finalStrategyId, 
            strategy_params: finalStrategyParams, 
            start_date: formatDateForAPI(new Date(new Date().setDate(new Date().getDate() - 365))), 
            end_date: formatDateForAPI(new Date())
        };
        
        if (chartRequest.strategy_params && chartRequest.strategy_params.fast_ema_period !== undefined) {
            console.log(`[applySettingsToChart] Pre-API Call - fast_ema_period: ${chartRequest.strategy_params.fast_ema_period}, type: ${typeof chartRequest.strategy_params.fast_ema_period}`);
        }
        if (chartRequest.strategy_params && chartRequest.strategy_params.slow_ema_period !== undefined) {
            console.log(`[applySettingsToChart] Pre-API Call - slow_ema_period: ${chartRequest.strategy_params.slow_ema_period}, type: ${typeof chartRequest.strategy_params.slow_ema_period}`);
        }
        console.log("[applySettingsToChart] chartRequest payload:", JSON.parse(JSON.stringify(chartRequest))); 


        const data = await getChartData(chartRequest);

        if (data && data.ohlc_data && data.ohlc_data.length > 0) {
            const ohlcForChart = data.ohlc_data.map(d => ({
                time: formatTimeForLightweightCharts(d.time),
                open: d.open,
                high: d.high,
                low: d.low,
                close: d.close,
                volume: d.volume 
            }));

            window.candlestickSeries = addOrUpdateCandlestickSeries(window.chartInstance, ohlcForChart);

            if (data.indicator_data && Array.isArray(data.indicator_data) && data.indicator_data.length > 0) {
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
                addOrUpdateIndicatorSeries(window.chartInstance, transformedIndicatorData, indicatorColors);
            }

            if (data.trade_markers && window.candlestickSeries && data.trade_markers.length > 0) {
                 const markersForChart = data.trade_markers.map(m => ({
                    ...m,
                    time: formatTimeForLightweightCharts(m.time), 
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
