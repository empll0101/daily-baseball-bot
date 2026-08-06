from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from ..models import League, Player, TrackingEvent
from .base import DataProvider, ProviderUnavailable


class UnavailableProvider(DataProvider):
    """保留聯盟邊界，避免用不可靠頁面擷取偽裝成正式支援。"""

    def __init__(self, league: League, reason: str):
        self.league = league
        self.reason = reason

    async def search_players(self, query: str) -> list[Player]:
        raise ProviderUnavailable(self.reason)

    async def get_player(self, player_id: str) -> Player:
        return Player(self.league, player_id, player_id)

    async def collect_events(
        self, player_ids: Iterable[str], start: date, end: date
    ) -> list[TrackingEvent]:
        raise ProviderUnavailable(self.reason)

    async def daily_summary(self, player: Player, start: date, end: date) -> str:
        raise ProviderUnavailable(self.reason)

