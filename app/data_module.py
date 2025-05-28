# app/data_module.py
import pandas as pd
import os
import sqlite3
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timedelta, time as dt_time, timezone # Added timezone
from typing import List, Dict, Optional, Union, TYPE_CHECKING, Any

from .models import TokenInfo

if TYPE_CHECKING:
    from api_helper import ShoonyaApiPy
else:
    try:
        from api_helper import ShoonyaApiPy
    except ImportError:
        ShoonyaApiPy = Any


from .config import settings, logger
from .auth import get_shoonya_api_client
from . import models

background_executor = ThreadPoolExecutor(max_workers=settings.API_RETRIES + 1)
_scripmaster_data: Dict[str, pd.DataFrame] = {}

def load_scripmaster(exchange: str) -> pd.DataFrame:
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
        potential_path = settings.SCRIPMASTER_DIR / fname
        if potential_path.exists():
            filepath = potential_path
            break
    if not filepath:
        logger.error(f"Scripmaster file not found for exchange: {exchange} in {settings.SCRIPMASTER_DIR}")
        raise FileNotFoundError(f"Scripmaster file not found for exchange: {exchange} in {settings.SCRIPMASTER_DIR}")

    try:
        df = pd.read_csv(filepath, low_memory=False)
        if 'Token' not in df.columns or 'Symbol' not in df.columns:
            raise ValueError("Scripmaster CSV must contain 'Token' and 'Symbol' columns")
        df['Token'] = df['Token'].astype(str)
        _scripmaster_data[exchange_upper] = df
        logger.info(f"Scripmaster loaded for {exchange_upper} from {filepath} with {len(df)} entries.")
        return df
    except Exception as e:
        logger.error(f"Error loading scripmaster for {exchange}: {e}", exc_info=True)
        raise

async def get_available_symbols(exchange: str) -> models.AvailableSymbolsResponse:
    try:
        df = load_scripmaster(exchange)
        symbols_info = []
        for _, row in df.iterrows():
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
            ))
        return models.AvailableSymbolsResponse(
            exchange=exchange.upper(),
            symbols=symbols_info,
            count=len(symbols_info)
        )
    except FileNotFoundError:
        logger.error(f"Scripmaster file not found for exchange: {exchange} in get_available_symbols")
        raise
    except Exception as e:
        logger.error(f"Error getting available symbols for {exchange}: {e}", exc_info=True)
        raise

def _get_db_connection():
    conn = sqlite3.connect(settings.DATABASE_PATH, check_same_thread=False, timeout=10)
    return conn

