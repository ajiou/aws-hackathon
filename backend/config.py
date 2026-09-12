"""Environment configuration shared by local Uvicorn and Lambda."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    serving_dir: Path | None = None
    data_bucket: str | None = None
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @classmethod
    def from_env(cls) -> "Settings":
        directory = os.environ.get("SERVING_DIR")
        bucket = os.environ.get("DATA_BUCKET")
        if directory:
            path = Path(directory).expanduser().resolve()
        elif bucket:
            path = None
        else:
            path = ROOT / "out" / "serving"
            if not path.exists():
                path = ROOT / "frontend" / "mock"
        origins = os.environ.get("CORS_ORIGINS")
        return cls(
            serving_dir=path,
            data_bucket=bucket,
            cors_origins=tuple(x.strip() for x in origins.split(",") if x.strip())
            if origins is not None
            else (() if bucket else cls.cors_origins),
        )
