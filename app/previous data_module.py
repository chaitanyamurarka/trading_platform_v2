# app/data_module.py
import pandas as pd
import os
import sqlite3
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timedelta, time as dt_time, timezone
from typing import List, Dict, Optional, Union, TYPE_CHECKING, Any
from collections import defaultdict

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

_persistent_1min_data_cache: Dict[str, List[models.OHLCDataPoint]] = defaultdict(list)
_token_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

MARKET_INFO = {
    "NSE": {
        "close_time_utc": dt_time(10, 0, 0, tzinfo=timezone.utc),
    }
}

# Define a configurable constant for how stale data for "today" can be before forcing a DB read
# (e.g., if cache for today is older than X minutes from current time, refresh from DB)
# This could also be moved to settings.py
DATA_CACHE_STALE_MINUTES_TODAY = getattr(settings, 'DATA_CACHE_STALE_MINUTES_TODAY', 2)


# ... (load_scripmaster, get_available_symbols, _get_db_connection, _init_db)
# ... (_ohlc_datapoint_to_db_tuple, _db_row_to_ohlc_datapoint)
# ... (_format_shoonya_time, _parse_shoonya_ohlc)
# ... (_store_data_to_db_background, _get_historical_data_from_db)
# ... (_fetch_1min_data_from_api, _resample_ohlc_data)
# ... (_update_token_cache)
# All the above functions remain the same as in the provided file.
# For brevity, they are not repeated here but are assumed to be present.
# Copying them from the provided file content:

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
    )

def _db_row_to_ohlc_datapoint(row: tuple) -> models.OHLCDataPoint:
    return models.OHLCDataPoint(
        time=datetime.fromtimestamp(row[2], tz=timezone.utc), 
        open=row[4],
        high=row[5],
        low=row[6],
        close=row[7],
        volume=row[8],
        oi=row[9]
    )

def _format_shoonya_time(dt_obj: Union[date, datetime]) -> str:
    if isinstance(dt_obj, datetime):
        dt_with_time = dt_obj
    else: 
        dt_with_time = datetime.combine(dt_obj, dt_time.min, tzinfo=timezone.utc) 
    return str(int(dt_with_time.timestamp())) 

