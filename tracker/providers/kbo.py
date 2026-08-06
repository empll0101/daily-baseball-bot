from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime

import aiohttp
from bs4 import BeautifulSoup

from ..models import EventKind, League, Player, TrackingEvent
from .base import DataProvider, ProviderUnavailable


class KboProvider(DataProvider):
    """MyKBOStats 公開頁面爬蟲；頁面結構變動時會安全降級。"""
    league = League.KBO
    base_url = "https://mykbostats.com"

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def _html(self, path: str) -> BeautifulSoup:
        try:
            url = path if path.startswith("http") else f"{self.base_url}{path}"
            async with self.session.get(url) as response:
                response.raise_for_status()
                return BeautifulSoup(await response.text(), "html.parser")
        except (aiohttp.ClientError, ValueError) as exc:
            raise ProviderUnavailable(f"MyKBOStats 無法使用：{exc}") from exc

    async def search_players(self, query: str) -> list[Player]:
        raise ProviderUnavailable("MyKBOStats 尚無穩定公開搜尋端點；請以球員頁 URL 中的數字 ID 手動訂閱。")

    async def get_player(self, player_id: str) -> Player:
        soup = await self._html(f"/players/{player_id}")
        heading = soup.find("h1")
        if not heading:
            raise ValueError(f"找不到 KBO 球員 ID {player_id}")
        return Player(League.KBO, player_id, heading.get_text(" ", strip=True))

    async def collect_events(self, player_ids: Iterable[str], start: date, end: date) -> list[TrackingEvent]:
        tracked = set(player_ids)
        home = await self._html("/")
        paths = {a.get("href") for a in home.select('a[href^="/games/"]')}
        events: list[TrackingEvent] = []
        for path in sorted(path for path in paths if path):
            game = await self._html(path)
            game_id = path.split("/")[2].split("-")[0]
            final = "Final" in game.get_text(" ", strip=True)
            for player_id in tracked:
                link = game.select_one(f'a[href^="/players/{player_id}"]')
                if not link:
                    continue
                name = link.get_text(" ", strip=True)
                row = link.find_parent("tr")
                body = row.get_text(" ", strip=True) if row else "本場出賽，資料細節待更新。"
                kind = EventKind.GAME_FINAL if final else EventKind.PITCHING_INNING
                key = f"KBO:{game_id}:{kind.value}:{player_id}:{hashlib.sha1(body.encode()).hexdigest()[:12]}"
                events.append(TrackingEvent(key, League.KBO, game_id, player_id, kind,
                    datetime.now(UTC), "終場成績" if final else "比賽進行中", body,
                    date.today().isoformat()))
        return events

    async def daily_summary(self, player: Player, start: date, end: date) -> str:
        events = await self.collect_events([player.external_id], start, end)
        finals = [event.body for event in events if event.kind == EventKind.GAME_FINAL]
        return "\n".join(finals) if finals else "本日沒有可用的出賽紀錄。"
