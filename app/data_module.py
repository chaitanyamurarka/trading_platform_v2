# app/data_module.py
import pandas as pd
import os
import sqlite3
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timedelta, time as dt_time
from typing import List, Dict, Optional, Union, TYPE_CHECKING, Any # Added TYPE_CHECKING and Any

# Conditional import for ShoonyaApiPy for type hinting
if TYPE_CHECKING:
    from api_helper import ShoonyaApiPy
else:
    # At runtime, ShoonyaApiPy might not be strictly needed as a distinct name
    # if get_shoonya_api_client() returns the correctly typed object and
    # no isinstance(obj, ShoonyaApiPy) checks are performed directly with this name.
    # We use 'Any' as a general placeholder if the import fails at runtime,
    # primarily to satisfy type hint resolution if it were to occur then.
    try:
        from api_helper import ShoonyaApiPy # Attempt runtime import if it's used beyond type hints
    except ImportError:
        ShoonyaApiPy = Any # Fallback for runtime if api_helper or ShoonyaApiPy isn't found


from .config import settings, logger # Correctly import shared logger
from .auth import get_shoonya_api_client
from . import models

# Thread pool for background database operations
# Adjust max_workers based on your application's needs and server capabilities
background_executor = ThreadPoolExecutor(max_workers=settings.API_RETRIES + 1)


# --- Scripmaster Loading ---
# SCRIPMASTER_DIR is now taken from settings
_scripmaster_data: Dict[str, pd.DataFrame] = {} # Cache for loaded scripmaster data

def load_scripmaster(exchange: str) -> pd.DataFrame:
    """
    Loads the scripmaster file for a given exchange from the configured SCRIPMASTER_DIR.
    Example: exchange="NSE" will look for "NSE_symbols.txt" or "NSE.csv"
    """
    global _scripmaster_data
    exchange_upper = exchange.upper()
    if exchange_upper in _scripmaster_data:
        return _scripmaster_data[exchange_upper]

    possible_filenames = [
        f"{exchange_upper}_symbols.txt",
        f"{exchange_upper}.txt",
        f"{exchange_upper}_symbols.csv",
        f"{exchange_upper}.csv"
    ]
    
    filepath = None
    for fname in possible_filenames:
        # settings.SCRIPMASTER_DIR is a Path object
        potential_path = settings.SCRIPMASTER_DIR / fname
        if potential_path.exists():
            filepath = potential_path
            break
    
    if not filepath:
        logger.error(f"Scripmaster file not found for exchange: {exchange} in {settings.SCRIPMASTER_DIR}") #
        raise FileNotFoundError(f"Scripmaster file not found for exchange: {exchange} in {settings.SCRIPMASTER_DIR}")

    try:
        df = pd.read_csv(filepath, low_memory=False) #
        if 'Token' not in df.columns or 'Symbol' not in df.columns: #
            raise ValueError("Scripmaster CSV must contain 'Token' and 'Symbol' columns")
        df['Token'] = df['Token'].astype(str) #
        _scripmaster_data[exchange_upper] = df #
        logger.info(f"Scripmaster loaded for {exchange_upper} from {filepath} with {len(df)} entries.") #
        return df
    except Exception as e:
        logger.error(f"Error loading scripmaster for {exchange}: {e}", exc_info=True) #
        raise

async def get_available_symbols(exchange: str) -> models.AvailableSymbolsResponse:
    """Lists available symbols for a given exchange from the scripmaster."""
    try:
        df = load_scripmaster(exchange) #
        symbols_info = []
        for _, row in df.iterrows(): #
            instrument_val = row.get('Instrument')
            instrument_str = str(instrument_val) if pd.notna(instrument_val) and instrument_val != '' else None
            trading_symbol_val = row.get('TradingSymbol', row.get('Symbol'))
            trading_symbol_str = str(trading_symbol_val) if pd.notna(trading_symbol_val) and trading_symbol_val != '' else None

            symbols_info.append(models.TokenInfo(
                exchange=row.get('Exchange', exchange.upper()),
                token=str(row['Token']),
                symbol=str(row['Symbol']) if pd.notna(row['Symbol']) else 'N/A',
                trading_symbol=trading_symbol_str,
                instrument=instrument_str
            )) #
        
        return models.AvailableSymbolsResponse(
            exchange=exchange.upper(),
            symbols=symbols_info,
            count=len(symbols_info)
        ) #
    except FileNotFoundError: #
        logger.error(f"Scripmaster file not found for exchange: {exchange} in get_available_symbols") #
        raise #
    except Exception as e:
        logger.error(f"Error getting available symbols for {exchange}: {e}", exc_info=True) #
        raise #

