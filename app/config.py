# app/config.py
import os
from dotenv import load_dotenv

# Load environment variables from a .env file (for local development)
# In production, these should be set directly in the environment or via a secrets manager.
load_dotenv()

class Settings:
    # Shoonya API Credentials
    SHOONYA_USER_ID: str = os.getenv("SHOONYA_USER_ID", "your_user_id")
    SHOONYA_PASSWORD: str = os.getenv("SHOONYA_PASSWORD", "your_password")
    SHOONYA_VENDOR_CODE: str = os.getenv("SHOONYA_VENDOR_CODE", "your_vendor_code")
    SHOONYA_API_KEY: str = os.getenv("SHOONYA_API_KEY", "your_api_key")
    SHOONYA_IMEI: str = os.getenv("SHOONYA_IMEI", "your_imei_or_mac") # Example IMEI/MAC
    SHOONYA_TOTP_SECRET: str = os.getenv("SHOONYA_TOTP_SECRET", "your_totp_secret_key") # Your 2FA secret

    # Data Storage
    DATA_DIR: str = os.getenv("DATA_DIR", "../data/") # Path to store historical data

    # Default Symbol (Example: TATA Motors EQ NSE, token 3456)
    DEFAULT_SYMBOL: str = os.getenv("DEFAULT_SYMBOL", "TATAMOTORS")
    DEFAULT_EXCHANGE: str = os.getenv("DEFAULT_EXCHANGE", "NSE")
    DEFAULT_TOKEN: str = os.getenv("DEFAULT_TOKEN", "3456") # As per your requirement

    # Logging Configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Lightweight Chart Version (Note for frontend, but can be stored here if backend serves version info)
    LIGHTWEIGHT_CHART_VERSION: str = "3.8.0" # Example, as per "old version" requirement

settings = Settings()

# Basic Logging Setup (can be more sophisticated)
import logging
logging.basicConfig(level=settings.LOG_LEVEL,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

logger.info("Configuration loaded.")
if settings.SHOONYA_USER_ID == "your_user_id" or not settings.SHOONYA_TOTP_SECRET:
    logger.warning("Shoonya API credentials or TOTP secret seem to be using default placeholder values. "
                   "Ensure they are set correctly via environment variables or a .env file.")