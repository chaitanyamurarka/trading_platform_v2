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
  container.innerHTML = '';

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
 * the Linear Regression Channel beneath it.
 *
 * @param {object} chart    - The Lightweight Chart instance.
 * @param {Array<{time:number, open:number, high:number, low:number, close:number}>} ohlcData
 *        - An array of candle objects, with `time` in UTC epoch seconds.
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

  // Recompute & redraw the regression channel on every update
  addOrUpdateLinearRegressionChannel(chart, ohlcData);
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
  if (!window.chartSeries.linearRegression) return;
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
 * Adds or updates a Linear Regression Channel.  The “fill” between upper & lower
 * regression lines will be a light‐blue band of 15% opacity.  Below the lower line
 * there will be no opaque fill—so the chart’s own dark gray background and grid
 * will show through.
 *
 * Internally, we do this with two overlapping AreaSeries:
 *   1) upperFill:   a 15%‐blue area “from upperLine down to bottom”,
 *   2) lowerCutoff: a fully‐transparent area “from lowerLine down to bottom”,
 *                  which effectively “erases” the portion of upperFill below lowerLine.
 *
 * Then we draw the boundary lines on top.
 *
 * @param {object} chart - The Lightweight Chart instance.
 * @param {Array<{time:number, open:number, high:number, low:number, close:number}>} ohlcData
 *        - The full OHLC array.  We’ll take the last N bars (N=10) for regression.
 */
function addOrUpdateLinearRegressionChannel(chart, ohlcData) {
  // Remove any existing regression‐channel series (in case a previous middle line exists)
  removeLinearRegressionChannel(chart);

  const REGRESSION_LENGTH = 10;
  if (!ohlcData || ohlcData.length < REGRESSION_LENGTH) {
    // Not enough bars to calculate a 10-bar regression.
    return;
  }

  // Take the last N candles
  const windowData = ohlcData.slice(-REGRESSION_LENGTH);
  const L = windowData.length;
  const times  = windowData.map(d => d.time);
  const closes = windowData.map(d => d.close);

  // Compute slope & intercept of linear regression on the close prices
  const xVals  = Array.from({ length: L }, (_, i) => i);
  const sumX   = xVals.reduce((s, v) => s + v, 0);
  const sumY   = closes.reduce((s, v) => s + v, 0);
  const sumXY  = xVals.reduce((s, v, i) => s + v * closes[i], 0);
  const sumXX  = xVals.reduce((s, v) => s + v * v, 0);
  const slope  = (L * sumXY - sumX * sumY) / (L * sumXX - sumX * sumX);
  const intercept = (sumY - slope * sumX) / L;

  // Build the “middle” regression‐line Y values
  const middleYs = xVals.map(x => slope * x + intercept);
  const midStart = middleYs[0];
  const midEnd   = middleYs[L - 1];
  const middleLine = [
    { time: times[0],   value: midStart },
    { time: times[L - 1], value: midEnd   },
  ];

  // Color for the middle line
  const MIDDLE_LINE_COLOR = 'rgb(213, 37, 219)'; // you can change this as needed

  // Common options for the line series (no last‐value dot or price line)
  const commonOpts = {
    lastValueVisible: false,
    priceLineVisible: false,
  };

  //
  // === ONLY STEP: Draw the middle regression line on top ===
  //
  const middleLineSeries = chart.addLineSeries({
    ...commonOpts,
    color:     MIDDLE_LINE_COLOR,
    lineWidth: 2,
  });
  middleLineSeries.setData(middleLine);

  // Keep track of this series so removeLinearRegressionChannel can clear it later
  window.chartSeries.linearRegression.push(middleLineSeries);
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
        priceLineVisible: true,
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
 * Clears everything from the chart: regression channel, candles, and indicators.
 * @param {object} chart - The Lightweight Chart instance.
 */
function clearChart(chart) {
  if (!chart) return;

  // Remove regression channel series
  removeLinearRegressionChannel(chart);

  // Remove the candlestick series
  if (window.candlestickSeries) {
    try { chart.removeSeries(window.candlestickSeries); } catch(e) {}
    window.candlestickSeries = null;
  }

  // Remove any indicator series
  if (window.indicatorSeries) {
    Object.values(window.indicatorSeries).forEach(s => {
      try { chart.removeSeries(s); } catch(e) {}
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
    chart.resize(container.clientWidth, container.clientHeight || 500);
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
 *    • .time  (number of UTC seconds),
 *    • .timestamp (number or ISO‐string),
 *    • and one of .value / .equity / .drawdown.
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
      if (ts > 2e12) {
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
    series.setData([]);
    console.warn('setSimpleLineChartData: no valid points after formatting.');
  }
}
