from __future__ import annotations

from pydantic import AnyUrl, BaseSettings, Field


class Settings(BaseSettings):
    database_url: AnyUrl
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    checker_concurrency: int = Field(default=20, ge=1)
    poll_interval_sec: float = Field(default=1.0, gt=0)
    lease_timeout_sec: float = Field(default=30.0, gt=0)
    fetch_batch_size: int = Field(default=100, ge=1)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_parse_mode: str = "Markdown"

    class Config:
        # ENV-only configuration as per requirements
        env_prefix = ""


settings = Settings()
