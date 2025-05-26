# app/auth.py
import pyotp
import logging
from api_helper import ShoonyaApiPy # Assuming api_helper.py is in the parent directory
from .config import settings

logger = logging.getLogger(__name__)

# Get the singleton instance of ShoonyaApiPy
# The actual NorenApi initialization happens in ShoonyaApiPy's __new__ method
shoonya_api_client = ShoonyaApiPy()
_logged_in = False # Module-level flag to track login status for the singleton

def get_shoonya_api_client() -> ShoonyaApiPy:
    """
    Ensures the API client is logged in and returns the instance.
    """
    global _logged_in
    if not _logged_in:
        logger.info("Attempting Shoonya API login...")
        try:
            if not settings.SHOONYA_TOTP_SECRET or settings.SHOONYA_TOTP_SECRET == "your_totp_secret_key":
                logger.error("SHOONYA_TOTP_SECRET is not configured properly.")
                raise ValueError("SHOONYA_TOTP_SECRET is not configured.")

            totp = pyotp.TOTP(settings.SHOONYA_TOTP_SECRET)
            token = totp.now()

            login_response = shoonya_api_client.login(
                userid=settings.SHOONYA_USER_ID,
                password=settings.SHOONYA_PASSWORD,
                twoFA=token,
                vendor_code=settings.SHOONYA_VENDOR_CODE,
                api_secret=settings.SHOONYA_API_KEY,
                imei=settings.SHOONYA_IMEI
            )

            if login_response and login_response.get('stat') == 'Ok':
                _logged_in = True
                logger.info("Shoonya API login successful.")
                # Example: Start websocket if needed immediately after login
                # ws_opened = shoonya_api_client.start_websocket()
                # logger.info(f"Websocket opened: {ws_opened}")
            else:
                _logged_in = False
                logger.error(f"Shoonya API login failed: {login_response}")
                raise ConnectionError(f"Shoonya API login failed: {login_response}")

        except Exception as e:
            _logged_in = False
            logger.error(f"Exception during Shoonya API login: {e}", exc_info=True)
            raise ConnectionError(f"Exception during Shoonya API login: {e}")
    else:
        logger.debug("Shoonya API already logged in.")
    
    return shoonya_api_client

# You might want to add a function to explicitly trigger login if needed elsewhere,
# or rely on the first call to get_shoonya_api_client() to handle it.