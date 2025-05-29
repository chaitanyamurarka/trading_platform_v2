// backtesting.js

let currentBacktestSettings = {
    exchange: 'NSE', token: '3456', symbol: 'TATAMOTORS', timeframe: '1min',
    strategyId: 'ema_crossover', initialCapital: 100000,
    startDate: '', endDate: '', strategyParams: {}
};

let backtestChartEquity = null;
let backtestEquitySeries = null;

let backtestExchangeSelect, backtestSymbolSelect, backtestTimeframeSelect,
    backtestStrategySelect, backtestInitialCapitalInput, backtestStartDateInput,
    backtestEndDateInput, backtestStrategyParamsContainer, runBacktestButton,
    backtestResultsContainer, performanceSummaryContainer, tradesTableBody,
    equityCurveChartContainer;

function formatTimeForBacktestCharts(timeValue) {
    if (typeof timeValue === 'string') {
        const date = new Date(timeValue);
        return Math.floor(date.getTime() / 1000);
    }
    if (typeof timeValue === 'number') {
        if (timeValue > 2000000000000) {
            return Math.floor(timeValue / 1000);
        }
        return timeValue;
    }
    console.warn("Unexpected time format for chart data:", timeValue);
    return new Date().getTime() / 1000;
}

function displayPerformanceSummary(container, metricsSource) {
    if (!container) {
        console.error("Performance summary container not found");
        return;
    }
    if (!metricsSource || typeof metricsSource !== 'object' || Object.keys(metricsSource).length === 0) {
        container.innerHTML = '<p class="text-center p-4 text-gray-400">No performance metrics available.</p>';
        return;
    }

    let metricsToShow = 0;
    // Title <H2> or <H3> is expected to be in the static HTML. JS only provides the content.
    let summaryHtml = '<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">'; // Multi-column responsive grid

    for (const key in metricsSource) {
        if (Object.hasOwnProperty.call(metricsSource, key)) {
            const value = metricsSource[key];
            const formattedValue = (value === null || value === undefined)
                ? 'N/A'
                : (typeof value === 'number' && !Number.isInteger(value))
                    ? value.toFixed(2)
                    : value;

            if (formattedValue !== 'N/A') {
                const displayName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                summaryHtml += `
                    <div class="bg-gray-700 p-3 rounded-lg shadow">
                        <p class="text-sm text-gray-400">${displayName}</p>
                        <p class="text-lg font-semibold text-white">${formattedValue}</p>
                    </div>
                `;
                metricsToShow++;
            }
        }
    }
    summaryHtml += '</div>';
    
    if (metricsToShow === 0) {
        container.innerHTML = '<p class="text-center p-4 text-gray-400">No performance metrics available to display.</p>';
    } else {
        container.innerHTML = summaryHtml;
    }
}

function populateTradesTable(tableBody, trades) {
    if (!tableBody) {
        console.error("Trades table body not found");
        return;
    }
    tableBody.innerHTML = ''; 

    if (!trades || trades.length === 0) {
        // Colspan updated to 7
        tableBody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-gray-400 border border-gray-600">No trades were executed.</td></tr>';
        return;
    }

    // Updated columns array to include Quantity and match the new HTML header order
    const columns = [
        { key: 'entry_time', header: 'Entry Time' },
        { key: 'trade_type', header: 'Type' },
        { key: 'entry_price', header: 'Entry Price' },
        { key: 'exit_time', header: 'Exit Time' },
        { key: 'exit_price', header: 'Exit Price' },
        { key: 'quantity', header: 'Quantity' }, // Added Quantity
        { key: 'pnl', header: 'PnL' }
    ];

    trades.forEach(trade => {
        const row = tableBody.insertRow();
        columns.forEach(column => {
            const cell = row.insertCell();
            let cellValue = trade[column.key];

            if (column.key === 'entry_time' || column.key === 'exit_time') {
                cellValue = cellValue ? new Date(cellValue).toLocaleString() : 'N/A';
            } else if (column.key === 'quantity') {
                cellValue = (typeof cellValue === 'number') ? cellValue.toFixed(2) : (cellValue || 'N/A'); // Format quantity
            } else if (typeof cellValue === 'number' && (column.key === 'entry_price' || column.key === 'exit_price' || column.key === 'pnl')) {
                cellValue = cellValue.toFixed(2);
            } else if (cellValue === undefined || cellValue === null) {
                cellValue = 'N/A';
            }

            cell.textContent = cellValue;
            cell.className = 'px-4 py-2 text-sm text-gray-300 border border-gray-600'; 
            if (column.key === 'entry_price' || column.key === 'exit_price' || column.key === 'pnl' || column.key === 'quantity') {
                cell.classList.add('text-right'); // Align numerical data to the right
            } else {
                cell.classList.add('text-left');
            }


            if (column.key === 'pnl') {
                const pnlValue = parseFloat(cellValue);
                if (!isNaN(pnlValue)) {
                    if (pnlValue > 0) {
                        cell.classList.add('text-green-400');
                    } else if (pnlValue < 0) {
                        cell.classList.add('text-red-400');
                    }
                }
            }
        });
    });
}

