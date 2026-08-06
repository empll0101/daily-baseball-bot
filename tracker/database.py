from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import League, Player, Subscription, TrackingEvent


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS subscriptions (
  user_id INTEGER NOT NULL,
  league TEXT NOT NULL,
  player_id TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  display_name TEXT NOT NULL,
  team TEXT NOT NULL DEFAULT '',
  position TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, league, player_id)
);
CREATE TABLE IF NOT EXISTS deliveries (
  user_id INTEGER NOT NULL,
  event_key TEXT NOT NULL,
  delivered_at TEXT NOT NULL,
  PRIMARY KEY (user_id, event_key)
);
CREATE TABLE IF NOT EXISTS events (
  event_key TEXT PRIMARY KEY,
  league TEXT NOT NULL,
  game_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  game_date TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_player
  ON subscriptions (league, player_id);
CREATE INDEX IF NOT EXISTS idx_events_date ON events (game_date);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    async def add_subscription(
        self, user_id: int, player: Player, display_name: str
    ) -> bool:
        async with self._lock:
            return await asyncio.to_thread(
                self._add_subscription_sync, user_id, player, display_name
            )

    def _add_subscription_sync(
        self, user_id: int, player: Player, display_name: str
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO subscriptions
                (user_id, league, player_id, canonical_name, display_name,
                 team, position, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    player.league.value,
                    player.external_id,
                    player.canonical_name,
                    display_name,
                    player.team,
                    player.position,
                    datetime.now(UTC).isoformat(),
                ),
            )
            return cursor.rowcount == 1

    async def remove_subscription(
        self, user_id: int, league: League, player_id: str
    ) -> bool:
        async with self._lock:
            return await asyncio.to_thread(
                self._remove_subscription_sync, user_id, league, player_id
            )

    def _remove_subscription_sync(
        self, user_id: int, league: League, player_id: str
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE user_id=? AND league=? AND player_id=?",
                (user_id, league.value, player_id),
            )
            return cursor.rowcount == 1

    async def subscriptions(self, user_id: int | None = None) -> list[Subscription]:
        async with self._lock:
            return await asyncio.to_thread(self._subscriptions_sync, user_id)

    def _subscriptions_sync(self, user_id: int | None) -> list[Subscription]:
        sql = "SELECT * FROM subscriptions"
        params: tuple[object, ...] = ()
        if user_id is not None:
            sql += " WHERE user_id=?"
            params = (user_id,)
        sql += " ORDER BY league, display_name"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            Subscription(
                user_id=row["user_id"],
                player=Player(
                    league=League(row["league"]),
                    external_id=row["player_id"],
                    canonical_name=row["canonical_name"],
                    team=row["team"],
                    position=row["position"],
                ),
                display_name=row["display_name"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    async def store_event(self, event: TrackingEvent) -> None:
        async with self._lock:
            await asyncio.to_thread(self._store_event_sync, event)

    def _store_event_sync(self, event: TrackingEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO events
                (event_key, league, game_id, player_id, kind, occurred_at,
                 game_date, title, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.key, event.league.value, event.game_id, event.player_id,
                    event.kind.value, event.occurred_at.isoformat(), event.game_date,
                    event.title, event.body,
                ),
            )

    async def claim_delivery(self, user_id: int, event_key: str) -> bool:
        """原子化取得發送權，避免重複通知。"""
        async with self._lock:
            return await asyncio.to_thread(
                self._claim_delivery_sync, user_id, event_key
            )

    def _claim_delivery_sync(self, user_id: int, event_key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?)",
                (user_id, event_key, datetime.now(UTC).isoformat()),
            )
            return cursor.rowcount == 1

    async def release_delivery(self, user_id: int, event_key: str) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._release_delivery_sync, user_id, event_key
            )

    def _release_delivery_sync(self, user_id: int, event_key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM deliveries WHERE user_id=? AND event_key=?",
                (user_id, event_key),
            )

    async def get_meta(self, key: str) -> str | None:
        async with self._lock:
            return await asyncio.to_thread(self._get_meta_sync, key)

    def _get_meta_sync(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    async def set_meta(self, key: str, value: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._set_meta_sync, key, value)

    def _set_meta_sync(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO metadata VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
