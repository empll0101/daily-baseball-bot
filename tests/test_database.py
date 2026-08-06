import asyncio
from datetime import UTC, datetime

from tracker.database import Database
from tracker.models import EventKind, League, Player, TrackingEvent


def test_subscription_limit_primitives_and_delivery_dedup(tmp_path):
    asyncio.run(_subscription_scenario(tmp_path))


async def _subscription_scenario(tmp_path):
    database = Database(tmp_path / "tracker.db")
    await database.initialize()
    player = Player(League.MLB, "123", "Test Player", "Test Team", "SS")

    assert await database.add_subscription(42, player, "測試球員") is True
    assert await database.add_subscription(42, player, "測試球員") is False
    items = await database.subscriptions(42)
    assert len(items) == 1
    assert items[0].display_name == "測試球員"

    event = TrackingEvent(
        key="MLB:1:PA:1:123",
        league=League.MLB,
        game_id="1",
        player_id="123",
        kind=EventKind.PLATE_APPEARANCE,
        occurred_at=datetime.now(UTC),
        title="一局上",
        body="安打",
        game_date="2026-07-27",
    )
    await database.store_event(event)
    assert await database.claim_delivery(42, event.key) is True
    assert await database.claim_delivery(42, event.key) is False
    await database.release_delivery(42, event.key)
    assert await database.claim_delivery(42, event.key) is True


def test_remove_subscription(tmp_path):
    asyncio.run(_remove_scenario(tmp_path))


async def _remove_scenario(tmp_path):
    database = Database(tmp_path / "tracker.db")
    await database.initialize()
    player = Player(League.NPB, "npb-7", "Player")
    await database.add_subscription(1, player, "球員")
    assert await database.remove_subscription(1, League.NPB, "npb-7") is True
    assert await database.subscriptions(1) == []