function renderEquityCurveChart(container, equityData) {
    if (!container) {
        console.error("Equity curve chart container not found.");
        return;
    }
    container.innerHTML = ''; 

    if (backtestChartEquity) {
        backtestChartEquity.remove();
        backtestChartEquity = null;
    }

    if (!equityData || equityData.length === 0) {
        container.innerHTML = '<p class="text-center p-4">No equity data available for this backtest.</p>';
        return;
    }

    const chartOptions = (typeof commonChartOptions !== 'undefined') ? commonChartOptions : {
        layout: {
            background: { type: 'solid', color: '#1f2937' }, 
            textColor: '#d1d5db', 
        },
        grid: {
            vertLines: { color: '#374151' }, 
            horzLines: { color: '#374151' },
        },
        timeScale: {
            borderColor: '#4b5563', 
        },
        rightPriceScale: {
            borderColor: '#4b5563',
        },
        autoSize: true,
    };
    
    backtestChartEquity = LightweightCharts.createChart(container, chartOptions);
    backtestEquitySeries = backtestChartEquity.addLineSeries({
        color: '#22c55e', 
        lineWidth: 2,
        title: 'Equity'
    });

    const formattedData = equityData.map(d => ({
        time: formatTimeForBacktestCharts(d.time), 
        value: d.value
    })).sort((a, b) => a.time - b.time); 

    backtestEquitySeries.setData(formattedData);
    backtestChartEquity.timeScale().fitContent();
}

