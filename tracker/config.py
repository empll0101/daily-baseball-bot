from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    database_path: Path
    poll_interval_seconds: int = 120
    daily_summary_hour: int = 23
    daily_summary_minute: int = 0
    max_subscriptions: int = 10
    backfill_days: int = 3
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token or token.startswith("請貼上"):
            raise ValueError("請先在 .env 設定有效的 DISCORD_TOKEN")
        settings = cls(
            discord_token=token,
            database_path=Path(os.getenv("DATABASE_PATH", "data/tracker.db")),
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "120")),
            daily_summary_hour=int(os.getenv("DAILY_SUMMARY_HOUR", "23")),
            daily_summary_minute=int(os.getenv("DAILY_SUMMARY_MINUTE", "0")),
            max_subscriptions=int(os.getenv("MAX_SUBSCRIPTIONS", "10")),
            backfill_days=int(os.getenv("BACKFILL_DAYS", "3")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
        if settings.poll_interval_seconds < 30:
            raise ValueError("POLL_INTERVAL_SECONDS 不可小於 30")
        if not 0 <= settings.daily_summary_hour <= 23:
            raise ValueError("DAILY_SUMMARY_HOUR 必須介於 0 到 23")
        if not 0 <= settings.daily_summary_minute <= 59:
            raise ValueError("DAILY_SUMMARY_MINUTE 必須介於 0 到 59")
        return settings

