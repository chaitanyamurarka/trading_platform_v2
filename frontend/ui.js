// frontend/ui.js

/**
 * Populates a select dropdown with options.
 * @param {HTMLSelectElement} selectElement - The select DOM element.
 * @param {Array<object>} options - Array of option objects.
 * @param {string} valueField - The field name for option value.
 * @param {string} textField - The field name for option text.
 * @param {string} [defaultValue=''] - The default selected value.
 * @param {boolean} [clearExisting=true] - Whether to clear existing options.
 */
function populateSelect(selectElement, options, valueField, textField, defaultValue = '', clearExisting = true) {
    if (!selectElement) {
        console.error("Select element not found for populating.");
        return;
    }
    if (clearExisting) {
        selectElement.innerHTML = ''; // Clear existing options
    }

    options.forEach(optionData => {
        const option = document.createElement('option');
        option.value = optionData[valueField];
        option.textContent = optionData[textField];
        if (defaultValue && String(option.value) === String(defaultValue)) { // Ensure type consistency for comparison
            option.selected = true;
        }
        selectElement.appendChild(option);
    });
}

/**
 * Creates and populates strategy parameter input fields.
 * @param {HTMLElement} container - The container element for parameters.
 * @param {Array<object>} paramsConfig - Array of parameter configurations from strategy info.
 * @param {object} [currentValues={}] - Current values for these parameters.
 * @param {boolean} [isRangeInputs=false] - If true, creates min/max/step inputs for optimization.
 */
function createStrategyParamsInputs(container, paramsConfig, currentValues = {}, isRangeInputs = false) {
    if (!container) {
        console.error("[ui.js:createStrategyParamsInputs] Strategy parameters container not found.");
        return;
    }
    container.innerHTML = ''; // Clear existing params

    if (!paramsConfig || !Array.isArray(paramsConfig)) {
        console.error("[ui.js:createStrategyParamsInputs] paramsConfig is invalid or not an array.");
        container.innerHTML = '<p class="text-red-500">Error: Invalid parameter configuration.</p>';
        return;
    }

    paramsConfig.forEach(param => {
        if (!param || typeof param.name === 'undefined' || typeof param.type === 'undefined') {
            console.warn("[ui.js:createStrategyParamsInputs] Skipping invalid parameter object:", param);
            return; // Skip this malformed parameter
        }

        const paramDiv = document.createElement('div');
        paramDiv.className = 'mb-3';

        const label = document.createElement('label');
        label.htmlFor = `param-${param.name}${isRangeInputs ? '-min' : ''}`;
        label.className = 'block text-sm font-medium text-gray-300 mb-1';
        label.textContent = `${param.name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())} (${param.type})`;
        paramDiv.appendChild(label);

        if (isRangeInputs) {
            // For optimization: Min, Max, Step
            const rangeGrid = document.createElement('div');
            rangeGrid.className = 'grid grid-cols-3 gap-2 items-center';

            ['min', 'max', 'step'].forEach(suffix => {
                const input = document.createElement('input');
                input.type = param.type === 'boolean' ? 'checkbox' : (param.type === 'integer' || param.type === 'float' ? 'number' : 'text');
                input.id = `param-${param.name}-${suffix}`;
                input.name = `param-${param.name}-${suffix}`;
                input.className = 'input-field w-full text-sm';
                input.placeholder = suffix.charAt(0).toUpperCase() + suffix.slice(1);

                if (param.type === 'float' || (param.type === 'integer' && suffix ==='step')) {
                    input.step = (param.step !== undefined ? param.step : (param.type === 'float' ? '0.01' : '0.1'));
                } else if (param.type === 'integer') {
                     input.step = param.step !== undefined ? param.step : '1';
                }


                if (currentValues[param.name] && currentValues[param.name][suffix] !== undefined) {
                    input.value = currentValues[param.name][suffix];
                } else {
                    if (suffix === 'min' && param.min_value !== null && param.min_value !== undefined) input.value = param.min_value;
                    else if (suffix === 'max' && param.max_value !== null && param.max_value !== undefined) input.value = param.max_value;
                    else if (suffix === 'step' && param.step !== null && param.step !== undefined) input.value = param.step;
                    // Provide a very basic default if specific range defaults are not present
                    else if (suffix === 'min') input.value = param.type === 'integer' ? '1' : '0.1';
                    else if (suffix === 'max') input.value = param.type === 'integer' ? '100' : '10';
                    else if (suffix === 'step') input.value = param.type === 'integer' ? '1' : '0.1';
                }
                rangeGrid.appendChild(input);
            });
            paramDiv.appendChild(rangeGrid);

        } else {
            // For dashboard/backtest: Single value input
            const input = document.createElement('input');
            input.id = `param-${param.name}`; // Ensure this ID is unique and correct
            input.name = param.name;

            if (param.type === 'boolean') {
                input.type = 'checkbox';
                input.className = 'form-checkbox h-5 w-5 text-blue-600 bg-gray-700 border-gray-600 rounded focus:ring-blue-500';
                // Use param.default for boolean, ensuring correct type coercion
                input.checked = currentValues[param.name] !== undefined ? Boolean(currentValues[param.name]) : (param.default !== undefined ? Boolean(param.default) : false);
            } else {
                input.type = (param.type === 'integer' || param.type === 'float') ? 'number' : 'text';
                input.className = 'input-field w-full';
                // Use param.default for other types
                input.value = currentValues[param.name] !== undefined ? currentValues[param.name] : (param.default !== undefined ? param.default : '');

                if (param.type === 'float') {
                    input.step = param.step !== undefined ? param.step : '0.01';
                } else if (param.type === 'integer') {
                    input.step = param.step !== undefined ? param.step : '1';
                }
                if(param.min_value !== null && param.min_value !== undefined) input.min = param.min_value;
                if(param.max_value !== null && param.max_value !== undefined) input.max = param.max_value;
            }
            paramDiv.appendChild(input);
        }
        container.appendChild(paramDiv);
    });
}

