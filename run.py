# run.py
import uvicorn
import os
import sys

# Add the project root to the Python path
# This allows modules in 'app' to be imported correctly (e.g., from app.main import app)
# and also allows 'app' to import from the root (e.g., from ..api_helper import ShoonyaApiPy)
# when 'app' is treated as a package.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)


if __name__ == "__main__":
    # Uvicorn server configuration
    host = "0.0.0.0"  # Listen on all available network interfaces
    port = 8000       # Standard port, can be changed
    reload = True     # Enable auto-reload for development (watches for file changes)
    log_level = "info" # Uvicorn's own log level

    print(f"Starting Uvicorn server on http://{host}:{port}")
    print(f"Auto-reload is {'enabled' if reload else 'disabled'}.")
    print(f"Access the API at http://{host}:{port}/docs for Swagger UI or http://{host}:{port}/redoc for ReDoc.")

    # Ensure the .env file is loaded if it exists, primarily for app.config
    # The app.config module itself tries to load .env, but this ensures it's early.
    from dotenv import load_dotenv
    dotenv_path = os.path.join(PROJECT_ROOT, '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path)
        print(f".env file loaded from {dotenv_path}")
    else:
        print(".env file not found, using environment variables or default settings.")

    # The application string 'app.main:app' means:
    # - 'app.main': Look for a module named main.py inside a package (folder) named 'app'.
    # - ':app': Inside main.py, find an instance named 'app' (which is our FastAPI instance).
    uvicorn.run("app.main:app", host=host, port=port, reload=reload, log_level=log_level)