from __future__ import annotations

import asyncio
import logging

import aiohttp

from .bot import TrackerClient
from .config import Settings
from .database import Database
from .models import League
from .providers import KboProvider, MlbProvider, NpbProvider


async def run() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    database = Database(settings.database_path)
    await database.initialize()
    timeout = aiohttp.ClientTimeout(total=20)
    headers = {"User-Agent": "TaiwanBaseballTracker/0.1 (personal MVP)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        providers = {
            League.MLB: MlbProvider(session),
            League.NPB: NpbProvider(session),
            League.KBO: KboProvider(session),
        }
        client = TrackerClient(settings, database, session, providers)
        await client.start(settings.discord_token)


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass
    except ValueError as exc:
        raise SystemExit(f"設定錯誤：{exc}") from exc
