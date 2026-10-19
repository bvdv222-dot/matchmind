import os

import uvicorn

port = int(os.environ.get("MM_PORT", "8000"))
uvicorn.run("api.app:app", host=os.environ.get("MM_HOST", "127.0.0.1"), port=port, log_level="info")