/**
 * Collects strategy parameter values from input fields.
 * @param {Array<object>} paramsConfig - Array of parameter configurations.
 * @param {boolean} [isRangeInputs=false] - Whether inputs are for ranges (optimization).
 * @returns {object} - Object with parameter names and their values.
 */
function getStrategyParamsValues(paramsConfig, isRangeInputs = false) {
    const values = {};
    if (!paramsConfig || !Array.isArray(paramsConfig)) {
        console.error("[ui.js:getStrategyParamsValues] paramsConfig is invalid.");
        return values;
    }

    paramsConfig.forEach(param => {
        if (!param || typeof param.name === 'undefined' || typeof param.type === 'undefined') {
            console.warn("[ui.js:getStrategyParamsValues] Skipping invalid parameter object in config:", param);
            return;
        }
        if (isRangeInputs) {
            const minEl = document.getElementById(`param-${param.name}-min`);
            const maxEl = document.getElementById(`param-${param.name}-max`);
            const stepEl = document.getElementById(`param-${param.name}-step`);

            if (!minEl || !maxEl || !stepEl) {
                console.warn(`[ui.js:getStrategyParamsValues] Range input elements not found for param: ${param.name}`);
                values[param.name] = { min: undefined, max: undefined, step: undefined }; // Indicate missing inputs
                return;
            }

            let minVal, maxVal, stepVal;

            if (param.type === 'integer' || param.type === 'int') {
                minVal = minEl.value !== '' ? parseInt(minEl.value) : undefined;
                maxVal = maxEl.value !== '' ? parseInt(maxEl.value) : undefined;
                stepVal = stepEl.value !== '' ? parseInt(stepEl.value) : undefined;
            } else if (param.type === 'float') {
                minVal = minEl.value !== '' ? parseFloat(minEl.value) : undefined;
                maxVal = maxEl.value !== '' ? parseFloat(maxEl.value) : undefined;
                stepVal = stepEl.value !== '' ? parseFloat(stepEl.value) : undefined;
            } else {
                minVal = minEl.value;
                maxVal = maxEl.value;
                stepVal = stepEl.value;
            }
            values[param.name] = { min: minVal, max: maxVal, step: stepVal };
        } else {
            const inputEl = document.getElementById(`param-${param.name}`);
            if (inputEl) {
                if (param.type === 'boolean') {
                    values[param.name] = inputEl.checked;
                } else if (param.type === 'integer') {
                    values[param.name] = inputEl.value !== '' ? parseInt(inputEl.value) : undefined; // Return undefined if empty to distinguish from 0
                } else if (param.type === 'float') {
                    values[param.name] = inputEl.value !== '' ? parseFloat(inputEl.value) : undefined;
                } else {
                    values[param.name] = inputEl.value;
                }
            } else {
                // This warning will now show if an input field is missing
                console.warn(`[ui.js:getStrategyParamsValues] Input element not found for param: param-${param.name}`);
                values[param.name] = undefined; // Indicate missing input
            }
        }
    });
    console.log("[ui.js:getStrategyParamsValues] Collected values:", JSON.parse(JSON.stringify(values)));
    return values;
}

