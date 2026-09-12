"""Run as a module or with the shared repo's original backend/local_server.py command."""

import os
import sys
from pathlib import Path

import uvicorn

if __name__ == "__main__":
    if not __package__:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    uvicorn.run(
        "backend.app:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