def _init_db():
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ohlc_data (
                    exchange TEXT NOT NULL,
                    token TEXT NOT NULL,
                    timestamp INTEGER NOT NULL, 
                    time_iso TEXT NOT NULL,    
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER,
                    oi INTEGER,
                    PRIMARY KEY (exchange, token, timestamp)
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_ohlc_data_exchange_token_timestamp 
                ON ohlc_data (exchange, token, timestamp);
            ''')
            conn.commit()
            logger.info(f"Database initialized/verified at {settings.DATABASE_PATH}")
    except sqlite3.Error as e:
        logger.error(f"SQLite error during DB initialization: {e}", exc_info=True)
        raise

_init_db()

def _ohlc_datapoint_to_db_tuple(dp: models.OHLCDataPoint, exchange: str, token: str) -> tuple:
    # dp.time is expected to be UTC-aware datetime
    return (
        exchange.upper(),
        token,
        int(dp.time.timestamp()), # UTC timestamp
        dp.time.isoformat(), 
        dp.open,
        dp.high,
        dp.low,
        dp.close,
        dp.volume,
        dp.oi
    )

def _db_row_to_ohlc_datapoint(row: tuple) -> models.OHLCDataPoint:
    # row[2] is UTC timestamp from DB
    return models.OHLCDataPoint(
        time=datetime.fromtimestamp(row[2], tz=timezone.utc), # Create UTC-aware datetime
        open=row[4],
        high=row[5],
        low=row[6],
        close=row[7],
        volume=row[8],
        oi=row[9]
    )

def _format_shoonya_time(dt_obj: Union[date, datetime]) -> str:
    # dt_obj is expected to be UTC-aware if datetime, or just date
    if isinstance(dt_obj, datetime):
        dt_with_time = dt_obj
    else: # date object
        dt_with_time = datetime.combine(dt_obj, dt_time.min, tzinfo=timezone.utc) # Assume UTC for date start
    return str(int(dt_with_time.timestamp())) # UTC timestamp

def _parse_shoonya_ohlc(data: List[Dict[str, str]], interval_str: str) -> List[models.OHLCDataPoint]:
    parsed_data = []
    for item in data:
        try:
            dt_object = None
            time_str = item.get('time')
            ssboe_str = item.get('ssboe')

            if time_str:
                try:
                    # Assuming Shoonya time_str is naive but represents UTC or includes offset
                    # For "dd-mm-YYYY HH:MM:SS", pandas parses it as naive.
                    dt_object_naive = pd.to_datetime(time_str, dayfirst=True).to_pydatetime()
                    # Explicitly make it UTC. If Shoonya time_str is IST, this needs correction:
                    # 1. Parse as IST naive: dt_object_naive = ...
                    # 2. Localize to IST: ist_tz = pytz.timezone('Asia/Kolkata') or zoneinfo.ZoneInfo('Asia/Kolkata')
                    #    dt_object_ist = ist_tz.localize(dt_object_naive)
                    # 3. Convert to UTC: dt_object = dt_object_ist.astimezone(timezone.utc)
                    # For now, assuming time_str represents UTC if provided.
                    dt_object = dt_object_naive.replace(tzinfo=timezone.utc)
                except Exception as e_parse:
                    logger.warning(f"Could not parse 'time' string: '{time_str}' (Error: {e_parse}). Item: {item}. Trying 'ssboe'.")
            
            if dt_object is None and ssboe_str:
                try:
                    # ssboe is typically a UTC epoch timestamp
                    dt_object = datetime.fromtimestamp(int(ssboe_str), tz=timezone.utc)
                except ValueError:
                    logger.warning(f"Could not parse 'ssboe' string: {ssboe_str} for item: {item}.")
                    continue

            if dt_object is None:
                logger.warning(f"Timestamp could not be determined for Shoonya data item: {item}")
                continue

            ohlc_point = models.OHLCDataPoint(
                time=dt_object, # UTC-aware datetime
                open=float(item.get('into', item.get('op', 0.0))),
                high=float(item.get('inth', item.get('hp', 0.0))),
                low=float(item.get('intl', item.get('lp', 0.0))),
                close=float(item.get('intc', item.get('cp', 0.0))),
                volume=int(float(item.get('v', item.get('vol', 0)))) if item.get('v') or item.get('vol') else None,
                oi=int(float(item.get('oi', 0))) if item.get('oi') else None,
            )
            parsed_data.append(ohlc_point)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Skipping malformed Shoonya data point: {item}. Error: {e}", exc_info=True)
            continue
    return sorted(parsed_data, key=lambda x: x.time)


async def _store_data_to_db_background(
    exchange: str,
    token: str,
    data_points: List[models.OHLCDataPoint]
):
    if not data_points:
        return
    loop = asyncio.get_running_loop()
    def db_operation():
        try:
            with _get_db_connection() as conn:
                cursor = conn.cursor()
                records_to_insert = [
                    _ohlc_datapoint_to_db_tuple(dp, exchange, token) for dp in data_points
                ]
                cursor.executemany('''
                    INSERT OR IGNORE INTO ohlc_data 
                    (exchange, token, timestamp, time_iso, open, high, low, close, volume, oi)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', records_to_insert)
                conn.commit()
                logger.info(f"BG DB Store: Stored/Ignored {len(records_to_insert)} 1-min records for {exchange}:{token}.")
        except sqlite3.Error as e:
            logger.error(f"BG DB Store: SQLite error for {exchange}:{token}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"BG DB Store: General error for {exchange}:{token}: {e}", exc_info=True)
    await loop.run_in_executor(background_executor, db_operation)
    logger.debug(f"BG DB Store: Task submitted for {len(data_points)} points for {exchange}:{token}.")


async def _get_historical_data_from_db(
    exchange: str,
    token: str,
    start_datetime_utc: datetime, 
    end_datetime_utc: datetime   
) -> List[models.OHLCDataPoint]:
    db_data_points = []
    try:
        # start_datetime_utc and end_datetime_utc are expected to be UTC-aware
        start_ts_utc = int(start_datetime_utc.timestamp())
        end_ts_utc = int(end_datetime_utc.timestamp())

        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM ohlc_data
                WHERE exchange = ? AND token = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
            ''', (exchange.upper(), token, start_ts_utc, end_ts_utc))
            rows = cursor.fetchall()
            for row in rows:
                db_data_points.append(_db_row_to_ohlc_datapoint(row))
        logger.info(f"DB Read: Fetched {len(db_data_points)} 1-min records for {exchange}:{token} "
                    f"from {start_datetime_utc.isoformat()} to {end_datetime_utc.isoformat()} (UTC).")
    except sqlite3.Error as e:
        logger.error(f"DB Read: SQLite error for {exchange}:{token}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"DB Read: General error for {exchange}:{token}: {e}", exc_info=True)
    return db_data_points

async def _fetch_1min_data_from_api(
    api: ShoonyaApiPy,
    exchange: str,
    token: str,
    start_datetime_api_utc: datetime, 
    end_datetime_api_utc: datetime   
) -> List[models.OHLCDataPoint]:
    # start_datetime_api_utc and end_datetime_api_utc are UTC-aware
    logger.info(f"API Fetch (1-min): Requesting for {exchange}:{token} "
                f"from {start_datetime_api_utc.isoformat()} to {end_datetime_api_utc.isoformat()} (UTC).")

    api_start_time_str = _format_shoonya_time(start_datetime_api_utc) # Converts UTC dt to UTC timestamp string
    api_end_time_str = _format_shoonya_time(end_datetime_api_utc)   # Converts UTC dt to UTC timestamp string
    api_interval = "1"

    for attempt in range(settings.API_RETRIES):
        try:
            response = api.get_time_price_series(
                exchange=exchange.upper(),
                token=token,
                starttime=api_start_time_str,
                endtime=api_end_time_str,
                interval=api_interval
            )
            if response and isinstance(response, list):
                logger.info(f"API Fetch (1-min): Received {len(response)} data points for {exchange}:{token}.")
                parsed_points = _parse_shoonya_ohlc(response, api_interval) # Returns list of UTC-aware OHLCDataPoint
                return parsed_points
            elif response and isinstance(response, dict) and response.get('stat') == 'Not_Ok':
                emsg = response.get('emsg', 'Unknown API error')
                logger.error(f"API Fetch (1-min): Error for {exchange}:{token}: {emsg}")
                if "no_data" in emsg.lower():
                    return [] 
                if attempt < settings.API_RETRIES - 1:
                    await asyncio.sleep(settings.API_RETRY_DELAY * (2**attempt))
                else:
                    return []
            else:
                logger.warning(f"API Fetch (1-min): Unexpected response for {exchange}:{token}: {response}")
                if attempt < settings.API_RETRIES - 1:
                    await asyncio.sleep(settings.API_RETRY_DELAY * (2**attempt))
                else:
                    return []
        except Exception as e:
            logger.error(f"API Fetch (1-min): Exception for {exchange}:{token}: {e}", exc_info=True)
            if attempt < settings.API_RETRIES - 1:
                await asyncio.sleep(settings.API_RETRY_DELAY * (2**attempt))
            else:
                return []
    return []

def _resample_ohlc_data(
    one_min_data_points: List[models.OHLCDataPoint], # Expects UTC-aware datetimes in points
    target_interval_str: str 
) -> List[models.OHLCDataPoint]:
    if not one_min_data_points:
        return []
    
    rule = target_interval_str.upper()
    if rule.isdigit():
        rule += 'min'
    elif rule == 'D':
        pass
    elif rule.endswith('H'):
        pass
    
    if rule in ['1MIN', '1T']: # Standardize to 1min for comparison
        return one_min_data_points

    try:
        # OHLCDataPoint.time is UTC-aware datetime
        df = pd.DataFrame([item.model_dump() for item in one_min_data_points])
        if df.empty:
            return []
            
        df['time'] = pd.to_datetime(df['time']) # This will preserve UTC tz-awareness
        df.set_index('time', inplace=True)

        resampled_df = df.resample(rule, label='right', closed='right').agg({ # Adjust label/closed as per typical financial convention
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
            'oi': 'last' 
        }).dropna(subset=['open'])

        resampled_data = []
        for timestamp, row_data in resampled_df.iterrows():
            # timestamp from resampled_df.iterrows() is UTC-aware
            resampled_data.append(models.OHLCDataPoint(
                time=timestamp.to_pydatetime(), # Still UTC-aware
                open=row_data['open'],
                high=row_data['high'],
                low=row_data['low'],
                close=row_data['close'],
                volume=int(row_data['volume']) if pd.notna(row_data['volume']) else None,
                oi=int(row_data['oi']) if pd.notna(row_data['oi']) else None,
            ))
        logger.info(f"Resample: {len(one_min_data_points)} (1-min) -> {len(resampled_data)} ({rule}) for interval '{target_interval_str}'.")
        return resampled_data
    except Exception as e:
        logger.error(f"Resample: Error resampling to {target_interval_str} (rule: {rule}): {e}", exc_info=True)
        return one_min_data_points # Fallback or handle differently


async def get_historical_data_orchestrator(
    exchange: str,
    token: str,
    req_start_date: date,       
    req_end_date: date,         
    req_interval: str           
) -> List[models.OHLCDataPoint]:
    api_client: ShoonyaApiPy = get_shoonya_api_client()

    # Create UTC-aware datetime objects for the requested range
    db_start_dt_utc = datetime.combine(req_start_date, dt_time.min, tzinfo=timezone.utc)
    db_end_dt_utc = datetime.combine(req_end_date, dt_time(23, 59, 59), tzinfo=timezone.utc)

    # API request datetimes are also UTC aware now
    api_req_start_dt_utc = db_start_dt_utc
    api_req_end_dt_utc = db_end_dt_utc

    logger.info(f"Data Orchestrator: {exchange}:{token} for {req_start_date} to {req_end_date}, interval '{req_interval}'.")
    logger.debug(f"DB query range (UTC): {db_start_dt_utc.isoformat()} to {db_end_dt_utc.isoformat()}")
    
    db_1min_data = await _get_historical_data_from_db(exchange, token, db_start_dt_utc, db_end_dt_utc)
    all_1min_data = list(db_1min_data) # All data points here have UTC-aware .time
    
    fetch_from_api = True
    api_fetch_start_range_utc = api_req_start_dt_utc
    api_fetch_end_range_utc = api_req_end_dt_utc

    if db_1min_data:
        latest_db_time_utc = max(dp.time for dp in all_1min_data if isinstance(dp.time, datetime)) # This is UTC-aware
        
        if latest_db_time_utc >= db_end_dt_utc - timedelta(minutes=1):
            logger.info(f"Data Orchestrator: Sufficient 1-min data found in DB until {latest_db_time_utc.isoformat()}. No API fetch needed.")
            fetch_from_api = False
        else:
            api_fetch_start_range_utc = latest_db_time_utc + timedelta(minutes=1)
            api_fetch_start_range_utc = max(api_fetch_start_range_utc, api_req_start_dt_utc) # Ensure it doesn't go before request
            logger.info(f"Data Orchestrator: DB data incomplete (ends {latest_db_time_utc.isoformat()}). "
                        f"Will try API fetch from {api_fetch_start_range_utc.isoformat()}.")
    else:
        logger.info(f"Data Orchestrator: No 1-min data in DB for range. Full API fetch initiated.")

    if fetch_from_api and api_fetch_start_range_utc <= api_fetch_end_range_utc:
        api_1min_data = await _fetch_1min_data_from_api(
            api_client, exchange, token, api_fetch_start_range_utc, api_fetch_end_range_utc
        ) # Returns list of UTC-aware OHLCDataPoint
        if api_1min_data:
            asyncio.create_task(
                _store_data_to_db_background(exchange, token, api_1min_data)
            )
            existing_timestamps = {dp.time for dp in all_1min_data}
            unique_api_data = [dp for dp in api_1min_data if dp.time not in existing_timestamps]
            all_1min_data.extend(unique_api_data)
            all_1min_data.sort(key=lambda x: x.time)
            logger.info(f"Data Orchestrator: Merged {len(unique_api_data)} new 1-min API points.")
    
    if not all_1min_data:
        logger.warning(f"Data Orchestrator: No 1-min data available for {exchange}:{token} after DB and API checks.")
        return []

    final_user_interval_data = []
    # Standardize interval comparison
    normalized_req_interval = req_interval.lower()
    if normalized_req_interval in ['1', '1t', '1m', '1min']:
        final_user_interval_data = all_1min_data
    else:
        final_user_interval_data = _resample_ohlc_data(all_1min_data, req_interval)
        
    # Filter final data to be strictly within the day-boundaries of requested start/end dates
    # All dp.time objects are UTC-aware here.
    # req_start_date and req_end_date are date objects.
    filtered_output_data = [
        dp for dp in final_user_interval_data
        if req_start_date <= dp.time.astimezone(timezone.utc).date() <= req_end_date # Compare dates in UTC
    ]

    logger.info(f"Data Orchestrator: Final processed data for {exchange}:{token} ({req_interval}) has {len(filtered_output_data)} points.")
    return filtered_output_data


async def fetch_and_store_historical_data(
    request: models.HistoricalDataRequest
) -> models.HistoricalDataResponse:
    try:
        ohlc_data_points = await get_historical_data_orchestrator(
            exchange=request.exchange,
            token=request.token,
            req_start_date=request.start_time, 
            req_end_date=request.end_time,     
            req_interval=request.interval      
        )
        message = "Data processed successfully."
        if not ohlc_data_points:
            is_old_request = request.end_time < (date.today() - timedelta(days=2))
            if is_old_request:
                message = "No historical data found for the specified older period after checking database and API."
            else:
                message = "No data found for the given parameters after checking database and API."
        
        return models.HistoricalDataResponse(
            request_params=request,
            data=ohlc_data_points, # List of OHLCDataPoint with UTC-aware .time
            count=len(ohlc_data_points),
            message=message
        )
    except Exception as e:
        logger.error(f"Critical error in fetch_and_store_historical_data for {request.exchange}:{request.token}: {e}", exc_info=True)
        return models.HistoricalDataResponse(
            request_params=request,
            data=[],
            count=0,
            message=f"An internal server error occurred: {str(e)}"
        )
  
async def get_token_info(exchange: str, token: str) -> Optional[TokenInfo]:
    exchange_upper = exchange.upper()
    try:
        scripmaster_df = load_scripmaster(exchange_upper) 
    except FileNotFoundError:
        logger.warning(f"Scripmaster not found for {exchange_upper} when attempting to get token info for {token}.")
        return None
    
    if scripmaster_df is None or scripmaster_df.empty:
        logger.warning(f"Scripmaster is None or empty for {exchange_upper} when getting token info for {token}.")
        return None
    
    token_data = scripmaster_df[scripmaster_df['Token'] == token]

    if token_data.empty:
        logger.warning(f"Token {token} not found in scripmaster for exchange {exchange_upper}.")
        return None

    row = token_data.iloc[0]
    symbol_val = row.get('Symbol', 'N/A')
    trading_symbol_val = row.get('TradingSymbol', row.get('Tsym', f"{symbol_val}-{token}"))
    instrument_val = row.get('Instrument', row.get('Instname', 'N/A'))

    return TokenInfo(
        exchange=exchange_upper,
        token=str(row['Token']),
        symbol=str(symbol_val),
        trading_symbol=str(trading_symbol_val),
        instrument=str(instrument_val) if pd.notna(instrument_val) else None
    )