// ... (rest of ui.js: displayPerformanceSummary, populateTradesTable, etc.)
// Make sure to keep the other functions from your ui.js file if they are not shown here.
// The provided snippet only included up to getStrategyParamsValues.
// The following are stubs for other functions if they are not fully in the snippet.

function displayPerformanceSummary(container, metrics) {
    if (!container) return;
    // ... (implementation)
    // console.log("[ui.js] displayPerformanceSummary called with metrics:", metrics);
}

function populateTradesTable(tbodyElement, trades) {
    if (!tbodyElement) return;
    // ... (implementation)
    // console.log("[ui.js] populateTradesTable called with trades:", trades ? trades.length : 0);
}

function populateOptimizationResultsTable(tbodyElement, theadElement, results, paramKeys, metricKeys) {
    if (!tbodyElement || !theadElement) return;
    // ... (implementation)
}

function formatDateForAPI(dateInput) {
    if (!dateInput) return null;
    const date = new Date(dateInput);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function setDefaultDateInputs(startDateInput, endDateInput, defaultDaysAgo = 90) {
    if (endDateInput) {
        endDateInput.value = formatDateForAPI(new Date());
    }
    if (startDateInput) {
        const startDate = new Date();
        startDate.setDate(startDate.getDate() - defaultDaysAgo);
        startDateInput.value = formatDateForAPI(startDate);
    }
}

function updateOptimizationProgressUI(statusData) {
    // ... (implementation)
}

function displayBestOptimizationResult(container, bestResult, metricOptimized) {
    if (!container) return;
    // ... (implementation)
}

/**
 * Displays performance metrics in a grid.
 * @param {HTMLElement} container - The container element.
 * @param {object} metrics - The performance metrics object.
 */
function displayPerformanceSummary(container, metrics) {
    if (!container) return;
    container.innerHTML = ''; // Clear previous
    for (const key in metrics) {
        if (Object.hasOwnProperty.call(metrics, key)) {
            const value = metrics[key];
            const itemDiv = document.createElement('div');
            itemDiv.className = 'p-3 bg-gray-700 rounded shadow';

            const keySpan = document.createElement('span');
            keySpan.className = 'font-semibold text-gray-300 block capitalize';
            keySpan.textContent = key.replace(/_/g, ' ');

            const valueSpan = document.createElement('span');
            valueSpan.className = 'text-lg text-white block';
            valueSpan.textContent = (typeof value === 'number' && !Number.isInteger(value)) ? value.toFixed(2) : value;
            if (value === null || value === undefined) valueSpan.textContent = 'N/A';


            itemDiv.appendChild(keySpan);
            itemDiv.appendChild(valueSpan);
            container.appendChild(itemDiv);
        }
    }
}

/**
 * Populates a table with trade data.
 * @param {HTMLTableSectionElement} tbodyElement - The tbody element of the table.
 * @param {Array<object>} trades - Array of trade objects.
 */
function populateTradesTable(tbodyElement, trades) {
    if (!tbodyElement) return;
    tbodyElement.innerHTML = ''; // Clear previous
    if (!trades || trades.length === 0) {
        tbodyElement.innerHTML = '<tr><td colspan="7" class="text-center py-4">No trades to display.</td></tr>';
        return;
    }
    trades.forEach(trade => {
        const row = tbodyElement.insertRow();
        row.className = 'table-row hover:bg-gray-600';
        row.insertCell().textContent = trade.entry_time ? new Date(trade.entry_time).toLocaleString() : 'N/A';
        row.insertCell().textContent = trade.trade_type || 'N/A';
        const entryPriceCell = row.insertCell();
        entryPriceCell.textContent = typeof trade.entry_price === 'number' ? trade.entry_price.toFixed(2) : 'N/A';
        entryPriceCell.className = 'text-right';
        row.insertCell().textContent = trade.exit_time ? new Date(trade.exit_time).toLocaleString() : 'N/A';
        const exitPriceCell = row.insertCell();
        exitPriceCell.textContent = typeof trade.exit_price === 'number' ? trade.exit_price.toFixed(2) : 'N/A';
        exitPriceCell.className = 'text-right';
        const pnlCell = row.insertCell();
        pnlCell.textContent = typeof trade.pnl === 'number' ? trade.pnl.toFixed(2) : 'N/A';
        pnlCell.className = `text-right ${trade.pnl > 0 ? 'text-green-400' : (trade.pnl < 0 ? 'text-red-400' : '')}`;
        row.insertCell().textContent = trade.reason_for_exit || 'N/A';
    });
}

/**
 * Populates the optimization results table.
 * @param {HTMLTableSectionElement} tbodyElement - The tbody element for results.
 * @param {HTMLTableSectionElement} theadElement - The thead element for headers.
 * @param {Array<object>} results - Array of optimization result entries.
 * @param {Array<string>} paramKeys - Ordered list of parameter keys for columns.
 * @param {Array<string>} metricKeys - Ordered list of metric keys for columns.
 */
function populateOptimizationResultsTable(tbodyElement, theadElement, results, paramKeys, metricKeys) {
    if (!tbodyElement || !theadElement) return;
    tbodyElement.innerHTML = '';
    theadElement.innerHTML = '';

    if (!results || results.length === 0) {
        tbodyElement.innerHTML = '<tr><td colspan="100%" class="text-center py-4">No optimization results to display.</td></tr>';
        return;
    }

    // Create headers
    const headerRow = theadElement.insertRow();
    paramKeys.forEach(key => {
        const th = document.createElement('th');
        th.className = 'px-4 py-2 text-left text-xs font-medium text-gray-300 uppercase tracking-wider';
        th.textContent = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        headerRow.appendChild(th);
    });
    metricKeys.forEach(key => {
        const th = document.createElement('th');
        th.className = 'px-4 py-2 text-left text-xs font-medium text-gray-300 uppercase tracking-wider';
        th.textContent = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        headerRow.appendChild(th);
    });
    const errorTh = document.createElement('th');
    errorTh.className = 'px-4 py-2 text-left text-xs font-medium text-gray-300 uppercase tracking-wider';
    errorTh.textContent = 'Error';
    headerRow.appendChild(errorTh);


    // Create rows
    results.forEach(result => {
        const row = tbodyElement.insertRow();
        row.className = 'table-row hover:bg-gray-600';
        paramKeys.forEach(key => {
            const cell = row.insertCell();
            cell.textContent = result.parameters[key] !== undefined ? result.parameters[key] : 'N/A';
        });
        metricKeys.forEach(key => {
            const cell = row.insertCell();
            const value = result.performance_metrics ? result.performance_metrics[key] : undefined;
            cell.textContent = (typeof value === 'number' && !Number.isInteger(value)) ? value.toFixed(2) : (value !== undefined ? value : 'N/A');
            if (key === 'net_pnl' && typeof value === 'number') {
                cell.className = value > 0 ? 'text-green-400' : (value < 0 ? 'text-red-400' : '');
            }
        });
        row.insertCell().textContent = result.error_message || '';
    });
}

/**
 * Formats a date object or string into YYYY-MM-DD.
 * @param {Date|string} dateInput - The date to format.
 * @returns {string} - Formatted date string.
 */
function formatDateForAPI(dateInput) {
    if (!dateInput) return null;
    const date = new Date(dateInput);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

/**
 * Sets default start and end dates for input fields.
 * E.g., end date to today, start date to 90 days ago.
 * @param {HTMLInputElement} startDateInput - The start date input element.
 * @param {HTMLInputElement} endDateInput - The end date input element.
 * @param {number} defaultDaysAgo - Number of days ago for the start date.
 */
function setDefaultDateInputs(startDateInput, endDateInput, defaultDaysAgo = 90) {
    if (endDateInput) {
        endDateInput.value = formatDateForAPI(new Date());
    }
    if (startDateInput) {
        const startDate = new Date();
        startDate.setDate(startDate.getDate() - defaultDaysAgo);
        startDateInput.value = formatDateForAPI(startDate);
    }
}

/**
 * Updates the optimization progress bar and status text.
 * @param {object} statusData - The status object from the API.
 */
function updateOptimizationProgressUI(statusData) {
    const jobIdEl = document.getElementById('optimizationJobId');
    const statusEl = document.getElementById('optimizationStatus');
    const progressBarEl = document.getElementById('optimizationProgressBar');
    const messageEl = document.getElementById('optimizationMessage');
    const statusContainer = document.getElementById('optimizationStatusContainer');

    if (!jobIdEl || !statusEl || !progressBarEl || !messageEl || !statusContainer) return;

    statusContainer.classList.remove('hidden');
    jobIdEl.textContent = `Job ID: ${statusData.job_id || 'N/A'}`;
    statusEl.textContent = `Status: ${statusData.status || 'N/A'}`;
    progressBarEl.style.width = `${statusData.progress_percentage || 0}%`;
    progressBarEl.textContent = `${Math.round(statusData.progress_percentage || 0)}%`;
    messageEl.textContent = statusData.message || '';

    const cancelButton = document.getElementById('cancelOptimizationButton');
    if (cancelButton) {
        if (statusData.status === 'RUNNING' || statusData.status === 'QUEUED') {
            cancelButton.classList.remove('hidden');
        } else {
            cancelButton.classList.add('hidden');
        }
    }
}

/**
 * Displays the best optimization result summary.
 * @param {HTMLElement} container - The container to display the summary.
 * @param {object|null} bestResult - The best result entry, or null.
 * @param {string} metricOptimized - The metric that was optimized.
 */
function displayBestOptimizationResult(container, bestResult, metricOptimized) {
    if (!container) return;
    container.innerHTML = '';
    if (!bestResult) {
        container.textContent = 'No best result found (e.g., all runs failed or no valid results).';
        return;
    }

    let summaryHTML = `<h4 class="text-md font-semibold text-white mb-2">Best Result (Optimized for ${metricOptimized.replace(/_/g, ' ')})</h4>`;
    summaryHTML += '<div class="text-xs space-y-1">';
    summaryHTML += '<strong>Parameters:</strong><ul class="list-disc list-inside ml-2">';
    for (const param in bestResult.parameters) {
        summaryHTML += `<li>${param.replace(/_/g, ' ')}: ${bestResult.parameters[param]}</li>`;
    }
    summaryHTML += '</ul>';
    summaryHTML += '<strong class="mt-2 block">Performance:</strong><ul class="list-disc list-inside ml-2">';
    for (const metric in bestResult.performance_metrics) {
        let value = bestResult.performance_metrics[metric];
        value = (typeof value === 'number' && !Number.isInteger(value)) ? value.toFixed(2) : value;
        summaryHTML += `<li>${metric.replace(/_/g, ' ')}: ${value}</li>`;
    }
    summaryHTML += '</ul></div>';
    container.innerHTML = summaryHTML;
}