# --- Database Helper Functions ---
def _get_db_connection():
    """Establishes a connection to the SQLite database using path from settings."""
    conn = sqlite3.connect(settings.DATABASE_PATH, check_same_thread=False, timeout=10) #
    return conn

def _init_db():
    """Initializes the database and creates the ohlc_data table if it doesn't exist."""
    try:
        with _get_db_connection() as conn: #
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ohlc_data (
                    exchange TEXT NOT NULL,
                    token TEXT NOT NULL,
                    timestamp INTEGER NOT NULL, -- Unix timestamp (seconds) for 1-min intervals, UTC
                    time_iso TEXT NOT NULL,    -- ISO format string of the timestamp for easier debugging / readability
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER,
                    oi INTEGER,
                    PRIMARY KEY (exchange, token, timestamp)
                )
            ''') #
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_ohlc_data_exchange_token_timestamp 
                ON ohlc_data (exchange, token, timestamp);
            ''') #
            conn.commit() #
            logger.info(f"Database initialized/verified at {settings.DATABASE_PATH}") #
    except sqlite3.Error as e:
        logger.error(f"SQLite error during DB initialization: {e}", exc_info=True) #
        raise # Critical error if DB can't be initialized #

_init_db() # Initialize DB when module is loaded #

def _ohlc_datapoint_to_db_tuple(dp: models.OHLCDataPoint, exchange: str, token: str) -> tuple:
    """Converts an OHLCDataPoint model to a tuple for DB insertion."""
    return (
        exchange.upper(),
        token,
        int(dp.time.timestamp()), 
        dp.time.isoformat(), 
        dp.open,
        dp.high,
        dp.low,
        dp.close,
        dp.volume,
        dp.oi
    ) #

def _db_row_to_ohlc_datapoint(row: tuple) -> models.OHLCDataPoint:
    """Converts a database row tuple back to an OHLCDataPoint model."""
    return models.OHLCDataPoint(
        time=datetime.fromtimestamp(row[2]), # Creates naive datetime from UTC timestamp #
        open=row[4], #
        high=row[5], #
        low=row[6], #
        close=row[7], #
        volume=row[8], #
        oi=row[9] #
    )

# --- Shoonya API Time Formatting and Parsing ---
def _format_shoonya_time(dt_obj: Union[date, datetime]) -> str:
    """Formats date/datetime to Shoonya API's expected time string (epoch seconds)."""
    if isinstance(dt_obj, datetime): #
        dt_with_time = dt_obj #
    else: 
        dt_with_time = datetime.combine(dt_obj, dt_time.min) #
    return str(int(dt_with_time.timestamp())) #

def _parse_shoonya_ohlc(data: List[Dict[str, str]], interval_str: str) -> List[models.OHLCDataPoint]:
    """
    Parses Shoonya's string-based OHLC data into structured OHLCDataPoint.
    The `interval_str` is Shoonya's interval string (e.g., "1", "D") to help parse time.
    """
    parsed_data = []
    # is_daily_interval = interval_str.upper() == 'D' or interval_str == "240" # Or other daily codes #

    for item in data: #
        try:
            dt_object = None
            time_str = item.get('time') #
            ssboe_str = item.get('ssboe') #

            if time_str: #
                try:
                    dt_object = pd.to_datetime(time_str, dayfirst=True).to_pydatetime()
                    # or, for more explicit parsing if the format is fixed:
                    # dt_object = pd.to_datetime(time_str, format="%d-%m-%Y %H:%M:%S").to_pydatetime()
                except Exception as e_parse:
                    logger.warning(f"Could not parse 'time' string: '{time_str}' (Error: {e_parse}). Item: {item}. Trying 'ssboe'.") #
            
            if dt_object is None and ssboe_str: #
                try:
                    dt_object = datetime.fromtimestamp(int(ssboe_str)) #
                except ValueError:
                    logger.warning(f"Could not parse 'ssboe' string: {ssboe_str} for item: {item}.") #
                    continue #

            if dt_object is None: #
                logger.warning(f"Timestamp could not be determined for Shoonya data item: {item}") #
                continue #

            ohlc_point = models.OHLCDataPoint(
                time=dt_object, #
                open=float(item.get('into', item.get('op', 0.0))), #
                high=float(item.get('inth', item.get('hp', 0.0))), #
                low=float(item.get('intl', item.get('lp', 0.0))), #
                close=float(item.get('intc', item.get('cp', 0.0))), #
                volume=int(float(item.get('v', item.get('vol', 0)))) if item.get('v') or item.get('vol') else None, #
                oi=int(float(item.get('oi', 0))) if item.get('oi') else None, #
            )
            parsed_data.append(ohlc_point) #
        except (ValueError, KeyError, TypeError) as e: #
            logger.warning(f"Skipping malformed Shoonya data point: {item}. Error: {e}", exc_info=True) #
            continue #
    return sorted(parsed_data, key=lambda x: x.time) #


