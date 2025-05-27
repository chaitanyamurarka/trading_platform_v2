// backtesting.js

// State specific to backtesting page
let currentBacktestSettings = { // Will be pre-filled from dashboard or defaults
    exchange: 'NSE',
    token: '3045', // TATAMOTORS
    symbol: 'TATAMOTORS',
    timeframe: 'day',
    strategyId: 'ema_crossover',
    initialCapital: 100000,
    startDate: '',
    endDate: '',
    strategyParams: {}
};
let backtestChartEquity = null;
let backtestChartDrawdown = null;
let backtestEquitySeries = null;
let backtestDrawdownSeries = null;

// DOM Elements for Backtesting page
let backtestExchangeSelect, backtestSymbolSelect, backtestTimeframeSelect,
    backtestStrategySelect, backtestInitialCapitalInput, backtestStartDateInput,
    backtestEndDateInput, backtestStrategyParamsContainer, runBacktestButton,
    backtestResultsContainer, performanceSummaryContainer, tradesTableBody,
    equityCurveChartContainer, drawdownChartContainer;


/**
 * Initializes the Backtesting page.
 */
async function initBacktestingPage() {
    console.log("Initializing Backtesting Page...");

    // Assign DOM elements
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

    // Set default date inputs (e.g., last year for backtest)
    setDefaultDateInputs(backtestStartDateInput, backtestEndDateInput, 365);
    currentBacktestSettings.startDate = backtestStartDateInput.value;
    currentBacktestSettings.endDate = backtestEndDateInput.value;


    // Event Listeners
    runBacktestButton.addEventListener('click', executeBacktest);
    backtestExchangeSelect.addEventListener('change', handleBacktestExchangeChange);
    backtestSymbolSelect.addEventListener('change', () => { currentBacktestSettings.token = backtestSymbolSelect.value; });
    backtestStrategySelect.addEventListener('change', updateBacktestStrategyParamsUI);


    showLoading(true);
    try {
        // Populate common controls (strategies, exchanges)
        if (!availableStrategies || availableStrategies.length === 0) {
            const strategiesData = await getAvailableStrategies();
            if (strategiesData && strategiesData.strategies) {
                availableStrategies = strategiesData.strategies;
            }
        }
        populateSelect(backtestStrategySelect, availableStrategies, 'strategy_id', 'name', currentBacktestSettings.strategyId);

        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        populateSelect(backtestExchangeSelect, exchanges, 'id', 'name', currentBacktestSettings.exchange);

        await loadBacktestSymbols(currentBacktestSettings.exchange, currentBacktestSettings.token);
        updateBacktestStrategyParamsUI(); // Load params for the default/selected strategy

        // Pre-fill other controls from currentBacktestSettings (which might have come from dashboard)
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
        // Store all symbols for potential lookup, filter for display
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
                    opt.value = defaultToken;
                    opt.textContent = selectedSymbolObj.trading_symbol;
                    opt.selected = true;
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
    const strategyConfig = availableStrategies.find(s => s.strategy_id === currentBacktestSettings.strategyId);
    if (strategyConfig && backtestStrategyParamsContainer) {
        // Use default values from strategy config, or currentBacktestSettings if they exist for this strategy
        const paramsToLoad = currentBacktestSettings.strategyParams && Object.keys(currentBacktestSettings.strategyParams).length > 0
                           ? currentBacktestSettings.strategyParams
                           : strategyConfig.parameters.reduce((acc, p) => { acc[p.name] = p.default_value; return acc; }, {});
        createStrategyParamsInputs(backtestStrategyParamsContainer, strategyConfig.parameters, paramsToLoad, false);
    } else if (backtestStrategyParamsContainer) {
        backtestStrategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Select a strategy.</p>';
    }
}

async function executeBacktest() {
    showLoading(true);
    backtestResultsContainer.classList.add('hidden'); // Hide previous results

    // Collect all parameters
    currentBacktestSettings.exchange = backtestExchangeSelect.value;
    currentBacktestSettings.token = backtestSymbolSelect.value;
    const selectedSymbolObj = availableSymbols.find(s => s.token === currentBacktestSettings.token) || // from dashboard's availableSymbols
                              (typeof getCurrentlyLoadedSymbols === "function" ? getCurrentlyLoadedSymbols().find(s => s.token === currentBacktestSettings.token) : null); // fallback if a global symbol list exists
    currentBacktestSettings.symbol = selectedSymbolObj ? selectedSymbolObj.symbol : currentBacktestSettings.token;

    currentBacktestSettings.timeframe = backtestTimeframeSelect.value;
    currentBacktestSettings.strategyId = backtestStrategySelect.value;
    currentBacktestSettings.initialCapital = parseFloat(backtestInitialCapitalInput.value);
    currentBacktestSettings.startDate = backtestStartDateInput.value;
    currentBacktestSettings.endDate = backtestEndDateInput.value;

    const strategyConfig = availableStrategies.find(s => s.strategy_id === currentBacktestSettings.strategyId);
    if (strategyConfig) {
        currentBacktestSettings.strategyParams = getStrategyParamsValues(strategyConfig.parameters, false);
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
            populateTradesTable(tradesTableBody, results.trades);

            // Equity Curve Chart
            if (results.equity_curve && results.equity_curve.length > 0) {
                if (backtestChartEquity) { backtestChartEquity.remove(); backtestChartEquity = null; } // Remove old chart
                const { chart, series } = initSimpleLineChart('equityCurveChartContainer', '#4caf50');
                backtestChartEquity = chart;
                backtestEquitySeries = series;
                setSimpleLineChartData(backtestEquitySeries, results.equity_curve);
                if(backtestChartEquity) backtestChartEquity.timeScale().fitContent();
            } else {
                equityCurveChartContainer.innerHTML = '<p class="text-center p-4">No equity data available.</p>';
            }


            // Drawdown Curve Chart
            if (results.drawdown_curve && results.drawdown_curve.length > 0) {
                 if (backtestChartDrawdown) { backtestChartDrawdown.remove(); backtestChartDrawdown = null; }
                const { chart, series } = initSimpleLineChart('drawdownChartContainer', '#f44336');
                backtestChartDrawdown = chart;
                backtestDrawdownSeries = series;
                // Drawdown data might need transformation if it's not {time, value}
                // Assuming backend sends drawdown_curve as [{timestamp: "...", drawdown: value}]
                const drawdownDataForChart = results.drawdown_curve.map(d => ({
                    time: d.timestamp, // Ensure this is compatible (unix or YYYY-MM-DD)
                    value: d.drawdown
                }));
                setSimpleLineChartData(backtestDrawdownSeries, drawdownDataForChart);
                 if(backtestChartDrawdown) backtestChartDrawdown.timeScale().fitContent();
            } else {
                drawdownChartContainer.innerHTML = '<p class="text-center p-4">No drawdown data available.</p>';
            }


            backtestResultsContainer.classList.remove('hidden');
        } else {
            showModal('Backtest Error', `Backtest completed but returned no valid results. ${results.summary_message || ''}`);
        }

    } catch (error) {
        console.error("Error running backtest:", error);
        showModal('Backtest Execution Error', `Failed to run backtest: ${error.data?.detail || error.data?.message || error.message}`);
    } finally {
        showLoading(false);
    }
}
