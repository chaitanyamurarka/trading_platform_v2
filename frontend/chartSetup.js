// chartSetup.js

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
    window.candlestickSeries.setData(ohlcData); // Timestamps are UTC epoch seconds
    return window.candlestickSeries;
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