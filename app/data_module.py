import os
import asyncio
from datetime import datetime, timezone, date, time as dt_time
from typing import List, Dict, Any
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import mysql.connector
from mysql.connector import pooling

from .models import TokenInfo, OHLCDataPoint, HistoricalDataRequest, HistoricalDataResponse
from .config import settings, logger
from .auth import get_shoonya_api_client

from pathlib import Path
from dateutil import parser


background_executor = ThreadPoolExecutor(max_workers=5)
_scripmaster_data: Dict[str, pd.DataFrame] = {}
_persistent_1min_data_cache: Dict[str, List[OHLCDataPoint]] = defaultdict(list)

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root123")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "trading_db")

_db_pool = pooling.MySQLConnectionPool(
    pool_name="ohlc_pool",
    pool_size=5,
    host=MYSQL_HOST,
    user=MYSQL_USER,
    password=MYSQL_PASSWORD,
    database=MYSQL_DATABASE,
    autocommit=True
)

def _get_db_connection():
    return _db_pool.get_connection()

def _init_db():
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ohlc_data (
                exchange VARCHAR(10) NOT NULL,
                token VARCHAR(20) NOT NULL,
                timestamp BIGINT NOT NULL,
                time_iso VARCHAR(32) NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume BIGINT,
                oi BIGINT,
                PRIMARY KEY (exchange, token, timestamp)
            ) ENGINE=InnoDB;
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Database initialized and verified in MySQL.")
    except Exception as e:
        logger.error(f"MySQL DB Initialization failed: {e}")

_init_db()


def load_scripmaster(exchange: str) -> pd.DataFrame:
    exchange = exchange.upper()
    if exchange in _scripmaster_data:
        return _scripmaster_data[exchange]

    scripmaster_dir = Path(settings.SCRIPMASTER_DIR)
    path = next(
        (scripmaster_dir / f for f in [
            f"{exchange}_symbols.txt",
            f"{exchange}.txt",
            f"{exchange}_symbols.csv",
            f"{exchange}.csv"
        ] if (scripmaster_dir / f).exists()),
        None
    )

    if not path:
        raise FileNotFoundError(f"Scripmaster for {exchange} not found in {settings.SCRIPMASTER_DIR}")

    df = pd.read_csv(path)
    if 'Token' not in df.columns or 'Symbol' not in df.columns:
        raise ValueError("Scripmaster file must have 'Token' and 'Symbol' columns")

    df['Token'] = df['Token'].astype(str)
    _scripmaster_data[exchange] = df
    logger.info(f"Scripmaster loaded for {exchange} from {path} with {len(df)} entries.")
    return df

def get_available_symbols(exchange: str) -> List[str]:
    df = load_scripmaster(exchange)
    return df['Symbol'].dropna().unique().tolist()

def _get_historical_data_from_db(exchange: str, token: str, start_dt: datetime, end_dt: datetime) -> List[OHLCDataPoint]:
    data = []
    try:
        conn = _get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('''
            SELECT * FROM ohlc_data
            WHERE exchange = %s AND token = %s AND timestamp BETWEEN %s AND %s
            ORDER BY timestamp ASC
        ''', (exchange.upper(), token, int(start_dt.timestamp()), int(end_dt.timestamp())))
        for row in cursor.fetchall():
            data.append(OHLCDataPoint(
                time=datetime.fromtimestamp(row['timestamp'], tz=timezone.utc),
                open=row['open'], high=row['high'], low=row['low'], close=row['close'],
                volume=row.get('volume', 0), oi=row.get('oi', 0)
            ))
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"MySQL fetch error: {e}")
    return data

def _store_data_to_db(exchange: str, token: str, points: List[OHLCDataPoint]):
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        values = [(
            exchange.upper(), token, int(dp.time.timestamp()), dp.time.isoformat(),
            dp.open, dp.high, dp.low, dp.close, dp.volume, dp.oi
        ) for dp in points]
        cursor.executemany('''
            INSERT IGNORE INTO ohlc_data
            (exchange, token, timestamp, time_iso, open, high, low, close, volume, oi)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', values)
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Stored {len(values)} OHLC records for {exchange}:{token}.")
    except Exception as e:
        logger.error(f"MySQL insert error: {e}")

async def _store_data_async(exchange: str, token: str, data: List[OHLCDataPoint]):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(background_executor, _store_data_to_db, exchange, token, data)

async def fetch_and_store_historical_data(req: HistoricalDataRequest) -> HistoricalDataResponse:
    exchange = req.exchange.upper()
    token = str(req.token)
    interval = req.interval

    from_dt = datetime.combine(req.start_time, datetime.min.time(), tzinfo=timezone.utc)
    to_dt = datetime.combine(req.end_time, datetime.min.time(), tzinfo=timezone.utc)

    db_data = _get_historical_data_from_db(exchange, token, from_dt, to_dt)
    if db_data:
        return HistoricalDataResponse(data=db_data, count=len(db_data), request_params=req.model_dump())

    logger.info(f"No DB data for {exchange}:{token}, fetching from Shoonya")
    api = get_shoonya_api_client()
    try:
        response = api.get_time_price_series(
            exchange=exchange,
            token=token,
            interval=interval,
            starttime=str(int(from_dt.timestamp())),
            endtime=str(int(to_dt.timestamp()))
        )
        if isinstance(response, dict) and response.get("stat") == "Not_Ok":
            emsg = response.get("emsg", "Unknown error")
            logger.error(f"Shoonya API error: {emsg}")
            raise RuntimeError(f"Shoonya API error: {emsg}")

        if not isinstance(response, list):
            logger.warning(f"Unexpected Shoonya response: {response}")
            raise RuntimeError("Shoonya API response is not a list")
        data = [
            OHLCDataPoint(
                time=datetime.fromtimestamp(int(candle['ssboe']), tz=timezone.utc),
                open=float(candle['into']),
                high=float(candle['inth']),
                low=float(candle['intl']),
                close=float(candle['intc']),
                volume=int(candle.get('v', 0)),
                oi=int(candle.get('oi', 0))
            )
            for candle in response
        ]

        await _store_data_async(exchange, token, data)
        return HistoricalDataResponse(data=data, count=len(data), request_params=req.model_dump())
    except Exception as e:
        logger.error(f"Shoonya API historical fetch failed: {e}")
        return HistoricalDataResponse(data=[], count=0, request_params=req.model_dump())