# --- Data Fetching, Storing, and Resampling Logic ---

async def _store_data_to_db_background(
    exchange: str,
    token: str,
    data_points: List[models.OHLCDataPoint]
):
    """Stores historical data points to SQLite in a background thread."""
    if not data_points: #
        return

    loop = asyncio.get_running_loop() #

    def db_operation():
        try:
            with _get_db_connection() as conn: #
                cursor = conn.cursor()
                records_to_insert = [
                    _ohlc_datapoint_to_db_tuple(dp, exchange, token) for dp in data_points
                ] #
                cursor.executemany('''
                    INSERT OR IGNORE INTO ohlc_data 
                    (exchange, token, timestamp, time_iso, open, high, low, close, volume, oi)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', records_to_insert) #
                conn.commit() #
                logger.info(f"BG DB Store: Stored/Ignored {len(records_to_insert)} 1-min records for {exchange}:{token}.") #
        except sqlite3.Error as e:
            logger.error(f"BG DB Store: SQLite error for {exchange}:{token}: {e}", exc_info=True) #
        except Exception as e: # Catch other potential errors #
            logger.error(f"BG DB Store: General error for {exchange}:{token}: {e}", exc_info=True) #

    await loop.run_in_executor(background_executor, db_operation) #
    logger.debug(f"BG DB Store: Task submitted for {len(data_points)} points for {exchange}:{token}.") #


async def _get_historical_data_from_db(
    exchange: str,
    token: str,
    start_datetime_utc: datetime, 
    end_datetime_utc: datetime   
) -> List[models.OHLCDataPoint]:
    """Fetches 1-minute historical data from SQLite for the given UTC datetime range."""
    db_data_points = []
    try:
        start_ts_utc = int(start_datetime_utc.timestamp()) #
        end_ts_utc = int(end_datetime_utc.timestamp()) #

        with _get_db_connection() as conn: #
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM ohlc_data
                WHERE exchange = ? AND token = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
            ''', (exchange.upper(), token, start_ts_utc, end_ts_utc)) #
            
            rows = cursor.fetchall() #
            for row in rows: #
                db_data_points.append(_db_row_to_ohlc_datapoint(row)) #
        
        logger.info(f"DB Read: Fetched {len(db_data_points)} 1-min records for {exchange}:{token} "
                    f"from {start_datetime_utc.isoformat()} to {end_datetime_utc.isoformat()} (UTC).") #
    except sqlite3.Error as e:
        logger.error(f"DB Read: SQLite error for {exchange}:{token}: {e}", exc_info=True) #
    except Exception as e:
        logger.error(f"DB Read: General error for {exchange}:{token}: {e}", exc_info=True) #
    return db_data_points #

