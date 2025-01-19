import uvicorn
from src.app import app
from src.config.settings import APP_PORT, DEBUG

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=APP_PORT,
        reload=DEBUG
    )
