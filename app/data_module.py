# app/data_module.py
import pandas as pd
import os
from datetime import datetime, date, timedelta, time as dt_time
from typing import List, Dict, Optional, Union
import time # For rate limiting, if necessary

from .config import settings, logger
from .auth import get_shoonya_api_client # Manages login and returns API client instance
from api_helper import ShoonyaApiPy # For type hinting
from . import models # For response models

# --- Scripmaster Loading ---
SCRIPMASTER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Scripmaster'))# Assuming scripmaster files are CSV and have a common structure.
# Example columns: Exchange,Token,LotSize,Symbol,TradingSymbol,Expiry,Instrument,OptionType,StrikePrice,TickSize

_scripmaster_data: Dict[str, pd.DataFrame] = {} # Cache for loaded scripmaster data

def load_scripmaster(exchange: str) -> pd.DataFrame:
    """
    Loads the scripmaster file for a given exchange.
    Example: exchange="NSE" will look for "NSE_symbols.txt" or "NSE.csv"
    """
    global _scripmaster_data
    exchange_upper = exchange.upper()
    if exchange_upper in _scripmaster_data:
        return _scripmaster_data[exchange_upper]

    # Try common extensions like .txt or .csv
    possible_filenames = [
        f"{exchange_upper}_symbols.txt",
        f"{exchange_upper}.txt",
        f"{exchange_upper}_symbols.csv",
        f"{exchange_upper}.csv"
    ]
    
    filepath = None
    for fname in possible_filenames:
        potential_path = os.path.join(SCRIPMASTER_DIR, fname)
        if os.path.exists(potential_path):
            filepath = potential_path
            break
    
    if not filepath:
        logger.error(f"Scripmaster file not found for exchange: {exchange} in {SCRIPMASTER_DIR}")
        raise FileNotFoundError(f"Scripmaster file not found for exchange: {exchange}")

    try:
        # Adjust read_csv parameters based on actual file format (delimiter, headers)
        df = pd.read_csv(filepath, low_memory=False)
        # Basic validation: Ensure 'Token' and 'Symbol' columns exist
        if 'Token' not in df.columns or 'Symbol' not in df.columns:
            raise ValueError("Scripmaster CSV must contain 'Token' and 'Symbol' columns")
        df['Token'] = df['Token'].astype(str) # Ensure token is string
        _scripmaster_data[exchange_upper] = df
        logger.info(f"Scripmaster loaded for {exchange_upper} from {filepath} with {len(df)} entries.")
        return df
    except Exception as e:
        logger.error(f"Error loading scripmaster for {exchange}: {e}", exc_info=True)
        raise

async def get_available_symbols(exchange: str) -> models.AvailableSymbolsResponse:
    """
    Lists available symbols for a given exchange from the scripmaster.
    """
    try:
        df = load_scripmaster(exchange)
        symbols_info = []
        for _, row in df.iterrows():
            # Handle potential NaN values for optional string fields
            instrument_val = row.get('Instrument')
            instrument_str = str(instrument_val) if pd.notna(instrument_val) and instrument_val != '' else None
            # Handle other optional fields similarly if they might be NaN and are strings
            trading_symbol_val = row.get('TradingSymbol', row.get('Symbol')) # Fallback
            trading_symbol_str = str(trading_symbol_val) if pd.notna(trading_symbol_val) and trading_symbol_val != '' else None


            symbols_info.append(models.TokenInfo(
                exchange=row.get('Exchange', exchange.upper()),
                token=str(row['Token']),
                symbol=str(row['Symbol']) if pd.notna(row['Symbol']) else 'N/A', # Ensure symbol is also a string
                trading_symbol=trading_symbol_str,
                instrument=instrument_str # Use the processed value
            ))
        
        return models.AvailableSymbolsResponse(
            exchange=exchange.upper(),
            symbols=symbols_info,
            count=len(symbols_info)
        )
    except FileNotFoundError: # This should be caught by the endpoint if load_scripmaster raises it
        logger.error(f"Scripmaster file not found for exchange: {exchange} in get_available_symbols")
        raise # Re-raise to be caught by the endpoint's exception handler
    except Exception as e:
        logger.error(f"Error getting available symbols for {exchange}: {e}", exc_info=True)
        # This will be caught by the endpoint and turned into a 500 error.
        # If it's a validation error from TokenInfo, it might be better to let it propagate
        # or catch pydantic.ValidationError specifically.
        raise # Re-raise for the endpoint to handle