def _parse_shoonya_ohlc(data: List[Dict[str, str]], interval_str: str) -> List[models.OHLCDataPoint]:
    parsed_data = []
    for item in data:
        try:
            dt_object = None
            time_str = item.get('time')
            ssboe_str = item.get('ssboe')

            if time_str:
                try:
                    dt_object_naive = pd.to_datetime(time_str, dayfirst=True).to_pydatetime()
                    dt_object = dt_object_naive.replace(tzinfo=timezone.utc)
                except Exception as e_parse:
                    logger.warning(f"Could not parse 'time' string: '{time_str}' (Error: {e_parse}). Item: {item}. Trying 'ssboe'.")
            
            if dt_object is None and ssboe_str:
                try:
                    dt_object = datetime.fromtimestamp(int(ssboe_str), tz=timezone.utc)
                except ValueError:
                    logger.warning(f"Could not parse 'ssboe' string: {ssboe_str} for item: {item}.")
                    continue

            if dt_object is None:
                logger.warning(f"Timestamp could not be determined for Shoonya data item: {item}")
                continue

            ohlc_point = models.OHLCDataPoint(
                time=dt_object, 
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
    logger.info(f"API Fetch (1-min): Requesting for {exchange}:{token} "
                f"from {start_datetime_api_utc.isoformat()} to {end_datetime_api_utc.isoformat()} (UTC).")

    api_start_time_str = _format_shoonya_time(start_datetime_api_utc) 
    api_end_time_str = _format_shoonya_time(end_datetime_api_utc)   
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
                parsed_points = _parse_shoonya_ohlc(response, api_interval) 
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
    one_min_data_points: List[models.OHLCDataPoint], 
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
    
    if rule in ['1MIN', '1T']: 
        return one_min_data_points

    try:
        df = pd.DataFrame([item.model_dump() for item in one_min_data_points])
        if df.empty:
            return []
            
        df['time'] = pd.to_datetime(df['time']) 
        df.set_index('time', inplace=True)

        resampled_df = df.resample(rule, label='right', closed='right').agg({ 
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
            'oi': 'last' 
        }).dropna(subset=['open'])

        resampled_data = []
        for timestamp, row_data in resampled_df.iterrows():
            resampled_data.append(models.OHLCDataPoint(
                time=timestamp.to_pydatetime(), 
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
        return one_min_data_points

def _update_token_cache(cache_key: str, new_data_points: List[models.OHLCDataPoint]):
    global _persistent_1min_data_cache
    current_data = _persistent_1min_data_cache[cache_key]
    
    existing_timestamps = {dp.time for dp in current_data}
    truly_new_points = [dp for dp in new_data_points if dp.time not in existing_timestamps]
    
    if truly_new_points:
        current_data.extend(truly_new_points)
        current_data.sort(key=lambda x: x.time)
        logger.debug(f"Cache Update: Added {len(truly_new_points)} new points to {cache_key}. Cache size: {len(current_data)}")
    else:
        logger.debug(f"Cache Update: No new unique points to add to {cache_key} from the provided list of {len(new_data_points)}.")
    return truly_new_points

async def get_historical_data_orchestrator(
    exchange: str,
    token: str,
    req_start_date: date,
    req_end_date: date,
    req_interval: str
) -> List[models.OHLCDataPoint]:
    api_client: ShoonyaApiPy = get_shoonya_api_client()
    exchange_upper = exchange.upper()
    cache_key = f"{exchange_upper}:{token}"
    token_lock = _token_locks[cache_key]

    user_req_start_dt_utc = datetime.combine(req_start_date, dt_time.min, tzinfo=timezone.utc)
    user_req_end_dt_boundary_utc = datetime.combine(req_end_date, dt_time(23, 59, 59), tzinfo=timezone.utc)

    logger.info(f"Data Orchestrator: Starting for {cache_key}, Date Range: {req_start_date} to {req_end_date}, Interval: '{req_interval}'.")
    logger.debug(f"User request UTC start: {user_req_start_dt_utc.isoformat()}, User request input end date: {req_end_date}")

    all_1min_data_for_request: List[models.OHLCDataPoint] = []

    async with token_lock:
        logger.debug(f"Lock acquired for {cache_key}")

        current_utc_datetime = datetime.now(timezone.utc)
        current_utc_date = current_utc_datetime.date()

        effective_target_end_dt_utc = datetime.combine(req_end_date, dt_time(23, 59, 59), tzinfo=timezone.utc)
        market_details = MARKET_INFO.get(exchange_upper)
        if market_details:
            market_close_time_config = market_details["close_time_utc"]
            market_close_dt_on_req_end_date = datetime.combine(req_end_date, market_close_time_config)
            
            if req_end_date < current_utc_date:
                effective_target_end_dt_utc = min(effective_target_end_dt_utc, market_close_dt_on_req_end_date)
            elif req_end_date == current_utc_date:
                target_for_today = min(current_utc_datetime + timedelta(minutes=DATA_CACHE_STALE_MINUTES_TODAY + 1), market_close_dt_on_req_end_date) # ensure target is slightly ahead if market is open
                effective_target_end_dt_utc = min(effective_target_end_dt_utc, target_for_today)
            else: # Future day
                effective_target_end_dt_utc = min(effective_target_end_dt_utc, market_close_dt_on_req_end_date)
        logger.info(f"Effective target end datetime for {req_end_date} for {cache_key} is {effective_target_end_dt_utc.isoformat()}")

        # --- MODIFICATION: Check cache before DB read ---
        perform_db_read = True 
        if _persistent_1min_data_cache[cache_key]:
            # Check data from cache relevant to the effective range needed before API call
            cached_points_for_effective_range = [
                dp for dp in _persistent_1min_data_cache[cache_key]
                if dp.time >= user_req_start_dt_utc and dp.time <= effective_target_end_dt_utc # Effective range check
            ]

            if cached_points_for_effective_range:
                min_cached_dt_effective = min(dp.time for dp in cached_points_for_effective_range)
                max_cached_dt_effective = max(dp.time for dp in cached_points_for_effective_range)

                # Condition to skip DB read:
                # 1. Cache substantially covers the start of the user's request day (e.g., within market hours).
                # 2. Cache covers up to (or very near) the effective target end time.
                
                # Check if start is covered (e.g. first data point is on or before user_req_start_dt_utc, or at least near market open for that day)
                # For simplicity, we'll check if min_cached_dt_effective is on the same day as user_req_start_dt_utc.
                # A more robust check might involve market open times.
                start_covered = (min_cached_dt_effective.date() <= req_start_date) and \
                                (min_cached_dt_effective <= user_req_start_dt_utc + timedelta(hours=4)) # crude check for start of day data

                end_covered = (max_cached_dt_effective >= effective_target_end_dt_utc - timedelta(minutes=1))

                if start_covered and end_covered:
                    is_strictly_past_request = (req_end_date < current_utc_date)
                    
                    if is_strictly_past_request:
                        logger.info(f"Sufficient data for PAST day segment (up to {max_cached_dt_effective.isoformat()}) found in memory cache for {cache_key}. Skipping DB read.")
                        perform_db_read = False
                    else: # req_end_date is today or future
                        # For today, only skip DB if cache is very fresh compared to current time or effective target
                        if max_cached_dt_effective >= current_utc_datetime - timedelta(minutes=DATA_CACHE_STALE_MINUTES_TODAY):
                             logger.info(f"Sufficiently FRESH data for TODAY (up to {max_cached_dt_effective.isoformat()}) in memory cache for {cache_key}. Skipping DB read.")
                             perform_db_read = False
                        else:
                            logger.info(f"Cache for TODAY for {cache_key} (ends {max_cached_dt_effective.isoformat()}) might be stale against current time {current_utc_datetime.isoformat()}. Proceeding with DB read.")
            else: # No points in cache for the effective range
                logger.info(f"No data in cache for the effective range {user_req_start_dt_utc.isoformat()} to {effective_target_end_dt_utc.isoformat()} for {cache_key}.")

        if perform_db_read:
            logger.info(f"Proceeding with DB read for {cache_key} for range {req_start_date} to {req_end_date}.")
            db_query_start_utc = user_req_start_dt_utc
            db_query_end_utc = datetime.combine(req_end_date, dt_time(23,59,59), tzinfo=timezone.utc)
            
            db_1min_data = await _get_historical_data_from_db(exchange_upper, token, db_query_start_utc, db_query_end_utc)
            
            if db_1min_data:
                logger.info(f"Fetched {len(db_1min_data)} 1-min points from DB for {cache_key}.")
                _update_token_cache(cache_key, db_1min_data) # Update global cache
            else:
                logger.info(f"No data found in DB for {cache_key} in range {db_query_start_utc.isoformat()} to {db_query_end_utc.isoformat()}.")
        else:
            logger.info(f"DB Read SKIPPED for {cache_key} as sufficient data found in memory cache.")
        # --- END OF MODIFICATION ---

        current_global_cached_data = _persistent_1min_data_cache[cache_key]
        relevant_cached_data = [
            dp for dp in current_global_cached_data
            if user_req_start_dt_utc <= dp.time <= user_req_end_dt_boundary_utc 
        ]
        logger.info(f"Initialized with {len(relevant_cached_data)} points from in-memory cache (after potential DB sync) for {cache_key} within request range.")

        fetch_from_api = True
        api_fetch_start_range_utc = user_req_start_dt_utc 
        api_fetch_end_range_utc = effective_target_end_dt_utc 

        if relevant_cached_data:
            # Use max from relevant_cached_data, which reflects the user's broad request from start to end date boundary.
            latest_data_time_utc_in_relevant_cache = max(dp.time for dp in relevant_cached_data)
            
            # Check completeness against the effective_target_end_dt_utc
            if latest_data_time_utc_in_relevant_cache >= effective_target_end_dt_utc - timedelta(minutes=1):
                logger.info(f"Sufficient data found in cache (up to {latest_data_time_utc_in_relevant_cache.isoformat()}) against effective target {effective_target_end_dt_utc.isoformat()}. No API fetch needed for {cache_key}.")
                fetch_from_api = False
            else:
                # API fetch should start from the day after the latest data point if it's for a past day,
                # or from the next minute if it's for the same day.
                # More simply, start from next minute of latest data, but not before user_req_start_dt_utc.
                api_fetch_start_range_utc = latest_data_time_utc_in_relevant_cache + timedelta(minutes=1)
                api_fetch_start_range_utc = max(api_fetch_start_range_utc, user_req_start_dt_utc) # Ensure it doesn't go before user request start
                logger.info(f"Cache data incomplete (ends {latest_data_time_utc_in_relevant_cache.isoformat()}). Will try API fetch for {cache_key} from {api_fetch_start_range_utc.isoformat()} to {api_fetch_end_range_utc.isoformat()}.")
        else: # No relevant_cached_data
            logger.info(f"No data in cache for {cache_key} relevant to user's broad request range {user_req_start_dt_utc.isoformat()} to {user_req_end_dt_boundary_utc.isoformat()}. API fetch initiated: {api_fetch_start_range_utc.isoformat()} to {api_fetch_end_range_utc.isoformat()}.")
        
        if fetch_from_api and api_fetch_start_range_utc < api_fetch_end_range_utc:
            api_1min_data = await _fetch_1min_data_from_api(
                api_client, exchange_upper, token, api_fetch_start_range_utc, api_fetch_end_range_utc
            )
            if api_1min_data:
                logger.info(f"Fetched {len(api_1min_data)} 1-min points from API for {cache_key}.")
                newly_added_api_points = _update_token_cache(cache_key, api_1min_data)
                if newly_added_api_points:
                    asyncio.create_task(
                        _store_data_to_db_background(exchange_upper, token, newly_added_api_points)
                    )
                    logger.info(f"Scheduled DB storage for {len(newly_added_api_points)} new API points for {cache_key}.")
                else:
                    logger.info(f"No unique new points from API to store in DB for {cache_key}.")
        elif fetch_from_api and api_fetch_start_range_utc >= api_fetch_end_range_utc:
             logger.info(f"API fetch skipped for {cache_key}: calculated start time {api_fetch_start_range_utc.isoformat()} is not before end time {api_fetch_end_range_utc.isoformat()}.")

        final_cached_data_for_token = _persistent_1min_data_cache[cache_key]
        all_1min_data_for_request = [
            dp for dp in final_cached_data_for_token
            if user_req_start_dt_utc <= dp.time <= user_req_end_dt_boundary_utc 
        ]
        all_1min_data_for_request.sort(key=lambda x: x.time)
        logger.info(f"After all operations, {len(all_1min_data_for_request)} 1-min points selected for {cache_key} for the user's broad request range.")
        logger.debug(f"Lock released for {cache_key}")

    if not all_1min_data_for_request:
        logger.warning(f"Data Orchestrator: No 1-min data available for {cache_key} after all checks for the period {req_start_date} to {req_end_date}.")
        return []

    final_user_interval_data: List[models.OHLCDataPoint]
    normalized_req_interval = req_interval.lower().strip()
    if normalized_req_interval in ['1', '1t', '1m', '1min']:
        final_user_interval_data = all_1min_data_for_request
    else:
        logger.info(f"Resampling {len(all_1min_data_for_request)} 1-min points to '{req_interval}' for {cache_key}.")
        final_user_interval_data = _resample_ohlc_data(all_1min_data_for_request, req_interval)
    
    filtered_output_data = [
        dp for dp in final_user_interval_data
        if req_start_date <= dp.time.astimezone(timezone.utc).date() <= req_end_date
    ]

    logger.info(f"Data Orchestrator: Final processed data for {cache_key} ({req_interval}) has {len(filtered_output_data)} points for dates {req_start_date} to {req_end_date}.")
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
            data=ohlc_data_points, 
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