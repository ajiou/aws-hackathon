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
    # 稽查助手（ADR-0005）。CHAT_ENABLED 或 KB_ID 任一有設才啟用，否則 /chat 回 503；
    # 只有 CHAT_ENABLED 沒有 KB_ID 時是基礎模式：用園況回答、不檢索法規。
    chat_enabled: bool = False
    kb_id: str | None = None
    chat_model: str = "us.anthropic.claude-opus-4-6-v1"
    aws_region: str = "us-west-2"

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
            chat_enabled=os.environ.get("CHAT_ENABLED", "").lower() in ("1", "true")
            or bool(os.environ.get("KB_ID")),
            kb_id=os.environ.get("KB_ID") or None,
            chat_model=os.environ.get("CHAT_MODEL_ID") or cls.chat_model,
            aws_region=os.environ.get("AWS_REGION") or cls.aws_region,
        )
