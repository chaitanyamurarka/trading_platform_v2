// chartSetup.js

/**
 * Calculates the standard deviation of an array of numbers.
 * @param {number[]} arr - Array of numbers.
 * @returns {number} Standard deviation.
 */
function standardDeviation(arr) {
    const n = arr.length;
    if (n === 0) return 0;
    const mean = arr.reduce((a, b) => a + b, 0) / n;
    const variance = arr.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / n;
    return Math.sqrt(variance);
}

/**
 * Calculates and plots a linear regression channel with filled areas.
 * @param {object} chart - The chart instance.
 * @param {Array} ohlcData - The OHLC data array.
 * @param {number} period - Number of recent candles for regression (e.g., 10).
 * @param {string} sourceField - Field in ohlcData to use for source (e.g., 'close').
 * @param {number} upperMultiplier - Multiplier for std deviation for upper channel.
 * @param {number} lowerMultiplier - Multiplier for std deviation for lower channel.
 * @param {string} upperFillColor - RGBA color for the upper fill.
 * @param {string} lowerFillColor - RGBA color for the lower fill.
 * @param {string} centralLineColor - Color of the central regression line.
 * @param {string} upperLineColor - Color of the upper channel line.
 * @param {string} lowerLineColor - Color of the lower channel line.
 * @param {number} lineWidth - Line width for channel lines.
 */
function addLinearRegressionChannel(
    chart,
    ohlcData,
    period = 10,
    sourceField = 'close',
    upperMultiplier = 2.0, // Matches default from PineScript example
    lowerMultiplier = 2.0, // Matches default from PineScript example
    upperFillColor = 'rgba(0, 120, 255, 0.15)', // Blueish, semi-transparent
    lowerFillColor = 'rgba(0, 120, 255, 0.15)',   // Reddish, semi-transparent
    centralLineColor = '#FFA500', // Orange
    upperLineColor = '#42A5F5',   // Lighter Blue
    lowerLineColor = '#EF5350',   // Lighter Red
    lineWidth = 1
) {
    if (!chart || !ohlcData || ohlcData.length < period) {
        console.warn("Linear Regression Channel: Not enough data or chart not available.");
        return;
    }

    // --- 1. Clean up previous channel series ---
    if (window.regressionChannelGroup) {
        window.regressionChannelGroup.forEach(series => {
            try { chart.removeSeries(series); } catch (e) { /* ignore */ }
        });
    }
    window.regressionChannelGroup = [];

    // --- 2. Prepare data ---
    const recentData = ohlcData.slice(-period);
    const sourceValues = recentData.map(d => d[sourceField]);
    const xValues = recentData.map((_, i) => i); // Index 0 to period-1

    // --- 3. Calculate Linear Regression for the central line ---
    let sumX = 0, sumY = 0, sumXY = 0, sumXX = 0;
    const n = xValues.length;

    for (let i = 0; i < n; i++) {
        sumX += xValues[i];
        sumY += sourceValues[i];
        sumXY += xValues[i] * sourceValues[i];
        sumXX += xValues[i] * xValues[i];
    }

    const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
    const intercept = (sumY - slope * sumX) / n;

    // Central line points
    const centralStartPrice = intercept; // At x = 0 (first point in recentData)
    const centralEndPrice = slope * (n - 1) + intercept; // At x = n-1 (last point in recentData)

    const startTime = recentData[0].time;
    const endTime = recentData[n - 1].time;

    const centralLineData = [
        { time: startTime, value: centralStartPrice },
        { time: endTime, value: centralEndPrice }
    ];

    // --- 4. Calculate Standard Deviation and Channel Offsets ---
    const stdDev = standardDeviation(sourceValues);
    const upperDeviation = stdDev * upperMultiplier;
    const lowerDeviation = stdDev * lowerMultiplier;

    // Upper channel line points
    const upperChannelData = [
        { time: startTime, value: centralStartPrice + upperDeviation },
        { time: endTime, value: centralEndPrice + upperDeviation }
    ];

    // Lower channel line points
    const lowerChannelData = [
        { time: startTime, value: centralStartPrice - lowerDeviation },
        { time: endTime, value: centralEndPrice - lowerDeviation }
    ];

    // --- 5. Add Series (Fills first, then lines for visibility) ---
    // Chart background color needed for "erasing" parts of fills
    // Assuming your chart background is '#111827' as per initChart
    const chartBackgroundColor = chart.options().layout.backgroundColor || '#111827';

    // Helper to create area series for fills
    const createArea = (data, color, baseValueType) => {
        const series = chart.addAreaSeries({
            lineColor: 'transparent', // No border line for the fill itself
            topColor: color,
            bottomColor: color, // Solid fill
            lineWidth: 0,
            lastValueVisible: false,
            priceLineVisible: false,
            // baseValue: baseValueType ? { type: baseValueType, price: 0 } : undefined
        });
        series.setData(data);
        window.regressionChannelGroup.push(series);
        return series;
    };
    
    // Order of adding is important for layering effect:
    // Fill between Upper and Central
    createArea(upperChannelData, upperFillColor);
    createArea(centralLineData, chartBackgroundColor); // This "cuts" the fill above

    // Fill between Central and Lower
    createArea(centralLineData, lowerFillColor);
    createArea(lowerChannelData, chartBackgroundColor); // This "cuts" the fill above

    // Add the actual lines on top
    const centralSeries = chart.addLineSeries({
        color: centralLineColor, lineWidth: lineWidth, lastValueVisible: false, priceLineVisible: false,
    });
    centralSeries.setData(centralLineData);
    window.regressionChannelGroup.push(centralSeries);

    const upperSeries = chart.addLineSeries({
        color: upperLineColor, lineWidth: lineWidth, lastValueVisible: false, priceLineVisible: false,
    });
    upperSeries.setData(upperChannelData);
    window.regressionChannelGroup.push(upperSeries);

    const lowerSeries = chart.addLineSeries({
        color: lowerLineColor, lineWidth: lineWidth, lastValueVisible: false, priceLineVisible: false,
    });
    lowerSeries.setData(lowerChannelData);
    window.regressionChannelGroup.push(lowerSeries);
}

