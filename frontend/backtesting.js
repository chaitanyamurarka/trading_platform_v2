// backtesting.js

let currentBacktestSettings = {
    exchange: 'NSE', token: '3456', symbol: 'TATAMOTORS', timeframe: '1min',
    strategyId: 'ema_crossover', initialCapital: 100000,
    startDate: '', endDate: '', strategyParams: {}
};
let backtestChartEquity = null, backtestChartDrawdown = null;
let backtestEquitySeries = null, backtestDrawdownSeries = null;
let backtestCandlestickChart = null; // For the new main chart

let backtestExchangeSelect, backtestSymbolSelect, backtestTimeframeSelect,
    backtestStrategySelect, backtestInitialCapitalInput, backtestStartDateInput,
    backtestEndDateInput, backtestStrategyParamsContainer, runBacktestButton,
    backtestResultsContainer, performanceSummaryContainer, tradesTableBody,
    equityCurveChartContainer, drawdownChartContainer,
    backtestCandlestickChartContainer; // HTML element for the new main chart

async function initBacktestingPage() {
    console.log("Initializing Backtesting Page...");
    backtestExchangeSelect = document.getElementById('backtestExchangeSelect');
    backtestSymbolSelect = document.getElementById('backtestSymbolSelect');
    backtestTimeframeSelect = document.getElementById('backtestTimeframeSelect');
    backtestStrategySelect = document.getElementById('backtestStrategySelect');
    backtestInitialCapitalInput = document.getElementById('backtestInitialCapital');
    backtestStartDateInput = document.getElementById('backtestStartDate');
    backtestEndDateInput = document.getElementById('backtestEndDate');
    backtestStrategyParamsContainer = document.getElementById('backtestStrategyParamsContainer').querySelector('.parameter-grid');
    runBacktestButton = document.getElementById('runBacktestButton');
    backtestResultsContainer = document.getElementById('backtestResultsContainer');
    performanceSummaryContainer = document.getElementById('performanceSummary');
    tradesTableBody = document.getElementById('tradesTableBody');
    equityCurveChartContainer = document.getElementById('equityCurveChartContainer');
    drawdownChartContainer = document.getElementById('drawdownChartContainer');
    // Assuming you will add a div with this ID in your backtesting.html
    backtestCandlestickChartContainer = document.getElementById('backtestCandlestickChartContainer');


    currentBacktestSettings.exchange = currentBacktestSettings.exchange || 'NSE';
    currentBacktestSettings.token = currentBacktestSettings.token || '3456';
    currentBacktestSettings.symbol = currentBacktestSettings.symbol || 'TATAMOTORS';
    currentBacktestSettings.timeframe = currentBacktestSettings.timeframe || '1min';
    currentBacktestSettings.strategyId = currentBacktestSettings.strategyId || 'ema_crossover';
    currentBacktestSettings.initialCapital = currentBacktestSettings.initialCapital !== undefined ? parseFloat(currentBacktestSettings.initialCapital) : 100000;
    if (isNaN(currentBacktestSettings.initialCapital) || currentBacktestSettings.initialCapital <= 0) {
        currentBacktestSettings.initialCapital = 100000;
    }
    currentBacktestSettings.strategyParams = currentBacktestSettings.strategyParams || {};

    setDefaultDateInputs(backtestStartDateInput, backtestEndDateInput, 365);
    currentBacktestSettings.startDate = backtestStartDateInput.value;
    currentBacktestSettings.endDate = backtestEndDateInput.value;

    runBacktestButton.addEventListener('click', executeBacktest);
    backtestExchangeSelect.addEventListener('change', handleBacktestExchangeChange);
    backtestSymbolSelect.addEventListener('change', () => { currentBacktestSettings.token = backtestSymbolSelect.value; });
    backtestStrategySelect.addEventListener('change', updateBacktestStrategyParamsUI);

    showLoading(true);
    try {
        if (!availableStrategies || availableStrategies.length === 0) {
            const strategiesData = await getAvailableStrategies();
            if (strategiesData && strategiesData.strategies) {
                availableStrategies = strategiesData.strategies;
                if (availableStrategies.length > 0 && !availableStrategies.find(s => s.id === currentBacktestSettings.strategyId)) {
                    currentBacktestSettings.strategyId = availableStrategies[0].id;
                } else if (availableStrategies.length === 0) {
                     currentBacktestSettings.strategyId = '';
                }
            }
        }
        populateSelect(backtestStrategySelect, availableStrategies, 'id', 'name', currentBacktestSettings.strategyId);

        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        populateSelect(backtestExchangeSelect, exchanges, 'id', 'name', currentBacktestSettings.exchange);

        await loadBacktestSymbols(currentBacktestSettings.exchange, currentBacktestSettings.token);

        updateBacktestStrategyParamsUI();

        backtestTimeframeSelect.value = currentBacktestSettings.timeframe;
        backtestInitialCapitalInput.value = currentBacktestSettings.initialCapital;
        if(currentBacktestSettings.startDate) backtestStartDateInput.value = currentBacktestSettings.startDate;
        if(currentBacktestSettings.endDate) backtestEndDateInput.value = currentBacktestSettings.endDate;

        // Initialize the new candlestick chart area (optional, could also be done in executeBacktest)
        if (backtestCandlestickChartContainer) {
            backtestCandlestickChartContainer.innerHTML = '<p class="text-center p-4 text-gray-400">Run a backtest to see the chart with strategy.</p>';
             // If you have a common chart initialization utility like in dashboard.js:
            // window.backtestMainChart = initChart('backtestCandlestickChartContainer');
            // new ResizeObserver(() => {
            //     if (window.backtestMainChart && document.getElementById('backtestCandlestickChartContainer')) {
            //         resizeChart(window.backtestMainChart, 'backtestCandlestickChartContainer');
            //     }
            // }).observe(document.getElementById('backtestCandlestickChartContainer'));

        }


    } catch (error) {
        console.error("Error initializing backtesting page:", error);
        showModal('Initialization Error', `Failed to initialize backtesting page: ${error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}

async function loadBacktestSymbols(exchange, defaultToken = '') {
    showLoading(true);
    try {
        const data = await getSymbolsForExchange(exchange); // api.js
        const allSymbols = data.symbols || [];
        const filteredSymbols = allSymbols.filter(s => ['EQ', 'INDEX', 'FUTIDX', 'FUTSTK'].includes(s.instrument) || !s.instrument);
        populateSelect(backtestSymbolSelect, filteredSymbols, 'token', 'trading_symbol', defaultToken || (filteredSymbols.length > 0 ? filteredSymbols[0].token : '')); // ui.js

        if (backtestSymbolSelect.value) {
            currentBacktestSettings.token = backtestSymbolSelect.value;
        } else if (defaultToken) {
            currentBacktestSettings.token = defaultToken;
            if (!filteredSymbols.some(s => s.token === defaultToken)) {
                const selectedSymbolObj = allSymbols.find(s => s.token === defaultToken);
                if(selectedSymbolObj){
                    const opt = document.createElement('option');
                    opt.value = defaultToken; opt.textContent = selectedSymbolObj.trading_symbol; opt.selected = true;
                    backtestSymbolSelect.appendChild(opt);
                }
            }
        }
    } catch (error) {
        console.error(`Error fetching symbols for backtest ${exchange}:`, error);
        showModal('Symbol Error', `Could not load symbols for backtest: ${error.data?.detail || error.message}`); // ui.js
        backtestSymbolSelect.innerHTML = '<option value="">Error loading</option>';
    } finally {
        showLoading(false); // ui.js
    }
}

function handleBacktestExchangeChange() {
    currentBacktestSettings.exchange = backtestExchangeSelect.value;
    loadBacktestSymbols(currentBacktestSettings.exchange);
}

function updateBacktestStrategyParamsUI() {
    currentBacktestSettings.strategyId = backtestStrategySelect.value;
    const strategyConfig = availableStrategies.find(s => s.id === currentBacktestSettings.strategyId);
    if (strategyConfig && backtestStrategyParamsContainer) {
        const paramsToLoad = currentBacktestSettings.strategyParams && Object.keys(currentBacktestSettings.strategyParams).length > 0 &&
                             currentBacktestSettings.strategyParams.constructor === Object
                           ? currentBacktestSettings.strategyParams
                           : strategyConfig.parameters.reduce((acc, p) => { acc[p.name] = p.default_value; return acc; }, {});
        createStrategyParamsInputs(backtestStrategyParamsContainer, strategyConfig.parameters, paramsToLoad, false); // ui.js
    } else if (backtestStrategyParamsContainer) {
        backtestStrategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Select a strategy.</p>';
    }
}

async function executeBacktest() {
    showLoading(true); // ui.js
    backtestResultsContainer.classList.add('hidden');
    if (backtestCandlestickChartContainer) {
         backtestCandlestickChartContainer.innerHTML = '<p class="text-center p-4 text-gray-400">Loading chart data...</p>';
    }


    currentBacktestSettings.exchange = backtestExchangeSelect.value;
    currentBacktestSettings.token = backtestSymbolSelect.value;
    const selectedSymbolText = backtestSymbolSelect.options[backtestSymbolSelect.selectedIndex]?.text;
    currentBacktestSettings.symbol = selectedSymbolText || currentBacktestSettings.token;

    currentBacktestSettings.timeframe = backtestTimeframeSelect.value;
    currentBacktestSettings.strategyId = backtestStrategySelect.value;
    currentBacktestSettings.initialCapital = parseFloat(backtestInitialCapitalInput.value);
    currentBacktestSettings.startDate = backtestStartDateInput.value;
    currentBacktestSettings.endDate = backtestEndDateInput.value;

    const strategyConfig = availableStrategies.find(s => s.id === currentBacktestSettings.strategyId);
    if (!strategyConfig) {
        showModal('Error', 'Strategy configuration not found.'); // ui.js
        showLoading(false); // ui.js
        return;
    }
    currentBacktestSettings.strategyParams = getStrategyParamsValues(strategyConfig.parameters, false); // ui.js


    const paramRanges = [];
    if (strategyConfig.parameters && currentBacktestSettings.strategyParams) {
        for (const paramDef of strategyConfig.parameters) {
            const paramName = paramDef.name;
            if (Object.hasOwnProperty.call(currentBacktestSettings.strategyParams, paramName)) {
                let paramValue = currentBacktestSettings.strategyParams[paramName];
                let stepValue = 1;

                if (paramDef.type === 'float') {
                    paramValue = parseFloat(paramValue);
                    stepValue = parseFloat(paramDef.step || 0.01);
                } else if (paramDef.type === 'integer' || paramDef.type === 'int') {
                    paramValue = parseInt(paramValue);
                    stepValue = parseInt(paramDef.step || 1);
                }
                stepValue = Math.max(stepValue, (paramDef.type === 'float') ? 0.000001 : 1);

                if (paramDef.type === 'integer' || paramDef.type === 'int' || paramDef.type === 'float') {
                    paramRanges.push({
                        name: paramName,
                        start_value: paramValue,
                        end_value: paramValue,
                        step: stepValue
                    });
                }
            }
        }
    }
    
    let apiTimeframe = currentBacktestSettings.timeframe;
    if (apiTimeframe === 'day') apiTimeframe = 'D';

    const optimizationRequest = {
        strategy_id: currentBacktestSettings.strategyId,
        exchange: currentBacktestSettings.exchange,
        token: currentBacktestSettings.token,
        start_date: currentBacktestSettings.startDate,
        end_date: currentBacktestSettings.endDate,
        timeframe: apiTimeframe,
        initial_capital: currentBacktestSettings.initialCapital,
        parameter_ranges: paramRanges,
        metric_to_optimize: 'net_pnl'
    };

    try {
        console.log("Starting backtest (via optimization):", optimizationRequest);
        const optJob = await startOptimization(optimizationRequest); // api.js

        if (!optJob || !optJob.job_id || optJob.status === "FAILED") {
            const errorMsg = optJob?.data?.detail || optJob?.data?.message || optJob?.message || 'Unknown error starting job.';
            showModal('Backtest Error', `Failed to start backtest job: ${errorMsg}`); // ui.js
            showLoading(false); // ui.js
            return;
        }
        console.log("Backtest job started/queued:", optJob);

        let jobStatus = await getOptimizationStatus(optJob.job_id); // api.js
        let attempts = 0;
        const maxAttempts = 90;
        console.log(`Polling for job ${optJob.job_id} completion (max ${maxAttempts} attempts).`);

        while (jobStatus && (jobStatus.status === 'QUEUED' || jobStatus.status === 'RUNNING') && attempts < maxAttempts) {
            await new Promise(resolve => setTimeout(resolve, 2000));
            jobStatus = await getOptimizationStatus(optJob.job_id); // api.js
            attempts++;
            console.log(`Backtest job ${optJob.job_id} status: ${jobStatus?.status}, attempt: ${attempts}/${maxAttempts}`);
        }

        if (!jobStatus || jobStatus.status !== 'COMPLETED') {
            const errorMsg = jobStatus?.data?.message || jobStatus?.message || 'Job did not complete or status unknown.';
            showModal('Backtest Error', `Backtest job did not complete successfully. Status: ${jobStatus?.status || 'Unknown'}. Message: ${errorMsg}`); // ui.js
            if (jobStatus?.status === 'FAILED' && jobStatus?.result?.error) {
                 console.error("Optimization job failed with error:", jobStatus.result.error);
                 showModal('Backtest Error', `Backtest job failed: ${jobStatus.result.error}`); // ui.js
            }
            showLoading(false); // ui.js
            return;
        }

        console.log(`Backtest job ${optJob.job_id} COMPLETED. Fetching results.`);
        const optResults = await getOptimizationResults(optJob.job_id); // api.js
        console.log("Backtest (Optimization) Results:", optResults);

        if (optResults && optResults.best_result) {
            const bestResult = optResults.best_result;
            const performanceMetrics = bestResult.performance_metrics;
            const actualParametersRun = bestResult.parameters;

            if (performanceMetrics && typeof performanceMetrics === 'object') {
                displayPerformanceSummary(performanceSummaryContainer, performanceMetrics); // ui.js
                backtestResultsContainer.classList.remove('hidden');
            } else {
                performanceSummaryContainer.innerHTML = `<p class="text-center p-4 text-gray-400">Performance metrics not available.</p>`;
            }
            
            // Trades table - use bestResult.trades if available, otherwise show message
            // Based on logs, bestResult.trades might be undefined.
            if (bestResult.trades && Array.isArray(bestResult.trades)) {
                populateTradesTable(tradesTableBody, bestResult.trades); // ui.js
            } else {
                 tradesTableBody.innerHTML = '<tr><td colspan="7" class="text-center py-4">Detailed trade data not available from this backtest method. See trade markers on chart.</td></tr>';
            }

            // Equity and Drawdown Curves - Data not available from current optResults structure based on logs
            equityCurveChartContainer.innerHTML = '<p class="text-center p-4">Equity curve data not available with this backtest method.</p>';
            if (backtestChartEquity) { try {backtestChartEquity.remove();} catch(e){} backtestChartEquity = null; }

            drawdownChartContainer.innerHTML = '<p class="text-center p-4">Drawdown curve data not available with this backtest method.</p>';
            if (backtestChartDrawdown) { try {backtestChartDrawdown.remove();} catch(e){} backtestChartDrawdown = null; }
            
            // Now, fetch and display the main chart with strategy applied
            await displayMainBacktestChart(currentBacktestSettings, actualParametersRun, optJob.job_id);

        } else {
            const errorMsg = optResults?.data?.detail || optResults?.data?.message || optResults?.message || 'Optimization results are missing the best_result field.';
            showModal('Backtest Error', `Backtest completed but returned no parsable results or missing 'best_result'. ${errorMsg}`); // ui.js
            equityCurveChartContainer.innerHTML = '<p class="text-center p-4">Error loading backtest results.</p>';
            drawdownChartContainer.innerHTML = '<p class="text-center p-4">Error loading backtest results.</p>';
            if (backtestCandlestickChartContainer) {
                backtestCandlestickChartContainer.innerHTML = '<p class="text-center p-4 text-red-500">Error loading chart data due to backtest result issue.</p>';
            }
        }
    } catch (error) {
        console.error("Error running backtest (via optimization):", error);
        const errorMsg = error.data?.detail || error.data?.message || error.message || 'An unknown error occurred.';
        showModal('Backtest Execution Error', `Failed to run backtest: ${errorMsg}`); // ui.js
    } finally {
        showLoading(false); // ui.js
    }
}

async function displayMainBacktestChart(settings, strategyParamsForChart, jobId) {
    if (!backtestCandlestickChartContainer) {
        console.warn("Main backtest chart container (backtestCandlestickChartContainer) not found.");
        return;
    }
    showLoading(true); // ui.js
    backtestCandlestickChartContainer.innerHTML = `<p class="text-center p-4">Loading chart for backtest job ${jobId}...</p>`;

    try {
        let apiTimeframe = settings.timeframe;
        if (apiTimeframe === 'day') apiTimeframe = 'D';

        const chartRequest = {
            exchange: settings.exchange,
            token: settings.token,
            timeframe: apiTimeframe,
            strategy_id: settings.strategyId,
            strategy_params: strategyParamsForChart || {}, // Use parameters from opt_results
            start_date: settings.startDate,
            end_date: settings.endDate
        };
        console.log("[backtesting.js] Requesting /chart_data_with_strategy with params:", chartRequest);

        const chartData = await getChartData(chartRequest); // api.js
        console.log("[backtesting.js] Received chart data:", chartData);

        if (backtestCandlestickChart) {
            try { backtestCandlestickChart.remove(); } catch(e) { console.warn("Error removing old candlestick chart", e); }
            backtestCandlestickChart = null;
        }
        
        // --- Chart Rendering Logic (Simplified - adapt from dashboard.js/chartSetup.js) ---
        // You'll need to use functions like initChart, addOrUpdateCandlestickSeries, etc.
        // from your chartSetup.js or ui.js, similar to how dashboard.js does it.
        
        // Ensure the container is clean for new chart
        backtestCandlestickChartContainer.innerHTML = ''; 
        // Initialize a new chart instance targeting 'backtestCandlestickChartContainer'
        // This assumes 'initChart' is available and works like in dashboard.js
        const chart = initChart('backtestCandlestickChartContainer');
        if (!chart) {
            backtestCandlestickChartContainer.innerHTML = '<p class="text-center p-4 text-red-500">Failed to initialize chart.</p>';
            throw new Error("Failed to initialize chart instance for backtest display.");
        }
        backtestCandlestickChart = chart; // Store the new chart instance


        if (chartData && chartData.ohlc_data && chartData.ohlc_data.length > 0) {
            const ohlcForChart = chartData.ohlc_data.map(d => ({
                time: formatTimeForLightweightCharts(d.time), // Ensure this helper is available
                open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume
            }));
            
            // Assumes addOrUpdateCandlestickSeries is available (from chartSetup.js or similar)
            const candlestickSeries = addOrUpdateCandlestickSeries(backtestCandlestickChart, ohlcForChart, 'Backtest Series');
            
            if (chartData.indicator_data && Array.isArray(chartData.indicator_data) && chartData.indicator_data.length > 0) {
                const indicatorColors = { fast_ema: 'rgba(0, 150, 136, 0.8)', slow_ema: 'rgba(255, 82, 82, 0.8)' }; // Example colors
                const transformedIndicatorData = {};
                chartData.indicator_data.forEach(indicatorSeries => {
                    if (indicatorSeries.name && Array.isArray(indicatorSeries.data)) {
                        let simpleKey = indicatorSeries.name.toLowerCase().replace(/\s*\(.*\)/, '').replace(/\s+/g, '_');
                        transformedIndicatorData[simpleKey] = indicatorSeries.data.map(indPt => ({
                            time: formatTimeForLightweightCharts(indPt.time),
                            value: indPt.value
                        }));
                    }
                });
                 // Assumes addOrUpdateIndicatorSeries is available
                addOrUpdateIndicatorSeries(backtestCandlestickChart, transformedIndicatorData, indicatorColors);
            }

            if (chartData.trade_markers && candlestickSeries && chartData.trade_markers.length > 0) {
                 const markersForChart = chartData.trade_markers.map(m => ({
                    ...m,
                    time: formatTimeForLightweightCharts(m.time),
                }));
                // Assumes addTradeMarkers is available
                addTradeMarkers(candlestickSeries, markersForChart);
            }
            // Assumes fitChartContent is available
            fitChartContent(backtestCandlestickChart);
            // Update a header if you have one for this chart
            // document.getElementById('backtestChartHeader').textContent = `${chartData.chart_header_info || (settings.symbol + ' (' + settings.timeframe + ') - Backtest Visualization')}`;
        } else {
            backtestCandlestickChartContainer.innerHTML = `<p class="text-center p-4">No chart data (OHLC) available for ${settings.symbol}. ${chartData?.message || ''}</p>`;
        }
        // --- End Chart Rendering Logic ---

    } catch (error) {
        console.error("[backtesting.js] Error displaying main backtest chart:", error);
        const errorMsg = error.data?.detail || error.data?.message || error.message || 'Unknown error loading chart.';
        backtestCandlestickChartContainer.innerHTML = `<p class="text-center p-4 text-red-500">Failed to load chart: ${errorMsg}</p>`;
    } finally {
        showLoading(false); // ui.js
    }
}

// Make sure formatTimeForLightweightCharts helper is available in this scope
// (it's in dashboard.js, might need to be moved to a shared ui.js or duplicated)
function formatTimeForLightweightCharts(timeValue) {
    if (typeof timeValue === 'number') {
        if (timeValue > 2000000000000) { // Heuristic for ms
            return Math.floor(timeValue / 1000);
        }
        return timeValue;
    }
    if (typeof timeValue === 'string') {
        const d = new Date(timeValue);
        if (!isNaN(d.getTime())) {
            return Math.floor(d.getTime() / 1000);
        }
    }
     console.warn(`[formatTimeForLightweightCharts] Unexpected timeValue: ${timeValue}`);
    return timeValue; // Fallback
}