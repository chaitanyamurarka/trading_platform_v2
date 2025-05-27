// chartSetup.js

/**
 * Initializes the Lightweight Chart.
 * @param {string} containerId - The ID of the HTML element to contain the chart.
 * @returns {object} The chart instance.
 */
function initChart(containerId) {
    const chartContainer = document.getElementById(containerId);
    if (!chartContainer) {
        console.error(`Chart container with ID '${containerId}' not found.`);
        return null;
    }
    chartContainer.innerHTML = ''; // Clear previous chart if any

    // Lightweight Charts v4.1.3 specific initialization
    const chart = LightweightCharts.createChart(chartContainer, {
        width: chartContainer.clientWidth,
        height: chartContainer.clientHeight || 500, // Use clientHeight or default
        layout: {
            backgroundColor: '#111827', // Dark background to match theme
            textColor: '#d1d5db',    // Light text color
        },
        grid: {
            vertLines: {
                color: '#374151', // Darker grid lines
            },
            horzLines: {
                color: '#374151',
            },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        priceScale: {
            borderColor: '#4b5563', // Border for price scale
            autoScale: true,
        },
        timeScale: {
            borderColor: '#4b5563', // Border for time scale
            timeVisible: true,
            secondsVisible: false,
            // rightOffset: 12, // Add some space to the right
        },
    });
    return chart;
}

/**
 * Adds or updates the candlestick series on the chart.
 * @param {object} chart - The Lightweight Chart instance.
 * @param {Array<object>} ohlcData - Array of OHLC data points.
 * @returns {object} The candlestick series instance.
 */
function addOrUpdateCandlestickSeries(chart, ohlcData) {
    if (!chart) return null;

    // For v4.1.3, if series exists, we update it. If not, create it.
    // We need a global or passed-in reference to the series if we want to update it.
    // For simplicity here, let's assume 'candlestickSeries' is a global/module-level variable
    // that was assigned during the first call.

    if (window.candlestickSeries) {
        try {
            chart.removeSeries(window.candlestickSeries); // Remove old before adding new for simplicity with setData
        } catch (e) {
            console.warn("Could not remove existing candlestick series, it might have been removed already:", e);
        }
    }

    window.candlestickSeries = chart.addCandlestickSeries({
        upColor: '#22c55e', // Green for up candles
        downColor: '#ef4444', // Red for down candles
        borderDownColor: '#ef4444',
        borderUpColor: '#22c55e',
        wickDownColor: '#ef4444',
        wickUpColor: '#22c55e',
    });
    window.candlestickSeries.setData(ohlcData);
    return window.candlestickSeries;
}

/**
 * Adds or updates line series for indicators.
 * @param {object} chart - The Lightweight Chart instance.
 * @param {object} indicatorData - Object where keys are indicator names and values are arrays of {time, value}.
 * @param {object} indicatorColors - Object mapping indicator names to colors.
 */
function addOrUpdateIndicatorSeries(chart, indicatorData, indicatorColors = {}) {
    if (!chart || !indicatorData) return;

    // Remove previous indicator series before adding new ones
    // Assumes indicatorSeries is a global/module-level object { seriesName: seriesInstance }
    if (window.indicatorSeries) {
        for (const seriesName in window.indicatorSeries) {
            if (window.indicatorSeries[seriesName]) {
                try {
                    chart.removeSeries(window.indicatorSeries[seriesName]);
                } catch (e) {
                    console.warn(`Could not remove existing indicator series ${seriesName}:`, e);
                }
            }
        }
    }
    window.indicatorSeries = {}; // Reset

    Object.keys(indicatorData).forEach(key => {
        const data = indicatorData[key]; // Array of {time, value}
        if (data && data.length > 0) {
            const series = chart.addLineSeries({
                color: indicatorColors[key] || getRandomColor(), // Use provided color or a random one
                lineWidth: 2,
                // priceLineVisible: false, // Hide price line for indicators
                // lastValueVisible: false, // Hide last value label for indicators
            });
            series.setData(data);
            window.indicatorSeries[key] = series;
        }
    });
}

/**
 * Adds trade markers to the candlestick series.
 * @param {object} candlestickSeriesInstance - The candlestick series instance.
 * @param {Array<object>} tradeMarkersData - Array of trade marker objects.
 */
function addTradeMarkers(candlestickSeriesInstance, tradeMarkersData) {
    if (!candlestickSeriesInstance || !tradeMarkersData || tradeMarkersData.length === 0) return;

    // For v4.1.3, markers are set on the series directly.
    // If markers were previously set, calling setData on the series clears them.
    // So, we should apply markers *after* setting candlestick data.
    // Or, if we want to add to existing markers, we'd need to get existing markers and append.
    // For simplicity, this function assumes it's setting all markers for the current dataset.
    const markers = tradeMarkersData.map(marker => ({
        time: marker.time,
        position: marker.position, // 'aboveBar', 'belowBar', 'inBar'
        color: marker.color,
        shape: marker.shape, // 'arrowUp', 'arrowDown', 'circle', 'square'
        text: marker.text || ''
    }));
    candlestickSeriesInstance.setMarkers(markers);
}


/**
 * Clears all series (candlestick, indicators, markers) from the chart.
 * @param {object} chart - The Lightweight Chart instance.
 */
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
    // Markers are attached to candlestick series, so removing it clears them.
}