# --- Historical Data Fetching & Processing ---
def _format_shoonya_time(dt_obj: Union[date, datetime]) -> str:
    """Formats date/datetime to Shoonya API's expected time string (epoch seconds)."""
    if isinstance(dt_obj, datetime):
        dt_with_time = dt_obj
    else: # it's a date object
        dt_with_time = datetime.combine(dt_obj, dt_time.min) # Use start of day
    return str(int(dt_with_time.timestamp()))

def _parse_shoonya_ohlc(data: List[Dict[str, str]], interval_is_daily: bool) -> List[models.OHLCDataPoint]:
    """Parses Shoonya's string-based OHLC data into structured OHLCDataPoint."""
    parsed_data = []
    for item in data:
        try:
            dt_object = None
            # Prioritize 'ssboe' (seconds since beginning of epoch) for timestamp
            ssboe_str = item.get('ssboe')
            if ssboe_str:
                try:
                    dt_object = datetime.fromtimestamp(int(ssboe_str))
                except ValueError:
                    logger.warning(f"Could not parse 'ssboe' string: {ssboe_str} for item: {item}. Falling back to 'time'.")
                    dt_object = None # Reset on failure

            # If 'ssboe' parsing failed or 'ssboe' was not present, try parsing 'time' field
            if dt_object is None:
                time_str = item.get('time')
                if time_str:
                    try:
                        # Pandas to_datetime is flexible with formats, then convert to python datetime
                        dt_object = pd.to_datetime(time_str).to_pydatetime()
                    except ValueError:
                        logger.warning(f"Could not parse 'time' string: {time_str} for item: {item}.")
                        continue # Skip this data point if time cannot be parsed
                else:
                    logger.warning(f"Missing both 'ssboe' and 'time' fields in data item: {item}")
                    continue # Skip if no time information

            if dt_object is None: # Should not happen if logic above is correct, but as a safeguard
                logger.warning(f"Timestamp could not be determined for item: {item}")
                continue

            ohlc_point = models.OHLCDataPoint(
                time=dt_object,
                open=float(item.get('into', item.get('op', 0.0))),
                high=float(item.get('inth', item.get('hp', 0.0))),
                low=float(item.get('intl', item.get('lp', 0.0))),
                close=float(item.get('intc', item.get('cp', 0.0))),
                volume=int(float(item.get('v', item.get('vol', 0)))) if item.get('v') or item.get('vol') else None, # Handle potential float string for volume
                oi=int(float(item.get('oi', 0))) if item.get('oi') else None, # Handle potential float string for oi
            )
            parsed_data.append(ohlc_point)
        except (ValueError, KeyError, TypeError) as e: # Added TypeError
            logger.warning(f"Skipping malformed data point: {item}. Error: {e}", exc_info=True)
            continue
    return sorted(parsed_data, key=lambda x: x.time)