async function initBacktestingPage() {
    console.log("Initializing Backtesting Page...");
    backtestExchangeSelect = document.getElementById('backtestExchangeSelect');
    backtestSymbolSelect = document.getElementById('backtestSymbolSelect');
    backtestTimeframeSelect = document.getElementById('backtestTimeframeSelect');
    backtestStrategySelect = document.getElementById('backtestStrategySelect');
    backtestInitialCapitalInput = document.getElementById('backtestInitialCapital');
    backtestStartDateInput = document.getElementById('backtestStartDate');
    backtestEndDateInput = document.getElementById('backtestEndDate');
    const strategyParamsOuterContainer = document.getElementById('backtestStrategyParamsContainer');
    if (strategyParamsOuterContainer) {
        backtestStrategyParamsContainer = strategyParamsOuterContainer.querySelector('.parameter-grid');
         if (!backtestStrategyParamsContainer) {
            console.warn('[backtesting.js] Could not find .parameter-grid within #backtestStrategyParamsContainer. Creating one.');
            backtestStrategyParamsContainer = document.createElement('div');
            backtestStrategyParamsContainer.className = 'parameter-grid';
            strategyParamsOuterContainer.appendChild(backtestStrategyParamsContainer);
        }
    } else {
        console.error('[backtesting.js] #backtestStrategyParamsContainer not found. Strategy params UI will not work.');
    }

    runBacktestButton = document.getElementById('runBacktestButton');
    backtestResultsContainer = document.getElementById('backtestResultsContainer');
    performanceSummaryContainer = document.getElementById('performanceSummary');
    tradesTableBody = document.getElementById('tradesTableBody');
    equityCurveChartContainer = document.getElementById('equityCurveChartContainer');

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

    if (typeof setDefaultDateInputs === 'function') {
        setDefaultDateInputs(backtestStartDateInput, backtestEndDateInput, 365);
    } else {
        console.warn('[backtesting.js] setDefaultDateInputs function is not defined. Dates will not be defaulted.');
        const today = new Date();
        const pastDate = new Date();
        pastDate.setDate(today.getDate() - 365);
        if(backtestEndDateInput) backtestEndDateInput.valueAsDate = today;
        if(backtestStartDateInput) backtestStartDateInput.valueAsDate = pastDate;
    }
    if(backtestStartDateInput) currentBacktestSettings.startDate = backtestStartDateInput.value;
    if(backtestEndDateInput) currentBacktestSettings.endDate = backtestEndDateInput.value;

    if(runBacktestButton) runBacktestButton.addEventListener('click', executeBacktest);
    if(backtestExchangeSelect) backtestExchangeSelect.addEventListener('change', handleBacktestExchangeChange);
    if(backtestSymbolSelect) backtestSymbolSelect.addEventListener('change', () => { currentBacktestSettings.token = backtestSymbolSelect.value; });
    if(backtestStrategySelect) backtestStrategySelect.addEventListener('change', updateBacktestStrategyParamsUI);

    if (typeof showLoading === 'function') showLoading(true); else console.warn("showLoading not defined");
    try {
        if (typeof availableStrategies === 'undefined') {
            window.availableStrategies = [];
        }

        if (!availableStrategies || availableStrategies.length === 0) {
            if (typeof getAvailableStrategies === 'function') {
                const strategiesData = await getAvailableStrategies();
                if (strategiesData && strategiesData.strategies) {
                    availableStrategies = strategiesData.strategies;
                    if (availableStrategies.length > 0 && !availableStrategies.find(s => s.id === currentBacktestSettings.strategyId)) {
                        currentBacktestSettings.strategyId = availableStrategies[0].id;
                    } else if (availableStrategies.length === 0) {
                        currentBacktestSettings.strategyId = '';
                    }
                }
            } else {
                console.error('[backtesting.js] getAvailableStrategies function is not defined.');
            }
        }
        if (typeof populateSelect === 'function' && backtestStrategySelect) {
            populateSelect(backtestStrategySelect, availableStrategies, 'id', 'name', currentBacktestSettings.strategyId);
        } else {
             if(!backtestStrategySelect) console.error("[backtesting.js] backtestStrategySelect element not found.");
             if(typeof populateSelect !== 'function') console.error("[backtesting.js] populateSelect function not defined.");
        }

        const exchanges = [{ id: 'NSE', name: 'NSE' }, { id: 'BSE', name: 'BSE' }, { id: 'NFO', name: 'NFO' }, { id: 'MCX', name: 'MCX' }];
        if (typeof populateSelect === 'function' && backtestExchangeSelect) {
            populateSelect(backtestExchangeSelect, exchanges, 'id', 'name', currentBacktestSettings.exchange);
        }

        await loadBacktestSymbols(currentBacktestSettings.exchange, currentBacktestSettings.token);
        updateBacktestStrategyParamsUI();

        if(backtestTimeframeSelect) backtestTimeframeSelect.value = currentBacktestSettings.timeframe;
        if(backtestInitialCapitalInput) backtestInitialCapitalInput.value = currentBacktestSettings.initialCapital;
        if(currentBacktestSettings.startDate && backtestStartDateInput) backtestStartDateInput.value = currentBacktestSettings.startDate;
        if(currentBacktestSettings.endDate && backtestEndDateInput) backtestEndDateInput.value = currentBacktestSettings.endDate;

    } catch (error) {
        console.error("Error initializing backtesting page:", error);
        if (typeof showModal === 'function') showModal('Initialization Error', `Failed to initialize backtesting page: ${error.data?.message || error.message}`);
    } finally {
        if (typeof showLoading === 'function') showLoading(false);
    }
}

async function loadBacktestSymbols(exchange, defaultToken = '') {
    if (typeof showLoading === 'function') showLoading(true);
    try {
        if (typeof getSymbolsForExchange === 'function') {
            const data = await getSymbolsForExchange(exchange);
            const allSymbols = data.symbols || [];
            const filteredSymbols = allSymbols.filter(s => ['EQ', 'INDEX', 'FUTIDX', 'FUTSTK'].includes(s.instrument) || !s.instrument);
            
            if (typeof populateSelect === 'function' && backtestSymbolSelect) {
                populateSelect(backtestSymbolSelect, filteredSymbols, 'token', 'trading_symbol', defaultToken || (filteredSymbols.length > 0 ? filteredSymbols[0].token : ''));
            }

            if (backtestSymbolSelect && backtestSymbolSelect.value) {
                currentBacktestSettings.token = backtestSymbolSelect.value;
            } else if (defaultToken) {
                currentBacktestSettings.token = defaultToken;
                if (backtestSymbolSelect && !filteredSymbols.some(s => s.token === defaultToken)) {
                    const selectedSymbolObj = allSymbols.find(s => s.token === defaultToken);
                    if(selectedSymbolObj){
                        const opt = document.createElement('option');
                        opt.value = defaultToken; opt.textContent = selectedSymbolObj.trading_symbol; opt.selected = true;
                        backtestSymbolSelect.appendChild(opt);
                    }
                }
            }
        } else {
            console.error('[backtesting.js] getSymbolsForExchange function is not defined.');
            if(backtestSymbolSelect) backtestSymbolSelect.innerHTML = '<option value="">Symbol loading unavailable</option>';
        }
    } catch (error) {
        console.error(`Error fetching symbols for backtest ${exchange}:`, error);
        if (typeof showModal === 'function') showModal('Symbol Error', `Could not load symbols for backtest: ${error.data?.detail || error.message}`);
        if(backtestSymbolSelect) backtestSymbolSelect.innerHTML = '<option value="">Error loading</option>';
    } finally {
        if (typeof showLoading === 'function') showLoading(false);
    }
}

