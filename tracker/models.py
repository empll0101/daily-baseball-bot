from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class League(StrEnum):
    MLB = "MLB"
    NPB = "NPB"
    KBO = "KBO"


class EventKind(StrEnum):
    ON_DECK = "on_deck"
    PLATE_APPEARANCE = "plate_appearance"
    PITCHING_INNING = "pitching_inning"
    PITCHING_EXIT = "pitching_exit"
    GAME_FINAL = "game_final"


@dataclass(frozen=True, slots=True)
class Player:
    league: League
    external_id: str
    canonical_name: str
    team: str = ""
    position: str = ""


@dataclass(frozen=True, slots=True)
class Subscription:
    user_id: int
    player: Player
    display_name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TrackingEvent:
    key: str
    league: League
    game_id: str
    player_id: str
    kind: EventKind
    occurred_at: datetime
    title: str
    body: str
    game_date: str

