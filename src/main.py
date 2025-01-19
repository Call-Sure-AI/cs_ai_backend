import uvicorn
from config.settings import APP_PORT, DEBUG

if __name__ == "__main__":
    # Run the app using Uvicorn with import string
    uvicorn.run(
        "app:app",  # Use import string instead of app instance
        host="0.0.0.0",
        port=APP_PORT,
        reload=DEBUG,
        log_level="debug" if DEBUG else "info",
    )