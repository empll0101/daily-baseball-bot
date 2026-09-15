import asyncio
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo
from tracker.models import EventKind, League, Player, TrackingEvent
from tracker.providers.mlb import MlbProvider


def test_mlb_daily_summary_time_window(tmp_path):
    asyncio.run(_async_test_mlb_daily_summary())


async def _async_test_mlb_daily_summary():
    # 模擬 2026-08-10 臺灣時間上午 06:52 結束的比賽 (occurred_at: 2026-08-09 22:52 UTC)
    # game_date 在美東官方記錄為 2026-08-09
    game_occurred_utc = datetime(2026, 8, 9, 22, 52, tzinfo=UTC)
    tw_date = game_occurred_utc.astimezone(ZoneInfo("Asia/Taipei")).date()
    assert tw_date == date(2026, 8, 10)

    final_event = TrackingEvent(
        key="MLB:823190:FINAL:694364",
        league=League.MLB,
        game_id="823190",
        player_id="694364",
        kind=EventKind.GAME_FINAL,
        occurred_at=game_occurred_utc,
        title="終場成績",
        body="打者：1 打數、1 安打、1 得分",
        game_date="2026-08-09",
    )

    provider = MlbProvider(session=None)  # type: ignore

    # Mock collect_events and _season_stats
    async def mock_collect(pids, s, e):
        return [final_event]

    async def mock_season(pid, year):
        return "打者：出賽 75｜打席 208｜AVG .267"

    provider.collect_events = mock_collect  # type: ignore
    provider._season_stats = mock_season  # type: ignore

    player = Player(League.MLB, "694364", "李灝宇")
    # 當天晚上 23:00 執行每日彙整（查詢 2026-08-10）
    summary = await provider.daily_summary(player, date(2026, 8, 10), date(2026, 8, 10))

    assert "這段期間沒有可用的出賽紀錄" not in summary
    assert "打者：1 打數、1 安打、1 得分" in summary
    assert "打者：出賽 75" in summary


def test_npb_daily_summary_final_and_in_progress():
    asyncio.run(_async_test_npb_daily_summary())


async def _async_test_npb_daily_summary():
    from tracker.providers.npb import NpbProvider

    provider = NpbProvider(session=None)  # type: ignore

    # 1. 測試當天比賽已結束 (GAME_FINAL)
    final_event = TrackingEvent(
        key="NPB:test:FINAL:2106890",
        league=League.NPB,
        game_id="test",
        player_id="2106890",
        kind=EventKind.GAME_FINAL,
        occurred_at=datetime.now(UTC),
        title="終場成績",
        body="打者：4 打數、2 安打、1 全壘打、1 得分、3 打點、0 保送、1 三振、0 盜壘",
        game_date="2026-08-26",
    )

    async def mock_collect_final(pids, s, e):
        return [final_event]

    async def mock_season(pid):
        return "打者：出賽 50｜打席 180｜AVG .285｜OBP .350｜SLG .450｜OPS .800"

    provider.collect_events = mock_collect_final  # type: ignore
    provider._season_stats = mock_season  # type: ignore

    player = Player(League.NPB, "2106890", "孫易磊")
    summary = await provider.daily_summary(player, date(2026, 8, 26), date(2026, 8, 26))
    assert "4 打數、2 安打、1 全壘打" in summary
    assert "球季累計" in summary
    assert "AVG .285" in summary

    # 2. 測試比賽進行中 (僅有打席事件，尚未結算 GAME_FINAL)
    pa_event = TrackingEvent(
        key="NPB:test:PA:1回表:2106890:123",
        league=League.NPB,
        game_id="test",
        player_id="2106890",
        kind=EventKind.PLATE_APPEARANCE,
        occurred_at=datetime.now(UTC),
        title="一局上｜面對 山本 由伸",
        body="左外野方向安打",
        game_date="2026-08-26",
    )

    async def mock_collect_live(pids, s, e):
        return [pa_event]

    provider.collect_events = mock_collect_live  # type: ignore
    live_summary = await provider.daily_summary(player, date(2026, 8, 26), date(2026, 8, 26))
    assert "本日出賽紀錄" in live_summary
    assert "一局上｜面對 山本 由伸：左外野方向安打" in live_summary
    assert "球季累計" in live_summary