function handleBacktestExchangeChange() {
    if(backtestExchangeSelect) currentBacktestSettings.exchange = backtestExchangeSelect.value;
    loadBacktestSymbols(currentBacktestSettings.exchange);
}

function updateBacktestStrategyParamsUI() {
    if(backtestStrategySelect) currentBacktestSettings.strategyId = backtestStrategySelect.value;
    const currentAvailableStrategies = (typeof availableStrategies !== 'undefined') ? availableStrategies : [];
    const strategyConfig = currentAvailableStrategies.find(s => s.id === currentBacktestSettings.strategyId);

    if (strategyConfig && backtestStrategyParamsContainer) {
        const paramsToLoad = currentBacktestSettings.strategyParams && Object.keys(currentBacktestSettings.strategyParams).length > 0 &&
                             currentBacktestSettings.strategyParams.constructor === Object
                           ? currentBacktestSettings.strategyParams
                           : (strategyConfig.parameters ? strategyConfig.parameters.reduce((acc, p) => { acc[p.name] = p.default_value; return acc; }, {}) : {});
        
        if (typeof createStrategyParamsInputs === 'function') {
            createStrategyParamsInputs(backtestStrategyParamsContainer, strategyConfig.parameters || [], paramsToLoad, false);
        } else {
            console.error('[backtesting.js] createStrategyParamsInputs function is not defined.');
            backtestStrategyParamsContainer.innerHTML = '<p class="text-sm text-red-400">UI Error: Parameter input function missing.</p>';
        }
    } else if (backtestStrategyParamsContainer) {
        backtestStrategyParamsContainer.innerHTML = '<p class="text-sm text-gray-400">Select a strategy to see its parameters.</p>';
    }
}

