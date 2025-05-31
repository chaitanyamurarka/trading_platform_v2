// chartSetup.js

/**
 * Initializes a Lightweight Chart with IST-localized time scale.
 * @param {string} containerId - The ID of the container element for the chart.
 * @returns {object|null} The created chart instance, or null on failure.
 */
function initChart(containerId) {
  const container = document.getElementById(containerId);
  if (!container) {
    console.error(`Chart container with ID '${containerId}' not found.`);
    return null;
  }
  container.innerHTML = ''; // Clear previous content

  // Base colors
  const BACKGROUND_COLOR = '#111827';  // dark gray
  const TEXT_COLOR       = '#d1d5db';  // light gray
  const GRID_COLOR       = '#374151';  // slightly lighter gray
  const SCALE_BORDER     = '#4b5563';  // border color for axes

  // Create the chart
  const chart = LightweightCharts.createChart(container, {
    width:  container.clientWidth,
    height: container.clientHeight || 500,
    layout: {
      backgroundColor: BACKGROUND_COLOR,
      textColor:       TEXT_COLOR,
    },
    grid: {
      vertLines: { color: GRID_COLOR },
      horzLines: { color: GRID_COLOR },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    priceScale: {
      borderColor: SCALE_BORDER,
      autoScale:   true,
    },
    timeScale: {
      borderColor: SCALE_BORDER,
      timeVisible: true,
      secondsVisible: false,
    },
  });

  // Store containerId on chart instance for later use (e.g., by table)
  chart.containerId = containerId;

  // IST time formatter (HH:mm, 24-hour)
  const istTimeFormatter = (ts) => {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // IST tick mark formatter (handles Year, Month, Day, Time, TimeWithSeconds)
  const istTickMarkFormatter = (ts, tickType) => {
    const d = new Date(ts * 1000);
    switch (tickType) {
      case LightweightCharts.TickMarkType.Year:
        return d.toLocaleDateString('en-IN', {
          timeZone: 'Asia/Kolkata',
          year: 'numeric',
        });
      case LightweightCharts.TickMarkType.Month:
        return d.toLocaleDateString('en-IN', {
          timeZone: 'Asia/Kolkata',
          month: 'short',
          year: 'numeric',
        });
      case LightweightCharts.TickMarkType.DayOfMonth:
        return d.toLocaleDateString('en-IN', {
          timeZone: 'Asia/Kolkata',
          day: '2-digit',
          month: 'short',
        });
      case LightweightCharts.TickMarkType.Time:
        return d.toLocaleTimeString('en-IN', {
          timeZone: 'Asia/Kolkata',
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
        });
      case LightweightCharts.TickMarkType.TimeWithSeconds:
        return d.toLocaleTimeString('en-IN', {
          timeZone: 'Asia/Kolkata',
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        });
      default:
        return String(ts);
    }
  };

  chart.applyOptions({
    timeScale: {
      localization:      { timeFormatter: istTimeFormatter },
      tickMarkFormatter: istTickMarkFormatter,
    },
  });

  // Expose the background color so the regression‐channel code can “know” it if needed.
  window.chartOptions = {
    layout: { backgroundColor: BACKGROUND_COLOR },
  };

  return chart;
}


/**
 * Adds or updates a Candlestick series on the chart, then redraws
 * the Linear Regression Channels and their info table beneath it.
 *
 * @param {object} chart    - The Lightweight Chart instance.
 * @param {Array<{time:number, open:number, high:number, low:number, close:number}>} ohlcData
 * - An array of candle objects, with `time` in UTC epoch seconds.
 * @returns {object|null} The candlestick series instance, or null on failure.
 */
function addOrUpdateCandlestickSeries(chart, ohlcData) {
  if (!chart) return null;

  // If a previous candlestick series exists, remove it.
  if (window.candlestickSeries) {
    try {
      chart.removeSeries(window.candlestickSeries);
    } catch (e) {
      // ignore
    }
  }

  // Create a new candlestick series with green/red coloring
  const candlestickSeries = chart.addCandlestickSeries({
    upColor:      '#22c55e',
    downColor:    '#ef4444',
    borderUpColor:   '#22c55e',
    borderDownColor: '#ef4444',
    wickUpColor:  '#22c55e',
    wickDownColor:'#ef4444',
  });
  candlestickSeries.setData(ohlcData);
  window.candlestickSeries = candlestickSeries;

  // Recompute & redraw the regression channels and info table on every update
  addOrUpdateMultipleLinearRegressionChannels(chart, ohlcData, chart.containerId);
  return candlestickSeries;
}

// Keep track of all series that belong to the regression‐channel
if (!window.chartSeries) window.chartSeries = {};
window.chartSeries.linearRegression = [];


/**
 * Removes any existing series that were used for the Linear Regression Channel.
 * @param {object} chart - The Lightweight Chart instance.
 */
function removeLinearRegressionChannel(chart) {
  if (!window.chartSeries || !window.chartSeries.linearRegression) return;
  window.chartSeries.linearRegression.forEach(series => {
    try {
      chart.removeSeries(series);
    } catch (e) {
      // ignore
    }
  });
  window.chartSeries.linearRegression = [];
}

/**
 * Calculates Pearson's R correlation coefficient.
 * @param {number[]} xVals - Array of x values.
 * @param {number[]} yVals - Array of y values.
 * @returns {number} Pearson's R.
 */
function calculatePearsonR(xVals, yVals) {
  const n = xVals.length;
  if (n === 0 || yVals.length !== n) return 0;

  const sumX = xVals.reduce((s, v) => s + v, 0);
  const sumY = yVals.reduce((s, v) => s + v, 0);
  const sumXY = xVals.reduce((s, v, i) => s + v * yVals[i], 0);
  const sumXSquare = xVals.reduce((s, v) => s + v * v, 0);
  const sumYSquare = yVals.reduce((s, v) => s + v * v, 0);

  const numerator = n * sumXY - sumX * sumY;
  const denominatorSqrtPart1 = n * sumXSquare - sumX * sumX;
  const denominatorSqrtPart2 = n * sumYSquare - sumY * sumY;

  if (denominatorSqrtPart1 <= 0 || denominatorSqrtPart2 <= 0) {
    return 0; // Handles cases where all x or y values are constant
  }
  const denominator = Math.sqrt(denominatorSqrtPart1 * denominatorSqrtPart2);

  if (denominator === 0) return 0;
  return numerator / denominator;
}


/**
 * Clears the regression information table from the DOM.
 */
function clearRegressionTable() {
  const oldTable = document.getElementById('regressionInfoTable');
  if (oldTable) oldTable.remove();
}

/**
 * Displays a table with information about the regression lines on the chart.
 * @param {Array<object>} tableData - Data for the table rows.
 * @param {string} chartContainerId - The ID of the chart's container element.
 */
function displayRegressionTable(tableData, chartContainerId) {
  const chartContainer = document.getElementById(chartContainerId);
  if (!chartContainer) return;

  clearRegressionTable(); // Remove old table if exists

  const table = document.createElement('table');
  table.id = 'regressionInfoTable';
  table.style.position = 'absolute';
  table.style.top = '10px';
  table.style.right = '10px';
  table.style.backgroundColor = 'rgba(30, 41, 59, 0.85)'; // Dark slate, semi-transparent
  table.style.color = '#e5e7eb'; // Lighter gray text
  table.style.borderCollapse = 'collapse';
  table.style.fontSize = '10px';
  table.style.fontFamily = 'Arial, sans-serif';
  table.style.zIndex = '1000'; // Ensure it's on top
  table.style.border = '1px solid #4b5563'; // Border for the table itself
  table.style.boxShadow = '0 2px 4px rgba(0,0,0,0.2)';


  const thead = table.createTHead();
  const headerRow = thead.insertRow();
  const headers = ['Lookback', 'Color', 'Slope', 'Pearson R'];
  headers.forEach(text => {
    const th = document.createElement('th');
    th.textContent = text;
    th.style.border = '1px solid #4b5563'; // Grid lines color
    th.style.padding = '3px 5px';
    th.style.backgroundColor = 'rgba(55, 65, 81, 0.9)'; // Slightly darker header
    th.style.textAlign = 'center';
    headerRow.appendChild(th);
  });

  const tbody = table.createTBody();
  tableData.forEach(data => {
    const row = tbody.insertRow();
    const cellValues = [
      data.lookback,
      data.color,
      data.slope.toFixed(5), // More precision for slope
      data.pearsonR.toFixed(4)
    ];

    cellValues.forEach((val, index) => {
      const cell = row.insertCell();
      cell.style.border = '1px solid #4b5563';
      cell.style.padding = '3px 5px';
      if (index === 1) { // Color cell
        const colorSwatch = document.createElement('div');
        colorSwatch.style.width = '100%';
        colorSwatch.style.height = '12px';
        colorSwatch.style.backgroundColor = val;
        cell.appendChild(colorSwatch);
        cell.style.minWidth = '40px';
      } else {
        cell.textContent = val;
      }
      cell.style.textAlign = (index === 0 || index === 1) ? 'center' : 'right';
    });
  });
  if (!chartContainer.style.position || chartContainer.style.position === 'static') {
     chartContainer.style.position = 'relative'; // Ensure chart container can position absolute children
  }
  chartContainer.appendChild(table);
}

const LOOKBACK_PERIODS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
const REGRESSION_LINE_COLORS = [
  '#FF6347', '#4682B4', '#32CD32', '#FFD700', '#6A5ACD', // Tomato, SteelBlue, LimeGreen, Gold, SlateBlue
  '#FF4500', '#1E90FF', '#ADFF2F', '#DAA520', '#BA55D3'  // OrangeRed, DodgerBlue, GreenYellow, GoldenRod, MediumOrchid
];


/**
 * Adds or updates multiple Linear Regression Channels and their information table.
 * @param {object} chart - The Lightweight Chart instance.
 * @param {Array<{time:number, open:number, high:number, low:number, close:number}>} ohlcData
 * - The full OHLC array.
 * @param {string} chartContainerId - The ID of the chart's container element.
 */
function addOrUpdateMultipleLinearRegressionChannels(chart, ohlcData, chartContainerId) {
  removeLinearRegressionChannel(chart); // Clear previous lines
  clearRegressionTable(); // Clear previous table

  if (!ohlcData || ohlcData.length === 0) return;

  const tableInfo = []; // To store data for the info table

  const commonOpts = {
    lastValueVisible: false,
    priceLineVisible: false,
    lineWidth: 1.5, // Slightly thinner lines for multiple lines
  };

  for (let i = 0; i < LOOKBACK_PERIODS.length; i++) {
    const REGRESSION_LENGTH = LOOKBACK_PERIODS[i];
    const LINE_COLOR = REGRESSION_LINE_COLORS[i % REGRESSION_LINE_COLORS.length]; // Use modulo for safety

    if (ohlcData.length < REGRESSION_LENGTH) {
      // console.warn(`Not enough bars (${ohlcData.length}) for regression length ${REGRESSION_LENGTH}.`);
      continue;
    }

    const windowData = ohlcData.slice(-REGRESSION_LENGTH);
    const L = windowData.length;
    const times  = windowData.map(d => d.time);
    const closes = windowData.map(d => d.close);

    const xVals  = Array.from({ length: L }, (_, k) => k);
    const sumX   = xVals.reduce((s, v) => s + v, 0);
    const sumY   = closes.reduce((s, v) => s + v, 0);
    const sumXY  = xVals.reduce((s, v, k) => s + v * closes[k], 0);
    const sumXX  = xVals.reduce((s, v) => s + v * v, 0);

    let slope = 0;
    let intercept = L > 0 ? sumY / L : 0; // Default to average if slope cannot be calculated

    if (L * sumXX - sumX * sumX !== 0) { // Avoid division by zero
        slope = (L * sumXY - sumX * sumY) / (L * sumXX - sumX * sumX);
        intercept = (sumY - slope * sumX) / L;
    }


    const middleYs = xVals.map(x => slope * x + intercept);
    const midStart = middleYs[0];
    const midEnd   = middleYs[L - 1];

    // Ensure there are at least two points to draw a line
    if (times.length >= 2 && middleYs.length >=2 && times[0] !== undefined && times[L-1] !== undefined && midStart !== undefined && midEnd !== undefined ) {
        const middleLineData = [
            { time: times[0],   value: midStart },
            { time: times[L - 1], value: midEnd   },
        ];

        const middleLineSeries = chart.addLineSeries({
            ...commonOpts,
            color: LINE_COLOR,
        });
        middleLineSeries.setData(middleLineData);
        window.chartSeries.linearRegression.push(middleLineSeries);

        const pearsonR = calculatePearsonR(xVals, closes);
        tableInfo.push({
            lookback: REGRESSION_LENGTH,
            color: LINE_COLOR,
            slope: slope,
            pearsonR: pearsonR
        });
    } else {
        // console.warn(`Could not generate regression line for lookback ${REGRESSION_LENGTH} due to insufficient distinct time points or data.`);
    }
  }

  if (tableInfo.length > 0 && chartContainerId) {
    displayRegressionTable(tableInfo, chartContainerId);
  }
}


/**
 * Adds or updates indicator lines (e.g., RSI, MACD) on top of the chart.
 * @param {object} chart - The Lightweight Chart instance.
 * @param {object} indicatorData - A map from indicator name ➔ Array of {time, value}.
 * @param {object} [indicatorColors={}] - Optional map { indicatorName: hexColor }.
 */
function addOrUpdateIndicatorSeries(chart, indicatorData, indicatorColors = {}) {
  if (!chart || !indicatorData) return;

  // Remove any old indicator series
  if (!window.indicatorSeries) window.indicatorSeries = {};
  Object.values(window.indicatorSeries).forEach(s => {
    try { chart.removeSeries(s); } catch(e) { /*ignore*/ }
  });
  window.indicatorSeries = {};

  // Add each new indicator
  Object.keys(indicatorData).forEach(key => {
    const data = indicatorData[key];
    if (Array.isArray(data) && data.length > 0) {
      const series = chart.addLineSeries({
        color:            indicatorColors[key] || getRandomColor(),
        lineWidth:        2,
        lastValueVisible: false,
        priceLineVisible: true, // Keeps price line for indicators
      });
      series.setData(data);
      window.indicatorSeries[key] = series;
    }
  });
}


/**
 * Places trade markers (e.g. buy/sell arrows) on the candlestick series.
 * @param {object} candlestickSeriesInstance - The series returned from addCandlestickSeries().
 * @param {Array<{time:number, position:"aboveBar"|"belowBar", color:string, shape:string, text?:string}>} tradeMarkersData
 */
function addTradeMarkers(candlestickSeriesInstance, tradeMarkersData) {
  if (!candlestickSeriesInstance || !Array.isArray(tradeMarkersData) || tradeMarkersData.length === 0) {
    return;
  }
  const markers = tradeMarkersData.map(m => ({
    time:     m.time,
    position: m.position,
    color:    m.color,
    shape:    m.shape,
    text:     m.text || '',
  }));
  candlestickSeriesInstance.setMarkers(markers);
}


/**
 * Clears everything from the chart: regression channel, candles, indicators, and info table.
 * @param {object} chart - The Lightweight Chart instance.
 */
function clearChart(chart) {
  if (!chart) return;

  // Remove regression channel series
  removeLinearRegressionChannel(chart);
  // Clear the regression info table
  clearRegressionTable();


  // Remove the candlestick series
  if (window.candlestickSeries) {
    try { chart.removeSeries(window.candlestickSeries); } catch(e) {/*ignore*/}
    window.candlestickSeries = null;
  }

  // Remove any indicator series
  if (window.indicatorSeries) {
    Object.values(window.indicatorSeries).forEach(s => {
      try { chart.removeSeries(s); } catch(e) {/*ignore*/}
    });
    window.indicatorSeries = {};
  }
}


/**
 * Tells the chart to auto‐zoom so all visible data fits.
 * @param {object} chart - The Lightweight Chart instance.
 */
function fitChartContent(chart) {
  if (chart) chart.timeScale().fitContent();
}


/**
 * Returns a random hex color string (e.g. "#A1B2C3").
 * Useful for assigning default indicator colors.
 * @returns {string}
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
 * Resizes the chart to match its container’s current dimensions.
 * @param {object} chart       - The Lightweight Chart instance.
 * @param {string} containerId - The ID of the container element.
 */
function resizeChart(chart, containerId) {
  const container = document.getElementById(containerId);
  if (chart && container) {
    const newWidth = container.clientWidth;
    const newHeight = container.clientHeight || 500; // Keep fallback height
    if (newWidth > 0 && newHeight > 0) {
        chart.resize(newWidth, newHeight);
    }
  }
}


/**
 * Creates a simple stand‐alone line chart—for example, to plot “equity” or “drawdown.”
 * @param {string} containerId - The ID of the container element.
 * @param {string} lineColor   - The hex color for the line (default "#2962FF").
 * @returns {{ chart: object|null, series: object|null }}
 */
function initSimpleLineChart(containerId, lineColor = '#2962FF') {
  const container = document.getElementById(containerId);
  if (!container) {
    console.error(`Container '${containerId}' not found for simple line chart.`);
    return { chart: null, series: null };
  }
  container.innerHTML = '';

  const BACKGROUND_COLOR = '#1f2937'; // slightly different dark gray
  const TEXT_COLOR       = '#d1d5db';
  const GRID_COLOR       = '#374151';
  const SCALE_BORDER     = '#4b5563';

  const chart = LightweightCharts.createChart(container, {
    width:  container.clientWidth,
    height: container.clientHeight || 300,
    layout: {
      backgroundColor: BACKGROUND_COLOR,
      textColor:       TEXT_COLOR,
    },
    grid: {
      vertLines: { color: GRID_COLOR },
      horzLines: { color: GRID_COLOR },
    },
    priceScale: {
      borderColor: SCALE_BORDER,
    },
    timeScale: {
      borderColor: SCALE_BORDER,
      timeVisible: true,
      secondsVisible: false,
    },
  });

  // Re‐use IST time & tick formatting
  const istTimeFormatter = (ts) => {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
    });
  };
  const istTickMarkFormatter = (ts, tickType) => {
    const d = new Date(ts * 1000);
    if (
      tickType === LightweightCharts.TickMarkType.DayOfMonth ||
      tickType === LightweightCharts.TickMarkType.Time
    ) {
      return (
        d.toLocaleDateString('en-IN', {
          timeZone: 'Asia/Kolkata',
          day: '2-digit',
          month: 'short',
        }) +
        ' ' +
        d.toLocaleTimeString('en-IN', {
          timeZone: 'Asia/Kolkata',
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
        })
      );
    }
    return d.toLocaleDateString('en-IN', {
      timeZone: 'Asia/Kolkata',
      month: 'short',
      year: 'numeric',
    });
  };

  chart.applyOptions({
    timeScale: {
      localization:      { timeFormatter: istTimeFormatter },
      tickMarkFormatter: istTickMarkFormatter,
    },
  });

  const series = chart.addLineSeries({
    color:            lineColor,
    lineWidth:        2,
    lastValueVisible: false,
    priceLineVisible: true,
  });

  return { chart, series };
}


