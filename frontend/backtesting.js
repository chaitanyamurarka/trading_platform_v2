// backtesting.js

let currentBacktestSettings = { 
    exchange: 'NSE', token: '3456', symbol: 'TATAMOTORS', timeframe: '1min',
    strategyId: 'ema_crossover', initialCapital: 100000,
    startDate: '', endDate: '', strategyParams: {}
};
let backtestChartEquity = null, backtestChartDrawdown = null;
let backtestEquitySeries = null, backtestDrawdownSeries = null;

let backtestExchangeSelect, backtestSymbolSelect, backtestTimeframeSelect,
    backtestStrategySelect, backtestInitialCapitalInput, backtestStartDateInput,
    backtestEndDateInput, backtestStrategyParamsContainer, runBacktestButton,
    backtestResultsContainer, performanceSummaryContainer, tradesTableBody,
    equityCurveChartContainer, drawdownChartContainer;

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

    // Ensure critical values in currentBacktestSettings have defaults or correct types,
    // especially if populated from another page like the dashboard.
    currentBacktestSettings.exchange = currentBacktestSettings.exchange || 'NSE';
    // Ensure token and symbol have fallbacks, potentially based on availableSymbols if loaded prior or use hardcoded defaults
    currentBacktestSettings.token = currentBacktestSettings.token || '3456'; 
    currentBacktestSettings.symbol = currentBacktestSettings.symbol || 'TATAMOTORS';
    currentBacktestSettings.timeframe = currentBacktestSettings.timeframe || '1min';
    // Ensure strategyId has a fallback, potentially based on availableStrategies if loaded prior
    currentBacktestSettings.strategyId = currentBacktestSettings.strategyId || 'ema_crossover'; 
    currentBacktestSettings.initialCapital = currentBacktestSettings.initialCapital !== undefined ? parseFloat(currentBacktestSettings.initialCapital) : 100000;
    if (isNaN(currentBacktestSettings.initialCapital) || currentBacktestSettings.initialCapital <= 0) { // Also check for valid positive number
        currentBacktestSettings.initialCapital = 100000; // Default if invalid
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
                // If strategyId was a fallback and now we have strategies, ensure it's valid or pick first
                if (availableStrategies.length > 0 && !availableStrategies.find(s => s.id === currentBacktestSettings.strategyId)) {
                    currentBacktestSettings.strategyId = availableStrategies[0].id;
                } else if (availableStrategies.length === 0) {
                     currentBacktestSettings.strategyId = ''; // No strategies available
                }
            }
        }
        populateSelect(backtestStrategySelect, availableStrategies, 'id', 'name', currentBacktestSettings.strategyId);

        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        populateSelect(backtestExchangeSelect, exchanges, 'id', 'name', currentBacktestSettings.exchange);

        // It's better to set token after symbols are loaded if it's a generic default
        await loadBacktestSymbols(currentBacktestSettings.exchange, currentBacktestSettings.token); 
        
        updateBacktestStrategyParamsUI();

        backtestTimeframeSelect.value = currentBacktestSettings.timeframe;
        backtestInitialCapitalInput.value = currentBacktestSettings.initialCapital; // This should now be safe
        if(currentBacktestSettings.startDate) backtestStartDateInput.value = currentBacktestSettings.startDate;
        if(currentBacktestSettings.endDate) backtestEndDateInput.value = currentBacktestSettings.endDate;
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
        const data = await getSymbolsForExchange(exchange);
        const allSymbols = data.symbols || [];
        const filteredSymbols = allSymbols.filter(s => ['EQ', 'INDEX', 'FUTIDX', 'FUTSTK'].includes(s.instrument) || !s.instrument);
        populateSelect(backtestSymbolSelect, filteredSymbols, 'token', 'trading_symbol', defaultToken || (filteredSymbols.length > 0 ? filteredSymbols[0].token : ''));
        
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
        showModal('Symbol Error', `Could not load symbols for backtest: ${error.data?.detail || error.message}`);
        backtestSymbolSelect.innerHTML = '<option value="">Error loading</option>';
    } finally {
        showLoading(false);
    }
}

function handleBacktestExchangeChange() {
    currentBacktestSettings.exchange = backtestExchangeSelect.value;
    loadBacktestSymbols(currentBacktestSettings.exchange);
}

function updateBacktestStrategyParamsUI() {
    currentBacktestSettings.strategyId = backtestStrategySelect.value;
    // Corrected: Find strategy by 'id'
    const strategyConfig = availableStrategies.find(s => s.id === currentBacktestSettings.strategyId);
    if (strategyConfig && backtestStrategyParamsContainer) {
        const paramsToLoad = currentBacktestSettings.strategyParams && Object.keys(currentBacktestSettings.strategyParams).length > 0 &&
                             currentBacktestSettings.strategyParams.constructor === Object // Ensure it's an object of params, not something else
                           ? currentBacktestSettings.strategyParams
                           : strategyConfig.parameters.reduce((acc, p) => { acc[p.name] = p.default_value; return acc; }, {});
        createStrategyParamsInputs(backtestStrategyParamsContainer, strategyConfig.parameters, paramsToLoad, false); // false for single value inputs
    } else if (backtestStrategyParamsContainer) {
        backtestStrategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Select a strategy.</p>';
    }
}

