import uvicorn
import sys
from pathlib import Path

# Add the project root to the Python path
root_path = str(Path(__file__).parent)
if root_path not in sys.path:
    sys.path.append(root_path)

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1
    )