async def _fetch_1min_data_from_api(
    api: ShoonyaApiPy, # Type hint using the conditionally imported ShoonyaApiPy
    exchange: str,
    token: str,
    start_datetime_api: datetime, 
    end_datetime_api: datetime   
) -> List[models.OHLCDataPoint]:
    """Fetches 1-minute historical data from Shoonya API."""
    logger.info(f"API Fetch (1-min): Requesting for {exchange}:{token} "
                f"from {start_datetime_api.isoformat()} to {end_datetime_api.isoformat()} (API time).") #

    api_start_time_str = _format_shoonya_time(start_datetime_api) #
    api_end_time_str = _format_shoonya_time(end_datetime_api) #
    
    api_interval = "1" # Shoonya's code for 1 minute data #
    # ohlc_data_points = [] # Not needed due to direct return

    for attempt in range(settings.API_RETRIES): #
        try:
            response = api.get_time_price_series(
                exchange=exchange.upper(),
                token=token,
                starttime=api_start_time_str,
                endtime=api_end_time_str,
                interval=api_interval
            ) #
            
            if response and isinstance(response, list): #
                logger.info(f"API Fetch (1-min): Received {len(response)} data points for {exchange}:{token}.") #
                parsed_points = _parse_shoonya_ohlc(response, api_interval) #
                return parsed_points #
            elif response and isinstance(response, dict) and response.get('stat') == 'Not_Ok': #
                emsg = response.get('emsg', 'Unknown API error') #
                logger.error(f"API Fetch (1-min): Error for {exchange}:{token}: {emsg}") #
                if "no_data" in emsg.lower(): # More robust check for "no data" #
                    return []  #
                if attempt < settings.API_RETRIES - 1: #
                    await asyncio.sleep(settings.API_RETRY_DELAY * (2**attempt)) #
                else:
                    return [] # Failed after retries #
            else: # Unexpected response format #
                logger.warning(f"API Fetch (1-min): Unexpected response for {exchange}:{token}: {response}") #
                if attempt < settings.API_RETRIES - 1: #
                    await asyncio.sleep(settings.API_RETRY_DELAY * (2**attempt)) #
                else:
                    return [] #
        except Exception as e:
            logger.error(f"API Fetch (1-min): Exception for {exchange}:{token}: {e}", exc_info=True) #
            if attempt < settings.API_RETRIES - 1: #
                await asyncio.sleep(settings.API_RETRY_DELAY * (2**attempt)) #
            else:
                return [] # Return empty on final retry exception #
    return [] #


def _resample_ohlc_data(
    one_min_data_points: List[models.OHLCDataPoint],
    target_interval_str: str 
) -> List[models.OHLCDataPoint]:
    """Resamples 1-minute OHLC data to a higher timeframe using Pandas."""
    if not one_min_data_points: #
        return []
    
    rule = target_interval_str.upper() #
    if rule.isdigit(): #
        rule += 'T' # Assume minutes #
    elif rule == 'D': #
        pass 
    elif rule.endswith('H'): #
        pass
    
    if rule == '1T': # Already 1-minute #
        return one_min_data_points #

    try:
        df = pd.DataFrame([item.model_dump() for item in one_min_data_points]) #
        if df.empty: #
            return [] #
            
        df['time'] = pd.to_datetime(df['time']) # Ensure datetime objects #
        df.set_index('time', inplace=True) #

        resampled_df = df.resample(rule).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
            'oi': 'last' 
        }).dropna(subset=['open']) # Remove intervals that don't have any data #

        resampled_data = []
        for timestamp, row_data in resampled_df.iterrows(): #
            resampled_data.append(models.OHLCDataPoint(
                time=timestamp.to_pydatetime(), # Pandas timestamp to python datetime #
                open=row_data['open'], #
                high=row_data['high'], #
                low=row_data['low'], #
                close=row_data['close'], #
                volume=int(row_data['volume']) if pd.notna(row_data['volume']) else None, #
                oi=int(row_data['oi']) if pd.notna(row_data['oi']) else None, #
            ))
        logger.info(f"Resample: {len(one_min_data_points)} (1-min) -> {len(resampled_data)} ({rule}) for interval '{target_interval_str}'.") #
        return resampled_data #
    except Exception as e:
        logger.error(f"Resample: Error resampling to {target_interval_str} (rule: {rule}): {e}", exc_info=True) #
        return one_min_data_points # Fallback to 1-min on error, or handle differently #