async function executeBacktest() {
    showLoading(true);
    backtestResultsContainer.classList.add('hidden');

    // ... (parameter collection logic remains the same) ...
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
    if (strategyConfig) {
        currentBacktestSettings.strategyParams = getStrategyParamsValues(strategyConfig.parameters, false);
    } else {
        currentBacktestSettings.strategyParams = {};
        showModal('Error', 'Strategy configuration not found.');
        showLoading(false);
        return;
    }

    const requestBody = {
        strategy_id: currentBacktestSettings.strategyId,
        exchange: currentBacktestSettings.exchange,
        token: currentBacktestSettings.token,
        start_date: currentBacktestSettings.startDate,
        end_date: currentBacktestSettings.endDate,
        timeframe: currentBacktestSettings.timeframe,
        initial_capital: currentBacktestSettings.initialCapital,
        parameters: currentBacktestSettings.strategyParams
    };

    try {
        const results = await runBacktest(requestBody);
        console.log("Backtest Results:", results);

        // MODIFIED CONDITION:
        // Check if the results object exists.
        // Then, determine the source of metrics: results.performance_metrics (if it's an object) or results directly.
        // Display results if metricsSource is truthy and contains keys, or if a key like net_pnl is a number.
        if (results) {
            const metricsSource = results.performance_metrics || results; // Prefer performance_metrics if it exists as an object

            // Ensure metricsSource is an object and has some data to display or specific essential metrics like net_pnl are numbers.
            const hasMeaningfulMetrics = metricsSource && typeof metricsSource === 'object' &&
                                        (Object.keys(metricsSource).length > 0 || typeof metricsSource.net_pnl === 'number');

            if (hasMeaningfulMetrics) {
                displayPerformanceSummary(performanceSummaryContainer, metricsSource);
                populateTradesTable(tradesTableBody, results.trades || []); // Ensure trades is an array

                // Equity Curve
                if (results.equity_curve && results.equity_curve.length > 0) {
                    if (backtestChartEquity) { try {backtestChartEquity.remove();} catch(e){console.warn("Error removing old equity chart",e);} backtestChartEquity = null; }
                    const { chart, series } = initSimpleLineChart('equityCurveChartContainer', '#4caf50');
                    backtestChartEquity = chart; backtestEquitySeries = series;
                    const equityDataForChart = results.equity_curve.map(d => ({ time: d.time, value: d.equity }));
                    setSimpleLineChartData(backtestEquitySeries, equityDataForChart);
                    if(backtestChartEquity) backtestChartEquity.timeScale().fitContent();
                } else {
                    equityCurveChartContainer.innerHTML = '<p class="text-center p-4">No equity data available for this backtest.</p>';
                }

                // Drawdown Curve
                if (results.drawdown_curve && results.drawdown_curve.length > 0) {
                     if (backtestChartDrawdown) { try {backtestChartDrawdown.remove();} catch(e){console.warn("Error removing old drawdown chart", e);} backtestChartDrawdown = null; }
                    const { chart, series } = initSimpleLineChart('drawdownChartContainer', '#f44336');
                    backtestChartDrawdown = chart; backtestDrawdownSeries = series;
                    const drawdownDataForChart = results.drawdown_curve.map(d => ({ time: d.time, value: d.value }));
                    setSimpleLineChartData(backtestDrawdownSeries, drawdownDataForChart);
                     if(backtestChartDrawdown) backtestChartDrawdown.timeScale().fitContent();
                } else {
                    drawdownChartContainer.innerHTML = '<p class="text-center p-4">No drawdown data available for this backtest.</p>';
                }
                backtestResultsContainer.classList.remove('hidden');
            } else {
                // This case means results object was there, but metrics were not in the expected place or were empty/null.
                // Still attempt to show basic info and trades.
                performanceSummaryContainer.innerHTML = `<p class="text-center p-4 text-gray-400">Backtest completed. PnL: ${results.net_pnl !== undefined ? results.net_pnl.toFixed(2) : 'N/A'}. Other performance metrics may be minimal.</p>`;
                if (results.trades && results.trades.length > 0) {
                    populateTradesTable(tradesTableBody, results.trades);
                } else {
                    tradesTableBody.innerHTML = '<tr><td colspan="7" class="text-center py-4">No trades executed in this backtest.</td></tr>';
                }
                 // Optionally show equity/drawdown if they exist even with minimal metrics
                if (results.equity_curve && results.equity_curve.length > 0) { /* ... existing logic ... */ } else { equityCurveChartContainer.innerHTML = '<p class="text-center p-4">No equity data available for this backtest.</p>';}
                if (results.drawdown_curve && results.drawdown_curve.length > 0) { /* ... existing logic ... */ } else { drawdownChartContainer.innerHTML = '<p class="text-center p-4">No drawdown data available for this backtest.</p>';}
                backtestResultsContainer.classList.remove('hidden'); // Show parts of results container
                showModal('Backtest Info', `Backtest completed. Performance metrics might be minimal (e.g., PnL: ${results.net_pnl !== undefined ? results.net_pnl.toFixed(2) : 'N/A'}). ${results.summary_message || results.message || ''}`);
            }
        } else {
            // This case means the results object itself was null/undefined from API, or structure is unexpected
            showModal('Backtest Error', `Backtest completed but returned no parsable results object. ${results?.summary_message || results?.message || ''}`);
        }
    } catch (error) {
        console.error("Error running backtest:", error);
        showModal('Backtest Execution Error', `Failed to run backtest: ${error.data?.detail || error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}