async def get_historical_data(
    exchange: str,
    token: str,
    start_time: date,
    end_time: date,
    interval: str
) -> List[models.OHLCDataPoint]:
    """
    Fetches historical data from Shoonya API.
    Handles potential rate limits and data parsing.
    """
    api: ShoonyaApiPy = get_shoonya_api_client() # Ensures login

    logger.info(f"Fetching historical data for {exchange}:{token} from {start_time} to {end_time} interval {interval}")

    # Shoonya API might have limits on date range per call (e.g., 100 days for daily)
    # For simplicity, this example doesn't implement chunking for very long date ranges.
    # This would be an enhancement if needed.

    # Convert start_time and end_time to include full day for end_time if daily
    api_start_time_str = _format_shoonya_time(start_time)
    
    # For end_time, ensure it covers the whole day if it's just a date
    # Shoonya's API might interpret end_time as exclusive or inclusive of start of day.
    # Typically, for daily data, end_time would be the last day inclusive.
    # For intraday, end_time would be precise.
    # Let's make end_time the end of the specified day to be safe.
    effective_end_time = datetime.combine(end_time, dt_time(23, 59, 59))
    api_end_time_str = _format_shoonya_time(effective_end_time)
    
    interval_is_daily = interval.upper() == 'D'

    retries = 3
    for i in range(retries):
        try:
            # The actual API call method and parameters might differ slightly
            # based on NorenRestApiPy's exact interface for historical data.
            # Common parameters: exch, token, st, et, intrvl
            response = api.get_time_price_series(
                exchange=exchange.upper(),
                token=token,
                starttime=api_start_time_str,
                endtime=api_end_time_str,
                interval=interval
            )
            
            if response and isinstance(response, list): # Successful response is usually a list of dicts
                logger.info(f"Received {len(response)} data points from API for {exchange}:{token}")
                return _parse_shoonya_ohlc(response, interval_is_daily)
            elif response and isinstance(response, dict) and response.get('stat') == 'Not_Ok':
                logger.error(f"API Error for {exchange}:{token}: {response.get('emsg', 'Unknown error')}")
                if response.get('emsg', '').strip() == "no_data": # Explicit no data message
                    return []
                # Consider specific error handling or retries for certain messages
                if i < retries - 1:
                    logger.info(f"Retrying ({i+1}/{retries})...")
                    await asyncio.sleep(2**(i)) # Exponential backoff
                    continue
                return [] # Or raise an exception
            else:
                logger.warning(f"Unexpected API response for {exchange}:{token}: {response}")
                if i < retries - 1:
                    logger.info(f"Retrying ({i+1}/{retries})...")
                    await asyncio.sleep(2**(i))
                    continue
                return [] # Or raise

        except Exception as e:
            logger.error(f"Exception during API call for {exchange}:{token}: {e}", exc_info=True)
            if i < retries - 1:
                logger.info(f"Retrying ({i+1}/{retries})...")
                # Be careful with asyncio.sleep in synchronous function context if not using async def for outer.
                # For now, assuming this module's functions might be called from FastAPI async endpoints.
                import asyncio # Ensure asyncio is imported if using await
                await asyncio.sleep(2**(i)) 
                continue
            raise # Re-raise after final retry attempt

    return [] # Should not be reached if retries are handled properly

# --- Data Storage (Example: Parquet) ---
def get_parquet_file_path(exchange: str, token: str, interval: str) -> str:
    """Determines the path for storing/retrieving Parquet data."""
    sanitized_interval = interval.replace(" ", "").replace(":", "")
    filename = f"{exchange.upper()}_{token}_{sanitized_interval}.parquet"
    return os.path.join(settings.DATA_DIR, filename)

async def fetch_and_store_historical_data(
    request: models.HistoricalDataRequest
) -> models.HistoricalDataResponse:
    """
    Orchestrates fetching data, optionally storing/retrieving from cache (Parquet).
    This version will always fetch for now, but can be extended for caching.
    """
    os.makedirs(settings.DATA_DIR, exist_ok=True) # Ensure data directory exists
    
    # Caching logic could be added here:
    # parquet_path = get_parquet_file_path(request.exchange, request.token, request.interval)
    # if os.path.exists(parquet_path):
    #     # Add logic to check if cached data is up-to-date or covers requested range
    #     logger.info(f"Cache hit (logic to be implemented): {parquet_path}")
    #     # df = pd.read_parquet(parquet_path)
    #     # Convert df to List[models.OHLCDataPoint] and return

    ohlc_data_points = await get_historical_data(
        exchange=request.exchange,
        token=request.token,
        start_time=request.start_time,
        end_time=request.end_time,
        interval=request.interval
    )

    if ohlc_data_points:
        # Store fetched data to Parquet (optional, can be a separate step or configurable)
        # df_to_store = pd.DataFrame([item.model_dump() for item in ohlc_data_points])
        # if not df_to_store.empty:
        #     df_to_store.to_parquet(parquet_path, index=False)
        #     logger.info(f"Data for {request.exchange}:{request.token} saved to {parquet_path}")
        pass # Storing logic can be added later

    return models.HistoricalDataResponse(
        request_params=request,
        data=ohlc_data_points,
        count=len(ohlc_data_points),
        message="Data fetched successfully." if ohlc_data_points else "No data found for the given parameters."
    )