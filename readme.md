# Trading Platform V2

This project is a comprehensive trading platform with a backend built using FastAPI (Python) and a frontend potentially using HTML, CSS, and JavaScript. It allows users to perform backtesting of trading strategies, optimize strategy parameters, and view historical chart data.

## Project Overview

The platform supports various trading functionalities including:
-   **Authentication**: User authentication with Time-based One-Time Passwords (TOTP).
-   **Data Management**: Fetching and caching historical OHLC (Open, High, Low, Close) data for various financial instruments across different exchanges (NSE, BSE, NFO, BFO, MCX, CDS, NCX).
-   **Strategy Engine**: A robust engine to define and run trading strategies. It currently includes a base strategy class and an EMA (Exponential Moving Average) Crossover strategy.
-   **Backtesting**: Allows users to test their trading strategies against historical data to evaluate performance.
-   **Optimization Engine**: Provides tools to optimize strategy parameters by running multiple backtests with varying parameter sets to find the best-performing configurations.
-   **API Endpoints**: Exposes various API endpoints for health checks, fetching symbol lists, retrieving chart data, running backtests, and managing optimization jobs.
-   **Frontend Interface**: A web-based UI for interacting with the platform's features, including viewing charts, configuring backtests, and initiating optimizations.

## Key Features

* **Multi-Exchange Support**: Supports data from NSE, BSE, NFO, BFO, MCX, CDS, and NCX.
* **Historical Data**: Retrieves and manages 1-minute and daily OHLCV data.
* **Strategy Implementation**:
    * Base strategy class for creating custom strategies.
    * EMA Crossover strategy implemented.
* **Performance Metrics**: Calculates various backtesting performance metrics like Net PNL, Sharpe Ratio, Win Rate, Max Drawdown, etc.
* **Parameter Optimization**:
    * Asynchronous optimization tasks.
    * Caching of optimization results.
    * Ability to get the status and results of optimization jobs.
* **Interactive Charting**: Frontend likely uses Lightweight Charts for displaying financial data and trade markers.
* **API for Shoonya**: Integrates with the Shoonya (Finvasia) trading API.

## Project Structure (Simplified)

rading_platform_v2/
├── app/                     # Backend FastAPI application
│   ├── init.py
│   ├── auth.py              # Authentication logic
│   ├── config.py            # Configuration settings
│   ├── data_module.py       # Handles data fetching and caching
│   ├── main.py              # FastAPI app, defines API endpoints
│   ├── models.py            # Pydantic models for data validation
│   ├── numba_kernels.py     # Numba optimized functions for performance
│   ├── optimizer_engine.py  # Handles strategy parameter optimization
│   ├── strategy_engine.py   # Executes backtesting of strategies
│   └── strategies/
│       ├── init.py
│       ├── base_strategy.py
│       └── ema_crossover_strategy.py
├── frontend/                # Frontend files (HTML, JS, CSS)
│   ├── api.js
│   ├── backtesting.js
│   ├── chartSetup.js
│   ├── dashboard.js
│   ├── index.html
│   ├── optimization.js
│   └── ui.js
├── Scripmaster/             # Contains symbol lists for different exchanges
│   ├── BFO_symbols.txt
│   ├── BSE_symbols.txt
│   ├── CDS_symbols.txt
│   ├── MCX_symbols.txt
│   ├── NCX_symbols.txt
│   ├── NFO_symbols.txt
│   └── NSE_symbols.txt
├── test/                    # Test files
│   ├── api_test_output_v6.txt
│   ├── optimization_results_f51a7de7-c71b-4f98-a370-cc0a72366c9e.csv
│   └── test.py
├── api_helper.py            # Helper for Shoonya API interaction
├── run.py                   # Script to run the FastAPI application
└── requirements.txt         

## Setup and Running the Project

1.  **Clone the repository (if applicable).**
2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Environment Variables:**
    Create a `.env` file in the `app/` directory (or project root, depending on `dotenv_path` in `app/config.py`) and populate it with necessary API keys and settings. Based on `app/config.py`, the following might be needed:
    * `SHOONYA_USER`
    * `SHOONYA_PASSWORD`
    * `SHOONYA_TOTP_SECRET`
    * `SHOONYA_VENDOR_CODE`
    * `SHOONYA_API_KEY`
    * `DATABASE_URL` (e.g., `sqlite:///./shoonya_data.db`)
    * `SCRIPMASTER_DIR` (e.g., `../Scripmaster`)
    * `LOG_LEVEL` (e.g., `INFO`)
    * Other settings like `API_RETRIES`, `CACHE_EXPIRY_SECONDS`, etc.

5.  **Run the application:**
    ```bash
    python run.py
    ```
    This will typically start the FastAPI server using Uvicorn. By default, it might be accessible at `http://localhost:8000`.

6.  **Access the Frontend:**
    Open the `frontend/index.html` file in your web browser.

## API Endpoints

The application exposes several API endpoints under `/app`. Key endpoints likely include:

* `/health`: System health check.
* `/symbols/{exchange}`: Get a list of symbols for a given exchange.
* `/chart_data/`: Fetch historical chart data.
* `/strategies/`: List available trading strategies.
* `/backtest/run`: Run a backtest for a strategy.
* `/backtest/results/{job_id}`: Get results of a backtest job.
* `/optimize/start`: Start a parameter optimization job.
* `/optimize/status/{job_id}`: Get the status of an optimization job.
* `/optimize/results/{job_id}`: Get the results of an optimization job.
* `/optimize/cancel/{job_id}`: Cancel an ongoing optimization job.

Refer to `app/main.py` for detailed request and response models for each endpoint.

## Disclaimer

Trading financial instruments involves risk. This platform is for analysis and educational purposes and should not be used for making live trading decisions without understanding the risks involved.