/**
 * Calculates and plots a linear regression line for the last N candles.
 * @param {object} chart - The chart instance.
 * @param {Array} ohlcData - The OHLC data array.
 * @param {number} period - The number of recent candles to use for regression (e.g., 10).
 * @param {string} [color='#FFA500'] - Color of the regression line.
 * @param {number} [lineWidth=2] - Line width of the regression line.
 */
function addLinearRegressionLine(chart, ohlcData, period = 10, color = '#FFA500', lineWidth = 2) {
    if (!chart || !ohlcData || ohlcData.length < period) {
        console.warn("Linear Regression: Not enough data or chart not available.");
        return;
    }

    // Get the last 'period' data points
    const recentData = ohlcData.slice(-period);

    // For simplicity, let's use the closing prices for regression
    // And map time to a simple index (0, 1, 2, ...) for calculation
    const yValues = recentData.map(d => d.close);
    const xValues = recentData.map((_, i) => i);

    // Calculate linear regression (slope 'm' and intercept 'b' for y = mx + b)
    let sumX = 0, sumY = 0, sumXY = 0, sumXX = 0;
    const n = xValues.length;

    for (let i = 0; i < n; i++) {
        sumX += xValues[i];
        sumY += yValues[i];
        sumXY += xValues[i] * yValues[i];
        sumXX += xValues[i] * xValues[i];
    }

    const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
    const intercept = (sumY - slope * sumX) / n;

    // Determine the start and end points for the line on the chart
    // The line will span from the first candle of the 'recentData' to the last one.
    const regressionLineData = [
        { time: recentData[0].time, value: slope * xValues[0] + intercept }, // Start point
        { time: recentData[n - 1].time, value: slope * xValues[n - 1] + intercept } // End point
    ];

    // Remove previous regression line if it exists
    if (window.regressionLineSeries) {
        try { chart.removeSeries(window.regressionLineSeries); } catch (e) { /* ignore */ }
    }

    // Add the new line series for the regression line
    window.regressionLineSeries = chart.addLineSeries({
        color: color,
        lineWidth: lineWidth,
        lastValueVisible: false, // Optional: hide the price label on the price scale
        priceLineVisible: false, // Optional: hide the price line that follows the last value
    });
    window.regressionLineSeries.setData(regressionLineData);
}

