# app/config.py
import os
import logging
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from a .env file at the project root
# Assuming your project structure is something like:
# project_root/
#  ├── .env
#  ├── app/
#  │   ├── config.py
#  │   └── ...
#  └── data/
#  └── Scripmaster/

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

class Settings:
    """
    Application settings.
    Values are loaded from environment variables or .env file.
    """
    # --- Shoonya API Credentials ---
    SHOONYA_USER_ID: str = os.getenv("SHOONYA_USER_ID", "your_user_id")
    SHOONYA_PASSWORD: str = os.getenv("SHOONYA_PASSWORD", "your_password")
    SHOONYA_VENDOR_CODE: str = os.getenv("SHOONYA_VENDOR_CODE", "your_vendor_code")
    SHOONYA_API_KEY: str = os.getenv("SHOONYA_API_KEY", "your_api_key")
    SHOONYA_IMEI: str = os.getenv("SHOONYA_IMEI", "your_imei_or_mac")
    SHOONYA_TOTP_SECRET: str = os.getenv("SHOONYA_TOTP_SECRET", "your_totp_secret_key")

    # --- Data and File Paths ---
    # Base directory for all data files (cache, DBs, etc.)
    DATA_DIR: Path = PROJECT_ROOT / os.getenv("DATA_DIR_NAME", "data_cache")
    # Directory for Scripmaster files
    SCRIPMASTER_DIR: Path = PROJECT_ROOT / os.getenv("SCRIPMASTER_DIR_NAME", "Scripmaster")
    # SQLite Database file path
    DATABASE_FILE_NAME: str = os.getenv("DATABASE_FILE_NAME", "historical_data.db")
    DATABASE_PATH: Path = DATA_DIR / DATABASE_FILE_NAME

    # --- API Interaction Settings ---
    API_RETRIES: int = int(os.getenv("API_RETRIES", "3"))
    API_RETRY_DELAY: int = int(os.getenv("API_RETRY_DELAY_SECONDS", "1")) # Base delay in seconds

    # --- Default Symbol (Example) ---
    DEFAULT_SYMBOL: str = os.getenv("DEFAULT_SYMBOL", "TATAMOTORS")
    DEFAULT_EXCHANGE: str = os.getenv("DEFAULT_EXCHANGE", "NSE")
    DEFAULT_TOKEN: str = os.getenv("DEFAULT_TOKEN", "3456")

    # --- Logging Configuration ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FORMAT: str = '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'

    # --- Charting ---
    LIGHTWEIGHT_CHART_VERSION: str = os.getenv("LIGHTWEIGHT_CHART_VERSION", "3.8.0")

    def __init__(self):
        # Ensure data directories exist
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Note: Scripmaster directory is expected to be manually created and populated.
        # If SCRIPMASTER_DIR needs to be created automatically, add:
        # self.SCRIPMASTER_DIR.mkdir(parents=True, exist_ok=True)

settings = Settings()

# --- Logging Setup ---
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format=settings.LOG_FORMAT,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("TradingApp") # Use a general logger name for the app

# Initial configuration log
logger.info("Configuration loaded. Application starting...")
logger.info(f"Data directory: {settings.DATA_DIR}")
logger.info(f"Database path: {settings.DATABASE_PATH}")
logger.info(f"Scripmaster directory: {settings.SCRIPMASTER_DIR}")

if settings.SHOONYA_USER_ID == "your_user_id" or not settings.SHOONYA_TOTP_SECRET:
    logger.warning(
        "Shoonya API credentials or TOTP secret seem to be using default placeholder values. "
        "Ensure they are set correctly via environment variables or the .env file for proper API functionality."
    )