/**
 * Fits the chart content to view.
 * @param {object} chart - The Lightweight Chart instance.
 */
function fitChartContent(chart) {
    if (chart) {
        chart.timeScale().fitContent();
    }
}

/**
 * Generates a random hex color.
 * @returns {string} Hex color code.
 */
function getRandomColor() {
    const letters = '0123456789ABCDEF';
    let color = '#';
    for (let i = 0; i < 6; i++) {
        color += letters[Math.floor(Math.random() * 16)];
    }
    return color;
}

/**
 * Resizes the chart. Typically called on window resize.
 * @param {object} chart - The Lightweight Chart instance.
 * @param {string} containerId - The ID of the chart container.
 */
function resizeChart(chart, containerId) {
    const chartContainer = document.getElementById(containerId);
    if (chart && chartContainer) {
        chart.resize(chartContainer.clientWidth, chartContainer.clientHeight || 500);
    }
}

// --- Functions for Equity/Drawdown Charts (using Lightweight Charts) ---

/**
 * Initializes a simple line chart for equity or drawdown.
 * @param {string} containerId - The ID of the HTML element for the chart.
 * @param {string} lineColor - Color for the line series.
 * @returns {object} The chart instance and the line series instance.
 */
function initSimpleLineChart(containerId, lineColor = '#2962FF') {
    const container = document.getElementById(containerId);
    if (!container) {
        console.error(`Container ${containerId} not found for simple line chart.`);
        return { chart: null, series: null };
    }
    container.innerHTML = ''; // Clear previous

    const chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight || 300,
        layout: { backgroundColor: '#1f2937', textColor: '#d1d5db' },
        grid: { vertLines: { color: '#374151' }, horzLines: { color: '#374151' } },
        timeScale: { borderColor: '#4b5563', timeVisible: true, secondsVisible: false },
        priceScale: { borderColor: '#4b5563' }
    });

    const series = chart.addLineSeries({
        color: lineColor,
        lineWidth: 2,
    });

    return { chart, series };
}

/**
 * Sets data for a simple line chart (equity/drawdown).
 * @param {object} series - The line series instance.
 * @param {Array<object>} data - Array of {time, value} objects.
 */
function setSimpleLineChartData(series, data) {
    if (series && data) {
        // Ensure time is in a format Lightweight Charts understands (Unix timestamp or 'YYYY-MM-DD')
        const formattedData = data.map(d => ({
            time: (typeof d.timestamp === 'string' && !d.timestamp.includes('-')) ? parseInt(d.timestamp) : (new Date(d.timestamp).getTime() / 1000), // Assuming backend sends ISO string or already unix
            value: d.equity !== undefined ? d.equity : d.drawdown // Adapt based on data key
        }));
        series.setData(formattedData);
    }
}
