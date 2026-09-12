"""Backend-directory entry point: uvicorn main:app --reload."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import app

__all__ = ["app"]