async def get_historical_data_orchestrator(
    exchange: str,
    token: str,
    req_start_date: date,       
    req_end_date: date,         
    req_interval: str           
) -> List[models.OHLCDataPoint]:
    """
    Orchestrates fetching historical data.
    """
    api_client: ShoonyaApiPy = get_shoonya_api_client() # Type hint using the conditionally imported ShoonyaApiPy #

    db_start_dt_utc = datetime.combine(req_start_date, dt_time.min) #
    db_end_dt_utc = datetime.combine(req_end_date, dt_time(23, 59, 59)) #

    api_req_start_dt = datetime.combine(req_start_date, dt_time.min) #
    api_req_end_dt = datetime.combine(req_end_date, dt_time(23,59,59)) #


    logger.info(f"Data Orchestrator: {exchange}:{token} for {req_start_date} to {req_end_date}, interval '{req_interval}'.") #
    logger.debug(f"DB query range (UTC naive): {db_start_dt_utc.isoformat()} to {db_end_dt_utc.isoformat()}") #
    
    db_1min_data = await _get_historical_data_from_db(exchange, token, db_start_dt_utc, db_end_dt_utc) #
    
    all_1min_data = list(db_1min_data) #
    
    fetch_from_api = True #
    api_fetch_start_range = api_req_start_dt  #
    api_fetch_end_range = api_req_end_dt #

    if db_1min_data: #
        latest_db_time = max(dp.time for dp in all_1min_data if isinstance(dp.time, datetime)) #
        
        if latest_db_time >= db_end_dt_utc - timedelta(minutes=1): #
            logger.info(f"Data Orchestrator: Sufficient 1-min data found in DB until {latest_db_time.isoformat()}. No API fetch needed.") #
            fetch_from_api = False #
        else:
            api_fetch_start_range = latest_db_time + timedelta(minutes=1) #
            api_fetch_start_range = max(api_fetch_start_range, api_req_start_dt) #
            logger.info(f"Data Orchestrator: DB data incomplete (ends {latest_db_time.isoformat()}). "
                        f"Will try API fetch from {api_fetch_start_range.isoformat()}.") #
    else:
        logger.info(f"Data Orchestrator: No 1-min data in DB for range. Full API fetch initiated.") #

    if fetch_from_api and api_fetch_start_range <= api_fetch_end_range: #
        api_1min_data = await _fetch_1min_data_from_api(
            api_client, exchange, token, api_fetch_start_range, api_fetch_end_range
        ) #
        if api_1min_data: #
            asyncio.create_task(
                _store_data_to_db_background(exchange, token, api_1min_data)
            ) #
            
            existing_timestamps = {dp.time for dp in all_1min_data} #
            unique_api_data = [dp for dp in api_1min_data if dp.time not in existing_timestamps] #
            all_1min_data.extend(unique_api_data) #
            all_1min_data.sort(key=lambda x: x.time) # Sort by time #
            logger.info(f"Data Orchestrator: Merged {len(unique_api_data)} new 1-min API points.") #
    
    if not all_1min_data: #
        logger.warning(f"Data Orchestrator: No 1-min data available for {exchange}:{token} after DB and API checks.") #
        return [] #

    final_user_interval_data = []
    if req_interval.lower() in ['1', '1t', '1m']: # Explicit 1-minute request #
        final_user_interval_data = all_1min_data #
    else:
        final_user_interval_data = _resample_ohlc_data(all_1min_data, req_interval) #
        
    filtered_output_data = [
        dp for dp in final_user_interval_data
        if req_start_date <= dp.time.date() <= req_end_date
    ] #

    logger.info(f"Data Orchestrator: Final processed data for {exchange}:{token} ({req_interval}) has {len(filtered_output_data)} points.") #
    return filtered_output_data #


async def fetch_and_store_historical_data(
    request: models.HistoricalDataRequest
) -> models.HistoricalDataResponse:
    """
    Main entry point for fetching historical data.
    Uses the orchestrator to handle DB, API, storage, and resampling.
    """
    try:
        ohlc_data_points = await get_historical_data_orchestrator(
            exchange=request.exchange,
            token=request.token,
            req_start_date=request.start_time, 
            req_end_date=request.end_time,     
            req_interval=request.interval      
        ) #

        message = "Data processed successfully." #
        if not ohlc_data_points: #
            is_old_request = request.end_time < (date.today() - timedelta(days=2)) #
            if is_old_request: #
                message = "No historical data found for the specified older period after checking database and API." #
            else:
                message = "No data found for the given parameters after checking database and API." #
        
        return models.HistoricalDataResponse(
            request_params=request,
            data=ohlc_data_points,
            count=len(ohlc_data_points),
            message=message
        ) #
    except Exception as e:
        logger.error(f"Critical error in fetch_and_store_historical_data for {request.exchange}:{request.token}: {e}", exc_info=True) #
        return models.HistoricalDataResponse(
            request_params=request,
            data=[],
            count=0,
            message=f"An internal server error occurred: {str(e)}"
        ) #