async function executeBacktest() {
    if (typeof showLoading === 'function') showLoading(true); else console.warn("showLoading not defined");
    if(backtestResultsContainer) backtestResultsContainer.classList.add('hidden');

    if (equityCurveChartContainer) equityCurveChartContainer.innerHTML = '<p class="text-center p-4">Loading equity curve...</p>';

    currentBacktestSettings.exchange = backtestExchangeSelect?.value || currentBacktestSettings.exchange;
    currentBacktestSettings.token = backtestSymbolSelect?.value || currentBacktestSettings.token;
    const selectedSymbolText = backtestSymbolSelect?.options[backtestSymbolSelect.selectedIndex]?.text;
    currentBacktestSettings.symbol = selectedSymbolText || currentBacktestSettings.token;

    currentBacktestSettings.timeframe = backtestTimeframeSelect?.value || currentBacktestSettings.timeframe;
    currentBacktestSettings.strategyId = backtestStrategySelect?.value || currentBacktestSettings.strategyId;
    currentBacktestSettings.initialCapital = parseFloat(backtestInitialCapitalInput?.value) || currentBacktestSettings.initialCapital;
    currentBacktestSettings.startDate = backtestStartDateInput?.value || currentBacktestSettings.startDate;
    currentBacktestSettings.endDate = backtestEndDateInput?.value || currentBacktestSettings.endDate;

    const currentAvailableStrategies = (typeof availableStrategies !== 'undefined') ? availableStrategies : [];
    const strategyConfig = currentAvailableStrategies.find(s => s.id === currentBacktestSettings.strategyId);

    if (strategyConfig && strategyConfig.parameters) {
        if (typeof getStrategyParamsValues === 'function') {
            currentBacktestSettings.strategyParams = getStrategyParamsValues(strategyConfig.parameters, false);
        } else {
            console.error('[backtesting.js] getStrategyParamsValues function is not defined. Cannot get strategy params.');
            currentBacktestSettings.strategyParams = {};
        }
    } else {
        currentBacktestSettings.strategyParams = {};
        if (!strategyConfig && typeof showModal === 'function' && currentBacktestSettings.strategyId) {
            showModal('Error', 'Strategy configuration not found. Cannot collect parameters.');
            if (typeof showLoading === 'function') showLoading(false);
            return;
        }
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
        if (typeof runBacktest !== 'function') {
            console.error('[backtesting.js] runBacktest (API call function) is not defined.');
            if (typeof showModal === 'function') showModal('API Error', 'The function to run backtests is not available.');
            if (typeof showLoading === 'function') showLoading(false);
            return;
        }
        const results = await runBacktest(requestBody);
        console.log("Backtest Results:", results);

        if (results && results.error_message) {
            if (typeof showModal === 'function') showModal('Backtest Error from API', results.error_message);
            if(backtestResultsContainer) backtestResultsContainer.classList.add('hidden');
            if(performanceSummaryContainer) performanceSummaryContainer.innerHTML = `<p class="text-center p-4 text-red-500">Error: ${results.error_message}</p>`;
            if(tradesTableBody) tradesTableBody.innerHTML = `<tr><td colspan="7" class="text-center py-4 border border-gray-600">Backtest failed.</td></tr>`; // colspan 7
            if(equityCurveChartContainer) equityCurveChartContainer.innerHTML = '<p class="text-center p-4 text-red-500">Equity curve not available due to error.</p>';
            if (typeof showLoading === 'function') showLoading(false);
            return;
        }

        if (results) {
            const metricsSource = results.performance_metrics;
            const hasMeaningfulMetrics = metricsSource && typeof metricsSource === 'object' && 
                                        (Object.keys(metricsSource).length > 0 || typeof metricsSource.net_pnl === 'number');

            if (hasMeaningfulMetrics) {
                displayPerformanceSummary(performanceSummaryContainer, metricsSource);
                populateTradesTable(tradesTableBody, results.trades || []);
                renderEquityCurveChart(equityCurveChartContainer, results.equity_curve);
                if(backtestResultsContainer) backtestResultsContainer.classList.remove('hidden');
            } else if (results && results.summary_message) {
                if(performanceSummaryContainer) performanceSummaryContainer.innerHTML = `<p class="text-center p-4 text-gray-400">${results.summary_message}</p>`;
                if (results.trades && results.trades.length > 0) {
                    populateTradesTable(tradesTableBody, results.trades);
                } else {
                    if(tradesTableBody) tradesTableBody.innerHTML = `<tr><td colspan="7" class="text-center py-4 border border-gray-600">No trades executed.</td></tr>`; // colspan 7
                }
                renderEquityCurveChart(equityCurveChartContainer, results.equity_curve);
                if(backtestResultsContainer) backtestResultsContainer.classList.remove('hidden');
                if (typeof showModal === 'function') showModal('Backtest Info', results.summary_message);
            } else {
                if (typeof showModal === 'function') showModal('Backtest Info', `Backtest completed, but detailed performance metrics are unavailable. ${results.summary_message || ''}`);
                if(performanceSummaryContainer) performanceSummaryContainer.innerHTML = `<p class="text-center p-4 text-gray-400">Backtest completed. Performance metrics might be minimal or unavailable.</p>`;
                if(tradesTableBody) tradesTableBody.innerHTML = `<tr><td colspan="7" class="text-center py-4 border border-gray-600">No trades available.</td></tr>`; // colspan 7
                if(equityCurveChartContainer) equityCurveChartContainer.innerHTML = '<p class="text-center p-4">No equity data.</p>';
            }
        } else {
            if (typeof showModal === 'function') showModal('Backtest Error', `Backtest completed but returned no parsable results object.`);
            if(performanceSummaryContainer) performanceSummaryContainer.innerHTML = `<p class="text-center p-4 text-red-500">Backtest did not return valid results.</p>`;
            if(tradesTableBody) tradesTableBody.innerHTML = `<tr><td colspan="7" class="text-center py-4 border border-gray-600">No results.</td></tr>`; // colspan 7
            if(equityCurveChartContainer) equityCurveChartContainer.innerHTML = '<p class="text-center p-4 text-red-500">No results for equity curve.</p>';
        }
    } catch (error) {
        console.error("Error running backtest:", error);
        if (typeof showModal === 'function') showModal('Backtest Execution Error', `Failed to run backtest: ${error.data?.detail || error.data?.message || error.message}`);
        if(performanceSummaryContainer) performanceSummaryContainer.innerHTML = `<p class="text-center p-4 text-red-500">Backtest execution failed: ${error.data?.detail || error.message}</p>`;
        if(tradesTableBody) tradesTableBody.innerHTML = `<tr><td colspan="7" class="text-center py-4 border border-gray-600">Execution error.</td></tr>`; // colspan 7
        if(equityCurveChartContainer) equityCurveChartContainer.innerHTML = '<p class="text-center p-4 text-red-500">Equity curve error.</p>';
    } finally {
        if (typeof showLoading === 'function') showLoading(false);
    }
}