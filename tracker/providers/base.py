from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date

from ..models import League, Player, TrackingEvent


class ProviderUnavailable(RuntimeError):
    pass


class DataProvider(ABC):
    league: League

    @abstractmethod
    async def search_players(self, query: str) -> list[Player]: ...

    @abstractmethod
    async def get_player(self, player_id: str) -> Player: ...

    @abstractmethod
    async def collect_events(
        self, player_ids: Iterable[str], start: date, end: date
    ) -> list[TrackingEvent]: ...

    @abstractmethod
    async def daily_summary(
        self, player: Player, start: date, end: date
    ) -> str: ...