/**
 * Initializes the Lightweight Chart with IST localization for time scale.
 * @param {string} containerId - The ID of the HTML element to contain the chart.
 * @returns {object} The chart instance.
 */
function initChart(containerId) {
    const chartContainer = document.getElementById(containerId);
    if (!chartContainer) {
        console.error(`Chart container with ID '${containerId}' not found.`);
        return null;
    }
    chartContainer.innerHTML = ''; 

    const chart = LightweightCharts.createChart(chartContainer, {
        width: chartContainer.clientWidth,
        height: chartContainer.clientHeight || 500, 
        layout: { backgroundColor: '#111827', textColor: '#d1d5db' },
        grid: { vertLines: { color: '#374151' }, horzLines: { color: '#374151' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        priceScale: { borderColor: '#4b5563', autoScale: true },
        timeScale: {
            borderColor: '#4b5563',
            timeVisible: true,
            secondsVisible: false, // Keep false unless you have second-level data and need it
            // rightOffset: 12, // Optional: space at the right end of the chart
        },
    });

    // Define IST time formatter for the time scale
    const istTimeFormatter = (timestampInSeconds) => {
        const date = new Date(timestampInSeconds * 1000); // LWCharts provides UTC seconds
        // Customize format as needed. Example: "HH:mm" for intraday, or date for daily
        // This example shows HH:mm for time component
        return date.toLocaleTimeString('en-IN', {
            timeZone: 'Asia/Kolkata', // Specify Indian Standard Time
            hour: '2-digit',
            minute: '2-digit',
            hour12: false // Use true for AM/PM format if preferred
        });
        // For a more complete date/time string, you could use:
        // return date.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false, year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    };
    
    // Define a tick mark formatter that shows date for day ticks and time for intraday ticks
    const istTickMarkFormatter = (timestampInSeconds, tickType, locale) => {
        const date = new Date(timestampInSeconds * 1000);
        switch (tickType) {
            case LightweightCharts.TickMarkType.Year:
                return date.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', year: 'numeric' });
            case LightweightCharts.TickMarkType.Month:
                return date.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', month: 'short', year: 'numeric' });
            case LightweightCharts.TickMarkType.DayOfMonth:
                 return date.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short' });
            case LightweightCharts.TickMarkType.Time: // Intraday ticks
                return date.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
            case LightweightCharts.TickMarkType.TimeWithSeconds: // If secondsVisible is true
                return date.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
            default: // Fallback, should not happen with known tick types
                return String(timestampInSeconds);
        }
    };


    // Apply localization to the time scale
    chart.applyOptions({
        timeScale: {
            localization: {
                // locale: 'en-IN', // You can set locale for date formatting (e.g., "dd/mm/yyyy" vs "mm/dd/yyyy")
                timeFormatter: istTimeFormatter, // Formats the time displayed on the crosshair and last bar info.
            },
             tickMarkFormatter: istTickMarkFormatter, // Formats the labels on the time scale axis.
        },
    });

    return chart;
}

function addOrUpdateCandlestickSeries(chart, ohlcData) { // ohlcData.time is UTC epoch seconds
    if (!chart) return null;
    if (window.candlestickSeries) {
        try { chart.removeSeries(window.candlestickSeries); } catch (e) { /* Warn or ignore */ }
    }
    window.candlestickSeries = chart.addCandlestickSeries({
        upColor: '#22c55e', downColor: '#ef4444',
        borderDownColor: '#ef4444', borderUpColor: '#22c55e',
        wickDownColor: '#ef4444', wickUpColor: '#22c55e',
    });
    window.candlestickSeries.setData(ohlcData);

    // --- REPLACE OLD REGRESSION CALL WITH THIS ---
    if (ohlcData && ohlcData.length > 0) {
        addLinearRegressionChannel(chart, ohlcData, 10, 'close'); // Using 10 periods, close price
                                                                // You can adjust multipliers and colors here or pass them as args
    }
    // --- END OF MODIFIED SECTION ---

    return window.candlestickSeries;
}
function clearChart(chart) {
    if (!chart) return;
    if (window.candlestickSeries) {
        try { chart.removeSeries(window.candlestickSeries); } catch (e) { /* ignore */ }
        window.candlestickSeries = null;
    }
    if (window.indicatorSeries) {
        for (const key in window.indicatorSeries) {
            try { chart.removeSeries(window.indicatorSeries[key]); } catch (e) { /* ignore */ }
        }
        window.indicatorSeries = {};
    }
    // --- ADD/MODIFY THIS ---
    if (window.regressionChannelGroup) {
        window.regressionChannelGroup.forEach(series => {
            try { chart.removeSeries(series); } catch (e) { /* ignore */ }
        });
        window.regressionChannelGroup = []; // Reset the array
    }
    if (window.regressionLineSeries) { // If you still have the old single line series reference
        try { chart.removeSeries(window.regressionLineSeries); } catch(e) { /*ignore*/ }
        window.regressionLineSeries = null;
    }
    // --- END OF ADDED/MODIFIED CODE ---
}
function addOrUpdateIndicatorSeries(chart, indicatorData, indicatorColors = {}) { // indicatorData values are {time: UTC_epoch_seconds, value: ...}
    if (!chart || !indicatorData) return;
    if (window.indicatorSeries) {
        for (const seriesName in window.indicatorSeries) {
            if (window.indicatorSeries[seriesName]) {
                try { chart.removeSeries(window.indicatorSeries[seriesName]); } catch (e) { /* Warn or ignore */ }
            }
        }
    }
    window.indicatorSeries = {};
    Object.keys(indicatorData).forEach(key => {
        const data = indicatorData[key];
        if (data && data.length > 0) {
            const series = chart.addLineSeries({
                color: indicatorColors[key] || getRandomColor(),
                lineWidth: 2,
            });
            series.setData(data); // Timestamps are UTC epoch seconds
            window.indicatorSeries[key] = series;
        }
    });
}

function addTradeMarkers(candlestickSeriesInstance, tradeMarkersData) { // tradeMarkersData.time is UTC epoch seconds
    if (!candlestickSeriesInstance || !tradeMarkersData || tradeMarkersData.length === 0) return;
    const markers = tradeMarkersData.map(marker => ({
        time: marker.time, // UTC epoch seconds
        position: marker.position, color: marker.color, shape: marker.shape, text: marker.text || ''
    }));
    candlestickSeriesInstance.setMarkers(markers);
}

function clearChart(chart) {
    if (!chart) return;
    if (window.candlestickSeries) {
        try { chart.removeSeries(window.candlestickSeries); } catch (e) { /* ignore */ }
        window.candlestickSeries = null;
    }
    if (window.indicatorSeries) {
        for (const key in window.indicatorSeries) {
            try { chart.removeSeries(window.indicatorSeries[key]); } catch (e) { /* ignore */ }
        }
        window.indicatorSeries = {};
    }
}

function fitChartContent(chart) {
    if (chart) chart.timeScale().fitContent();
}

function getRandomColor() {
    const letters = '0123456789ABCDEF';
    let color = '#';
    for (let i = 0; i < 6; i++) color += letters[Math.floor(Math.random() * 16)];
    return color;
}

function resizeChart(chart, containerId) {
    const chartContainer = document.getElementById(containerId);
    if (chart && chartContainer) {
        chart.resize(chartContainer.clientWidth, chartContainer.clientHeight || 500);
    }
}

// --- Functions for Equity/Drawdown Charts ---
function initSimpleLineChart(containerId, lineColor = '#2962FF') {
    const container = document.getElementById(containerId);
    if (!container) {
        console.error(`Container ${containerId} not found for simple line chart.`);
        return { chart: null, series: null };
    }
    container.innerHTML = '';

    const chart = LightweightCharts.createChart(container, {
        width: container.clientWidth, height: container.clientHeight || 300,
        layout: { backgroundColor: '#1f2937', textColor: '#d1d5db' },
        grid: { vertLines: { color: '#374151' }, horzLines: { color: '#374151' } },
        timeScale: { borderColor: '#4b5563', timeVisible: true, secondsVisible: false },
        priceScale: { borderColor: '#4b5563' }
    });

    // Apply IST localization to equity/drawdown charts as well
    const istTimeFormatter = (timestampInSeconds) => { /* ... same as in initChart ... */ 
        const date = new Date(timestampInSeconds * 1000);
        return date.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
    };
     const istTickMarkFormatter = (timestampInSeconds, tickType, locale) => { /* ... same as in initChart ... */
        const date = new Date(timestampInSeconds * 1000);
        // Simplified for equity curve (often daily or by trade time)
        if (tickType === LightweightCharts.TickMarkType.DayOfMonth || tickType === LightweightCharts.TickMarkType.Time ) {
             return date.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short' }) + " " +
                    date.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false});
        }
        return date.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', month: 'short', year: 'numeric' });
    };


    chart.applyOptions({
        timeScale: {
            localization: { timeFormatter: istTimeFormatter },
            tickMarkFormatter: istTickMarkFormatter
        }
    });

    const series = chart.addLineSeries({ color: lineColor, lineWidth: 2 });
    return { chart, series };
}

function setSimpleLineChartData(series, data) { // data elements are {time: UTC_epoch_seconds, value: ...} or {timestamp: "ISO_UTC_string", ...}
    if (series && data) {
        const formattedData = data.map(d => {
            let timestamp; // Should be UTC epoch seconds
            if (typeof d.time === 'number') { // Backend sends UTC epoch seconds directly
                timestamp = d.time;
            } else if (typeof d.timestamp === 'number') { // Alternative key from backend
                 timestamp = d.timestamp;
            } else if (typeof d.timestamp === 'string') { // Backend might send ISO string (e.g. from Pydantic datetime)
                const dateObj = new Date(d.timestamp); // new Date() on ISO string with Z or offset is UTC
                if (!isNaN(dateObj.getTime())) {
                    timestamp = Math.floor(dateObj.getTime() / 1000);
                } else {
                    console.warn("setSimpleLineChartData: Could not parse timestamp string:", d.timestamp);
                    return null; // Skip this data point
                }
            } else {
                 console.warn("setSimpleLineChartData: Invalid time/timestamp format:", d);
                 return null; // Skip
            }
            // Ensure ms are converted to s if necessary for timestamps
            if (timestamp > 2000000000000) timestamp = Math.floor(timestamp / 1000);

            const valueKey = d.equity !== undefined ? 'equity' : (d.drawdown !== undefined ? 'drawdown' : 'value');
            return { time: timestamp, value: d[valueKey] };
        }).filter(d => d !== null && d.time !== undefined && d.value !== undefined); // Filter out nulls or malformed
        
        if(formattedData.length > 0) {
            series.setData(formattedData);
        } else {
            series.setData([]); // Clear if no valid data
            console.warn("setSimpleLineChartData: No valid data points after formatting.");
        }
    }
}