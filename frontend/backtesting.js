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
            }
        }
        // Corrected: Use 'id' as valueKey for strategies
        populateSelect(backtestStrategySelect, availableStrategies, 'id', 'name', currentBacktestSettings.strategyId);

        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        populateSelect(backtestExchangeSelect, exchanges, 'id', 'name', currentBacktestSettings.exchange);

        await loadBacktestSymbols(currentBacktestSettings.exchange, currentBacktestSettings.token);
        updateBacktestStrategyParamsUI(); 

        backtestTimeframeSelect.value = currentBacktestSettings.timeframe;
        backtestInitialCapitalInput.value = currentBacktestSettings.initialCapital;
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

    currentBacktestSettings.exchange = backtestExchangeSelect.value;
    currentBacktestSettings.token = backtestSymbolSelect.value;
    // Simplified symbol lookup
    const selectedSymbolText = backtestSymbolSelect.options[backtestSymbolSelect.selectedIndex]?.text;
    currentBacktestSettings.symbol = selectedSymbolText || currentBacktestSettings.token; // Use text or fallback to token

    currentBacktestSettings.timeframe = backtestTimeframeSelect.value;
    currentBacktestSettings.strategyId = backtestStrategySelect.value;
    currentBacktestSettings.initialCapital = parseFloat(backtestInitialCapitalInput.value);
    currentBacktestSettings.startDate = backtestStartDateInput.value;
    currentBacktestSettings.endDate = backtestEndDateInput.value;

    // Corrected: Find strategy by 'id'
    const strategyConfig = availableStrategies.find(s => s.id === currentBacktestSettings.strategyId);
    if (strategyConfig) {
        currentBacktestSettings.strategyParams = getStrategyParamsValues(strategyConfig.parameters, false); // false for single value inputs
    } else {
        currentBacktestSettings.strategyParams = {}; // Clear if no valid strategy
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

        if (results && results.performance_metrics) {
            displayPerformanceSummary(performanceSummaryContainer, results.performance_metrics);
            populateTradesTable(tradesTableBody, results.trades); // Assumes trades have datetime strings or parsable timestamps

            // Equity Curve (expects results.equity_curve with {time: UTC_timestamp, equity: value})
            if (results.equity_curve && results.equity_curve.length > 0) {
                if (backtestChartEquity) { try {backtestChartEquity.remove();} catch(e){console.warn("Error removing old equity chart",e);} backtestChartEquity = null; } 
                const { chart, series } = initSimpleLineChart('equityCurveChartContainer', '#4caf50'); // initSimpleLineChart now handles IST
                backtestChartEquity = chart; backtestEquitySeries = series;
                // Data for setSimpleLineChartData should be [{time: UTC_timestamp, equity: X}] or [{timestamp: ISO_UTC_string, equity: X}]
                const equityDataForChart = results.equity_curve.map(d => ({ time: d.time, value: d.equity }));
                setSimpleLineChartData(backtestEquitySeries, equityDataForChart);
                if(backtestChartEquity) backtestChartEquity.timeScale().fitContent();
            } else {
                equityCurveChartContainer.innerHTML = '<p class="text-center p-4">No equity data available.</p>';
            }

            // Drawdown Curve (expects results.drawdown_curve with {time: UTC_timestamp, value: X})
            if (results.drawdown_curve && results.drawdown_curve.length > 0) {
                 if (backtestChartDrawdown) { try {backtestChartDrawdown.remove();} catch(e){console.warn("Error removing old drawdown chart", e);} backtestChartDrawdown = null; }
                const { chart, series } = initSimpleLineChart('drawdownChartContainer', '#f44336'); // initSimpleLineChart now handles IST
                backtestChartDrawdown = chart; backtestDrawdownSeries = series;
                // Data for setSimpleLineChartData should be [{time: UTC_timestamp, value: X}]
                const drawdownDataForChart = results.drawdown_curve.map(d => ({ time: d.time, value: d.value })); // Backend sends 'value' for drawdown
                setSimpleLineChartData(backtestDrawdownSeries, drawdownDataForChart);
                 if(backtestChartDrawdown) backtestChartDrawdown.timeScale().fitContent();
            } else {
                drawdownChartContainer.innerHTML = '<p class="text-center p-4">No drawdown data available.</p>';
            }
            backtestResultsContainer.classList.remove('hidden');
        } else {
            showModal('Backtest Error', `Backtest completed but returned no valid results. ${results.summary_message || results.message || ''}`);
        }
    } catch (error) {
        console.error("Error running backtest:", error);
        showModal('Backtest Execution Error', `Failed to run backtest: ${error.data?.detail || error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}