/**
 * Populates a simple line chart (from initSimpleLineChart) with raw data.
 * Accepts objects containing either:
 * • .time  (number of UTC seconds),
 * • .timestamp (number or ISO‐string),
 * • and one of .value / .equity / .drawdown.
 *
 * @param {object} series - The line series returned by initSimpleLineChart().
 * @param {Array<object>} data - Array of raw data points.
 */
function setSimpleLineChartData(series, data) {
  if (!series || !Array.isArray(data)) return;

  const formatted = data
    .map(d => {
      let ts;
      if (typeof d.time === 'number') {
        ts = d.time;
      } else if (typeof d.timestamp === 'number') {
        ts = d.timestamp;
      } else if (typeof d.timestamp === 'string') {
        const dd = new Date(d.timestamp);
        if (!isNaN(dd.getTime())) {
          ts = Math.floor(dd.getTime() / 1000);
        } else {
          console.warn('Invalid timestamp string:', d.timestamp);
          return null;
        }
      } else {
        console.warn('Invalid data object (no time/timestamp):', d);
        return null;
      }
      // If a millisecond‐based timestamp was given, convert to seconds
      if (ts > 2e12) { // A rough check for milliseconds (e.g., > year 2033 in seconds)
        ts = Math.floor(ts / 1000);
      }
      // Prefer .equity, then .drawdown, then .value
      const val =
        d.equity !== undefined
          ? d.equity
          : d.drawdown !== undefined
            ? d.drawdown
            : d.value;
      if (val === undefined) {
        console.warn('No value/equity/drawdown in data point:', d);
        return null;
      }
      return { time: ts, value: val };
    })
    .filter(pt => pt !== null && pt.time !== undefined && pt.value !== undefined);

  if (formatted.length > 0) {
    series.setData(formatted);
  } else {
    series.setData([]); // Clear series if no valid data
    // console.warn('setSimpleLineChartData: no valid points after formatting.');
  }
}