from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import aiohttp

from ..models import EventKind, League, Player, TrackingEvent
from .base import DataProvider, ProviderUnavailable


class MlbProvider(DataProvider):
    league = League.MLB
    base_url = "https://statsapi.mlb.com/api/v1"

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def _get(self, path: str, **params: object) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with self.session.get(url, params=params) as response:
                    response.raise_for_status()
                    return await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(1 + attempt * 2)
        raise ProviderUnavailable(f"MLB Stats API 暫時無法使用：{last_error}") from last_error

    async def search_players(self, query: str) -> list[Player]:
        data = await self._get(
            "people/search", names=query, sportIds=1, hydrate="currentTeam"
        )
        return [self._player(person) for person in data.get("people", [])[:10]]

    async def get_player(self, player_id: str) -> Player:
        data = await self._get(f"people/{player_id}", hydrate="currentTeam")
        people = data.get("people", [])
        if not people:
            raise ValueError(f"找不到 MLB 球員 ID {player_id}")
        return self._player(people[0])

    @staticmethod
    def _player(person: dict[str, Any]) -> Player:
        return Player(
            League.MLB,
            str(person["id"]),
            person.get("fullName", str(person["id"])),
            person.get("currentTeam", {}).get("name", ""),
            person.get("primaryPosition", {}).get("abbreviation", ""),
        )

    async def collect_events(
        self, player_ids: Iterable[str], start: date, end: date
    ) -> list[TrackingEvent]:
        tracked = {str(value) for value in player_ids}
        if not tracked:
            return []
        schedule = await self._get(
            "schedule",
            sportId=1,
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            gameTypes="R,F,D,L,W",
        )
        game_ids = [
            str(game["gamePk"])
            for day in schedule.get("dates", [])
            for game in day.get("games", [])
            if game.get("status", {}).get("abstractGameState") in {"Live", "Final"}
        ]
        feeds = await asyncio.gather(
            *(self._get(f"https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live") for game_id in game_ids),
            return_exceptions=True,
        )
        events: list[TrackingEvent] = []
        failed_games: list[str] = []
        for game_id, feed in zip(game_ids, feeds, strict=True):
            if isinstance(feed, Exception):
                failed_games.append(game_id)
                logging.getLogger(__name__).warning(
                    "MLB 比賽 %s feed 取得失敗（下一輪會重試）：%s", game_id, feed
                )
                continue
            events.extend(self._parse_game(feed, tracked, game_id))
        if game_ids and len(failed_games) == len(game_ids):
            raise ProviderUnavailable(
                f"MLB 所有比賽 feed 暫時無法取得（{len(failed_games)} 場），下一輪會重試。"
            )
        final_player_ids = {
            event.player_id for event in events if event.kind == EventKind.GAME_FINAL
        }
        if final_player_ids:
            stats_results = await asyncio.gather(
                *(self._season_stats(player_id, end.year) for player_id in final_player_ids),
                return_exceptions=True,
            )
            season_by_player = {
                player_id: stats
                for player_id, stats in zip(final_player_ids, stats_results, strict=True)
                if isinstance(stats, str)
            }
            events = [
                replace(
                    event,
                    body=f"{event.body}\n\n**球季累計**\n{season_by_player[event.player_id]}",
                )
                if event.kind == EventKind.GAME_FINAL
                and event.player_id in season_by_player
                else event
                for event in events
            ]
        events.sort(key=lambda event: event.occurred_at)
        return events

    def _parse_game(
        self, feed: dict[str, Any], tracked: set[str], game_id: str
    ) -> list[TrackingEvent]:
        game_data = feed.get("gameData", {})
        live = feed.get("liveData", {})
        plays = live.get("plays", {}).get("allPlays", [])
        game_date = game_data.get("datetime", {}).get("officialDate", "")
        default_time = _parse_time(game_data.get("datetime", {}).get("dateTime"))
        result: list[TrackingEvent] = []

        for play in plays:
            matchup = play.get("matchup", {})
            batter_id = str(matchup.get("batter", {}).get("id", ""))
            pitcher_id = str(matchup.get("pitcher", {}).get("id", ""))
            about = play.get("about", {})
            play_result = play.get("result", {})
            ended = bool(about.get("isComplete", play_result.get("event")))
            if batter_id in tracked and ended:
                index = about.get("atBatIndex", play.get("atBatIndex", 0))
                inning = about.get("inning", "?")
                half = "上" if about.get("halfInning") == "top" else "下"
                event_name = play_result.get("event", "打席結束")
                description = play_result.get("description", "資料來源未提供敘述")
                hit_info = []
                for event in play.get("playEvents", []):
                    if "hitData" in event:
                        hit_data = event["hitData"]
                        if hit_data.get("launchSpeed") is not None:
                            hit_info.append(f"初速: {hit_data['launchSpeed']} mph")
                        if hit_data.get("launchAngle") is not None:
                            hit_info.append(f"仰角: {hit_data['launchAngle']}度")
                        if hit_data.get("totalDistance") is not None:
                            hit_info.append(f"距離: {hit_data['totalDistance']} ft")
                        break
                if hit_info:
                    description += f"\n📊 {' / '.join(hit_info)}"
                result.append(
                    TrackingEvent(
                        key=f"MLB:{game_id}:PA:{index}:{batter_id}",
                        league=League.MLB,
                        game_id=game_id,
                        player_id=batter_id,
                        kind=EventKind.PLATE_APPEARANCE,
                        occurred_at=_play_time(play, default_time),
                        title=f"第 {inning} 局{half}｜{event_name}",
                        body=description,
                        game_date=game_date,
                    )
                )

        pitching_groups: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
        for play in plays:
            matchup = play.get("matchup", {})
            pitcher_id = str(matchup.get("pitcher", {}).get("id", ""))
            about = play.get("about", {})
            inning = int(about.get("inning", 0) or 0)
            half = about.get("halfInning", "")
            if pitcher_id in tracked and inning and _half_inning_complete(feed, inning, half, pitcher_id):
                pitching_groups[(pitcher_id, inning, half)].append(play)

        for (pitcher_id, inning, half), inning_plays in pitching_groups.items():
            outs = hits = runs = walks = strikeouts = pitches = 0
            for play in inning_plays:
                event_type = play.get("result", {}).get("eventType", "")
                outs += int(play.get("count", {}).get("outs", 0)) - int(
                    play.get("about", {}).get("startOuts", 0)
                )
                hits += int(event_type in {"single", "double", "triple", "home_run"})
                walks += int(event_type in {"walk", "intent_walk"})
                strikeouts += int(event_type in {"strikeout", "strikeout_double_play"})
                for runner in play.get("runners", []):
                    if runner.get("movement", {}).get("end") == "score":
                        runs += 1
                pitches += sum(
                    1 for item in play.get("playEvents", []) if item.get("isPitch")
                )
            half_zh = "上" if half == "top" else "下"
            result.append(
                TrackingEvent(
                    key=f"MLB:{game_id}:IP:{inning}:{half}:{pitcher_id}",
                    league=League.MLB,
                    game_id=game_id,
                    player_id=pitcher_id,
                    kind=EventKind.PITCHING_INNING,
                    occurred_at=max((_play_time(p, default_time) for p in inning_plays)),
                    title=f"第 {inning} 局{half_zh}投球結束",
                    body=(
                        f"局內：{outs} 出局、{hits} 被安打、{runs} 失分、"
                        f"{walks} 保送、{strikeouts} 三振、{pitches} 球"
                    ),
                    game_date=game_date,
                )
            )

        if game_data.get("status", {}).get("abstractGameState") == "Final":
            final_time = max((_play_time(play, default_time) for play in plays), default=default_time)
            result.extend(self._final_events(feed, tracked, game_id, game_date, final_time))
        return result

    def _final_events(
        self,
        feed: dict[str, Any],
        tracked: set[str],
        game_id: str,
        game_date: str,
        occurred_at: datetime,
    ) -> list[TrackingEvent]:
        boxes = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
        result: list[TrackingEvent] = []
        for side in ("away", "home"):
            players = boxes.get(side, {}).get("players", {})
            for entry in players.values():
                player_id = str(entry.get("person", {}).get("id", ""))
                if player_id not in tracked:
                    continue
                stats = entry.get("stats", {})
                sections: list[str] = []
                batting = stats.get("batting", {})
                pitching = stats.get("pitching", {})
                if int(batting.get("plateAppearances", 0) or 0):
                    sections.append(_format_batting(batting))
                if pitching and (pitching.get("inningsPitched") or pitching.get("numberOfPitches")):
                    sections.append(_format_pitching(pitching))
                if not sections:
                    continue
                result.append(
                    TrackingEvent(
                        key=f"MLB:{game_id}:FINAL:{player_id}",
                        league=League.MLB,
                        game_id=game_id,
                        player_id=player_id,
                        kind=EventKind.GAME_FINAL,
                        occurred_at=occurred_at,
                        title="終場成績",
                        body="\n".join(sections),
                        game_date=game_date,
                    )
                )
        return result

    async def daily_summary(self, player: Player, start: date, end: date) -> str:
        events = await self.collect_events([player.external_id], start, end)
        finals = [event for event in events if event.kind == EventKind.GAME_FINAL]
        season = await self._season_stats(player.external_id, end.year)
        if finals:
            games = "\n\n".join(f"**{event.game_date}**\n{event.body}" for event in finals)
        else:
            games = "這段期間沒有可用的出賽紀錄。"
        # collect_events 的終場事件已附球季累計，摘要避免重複顯示。
        cleaned_games = games.replace(f"\n\n**球季累計**\n{season}", "")
        return f"{cleaned_games}\n\n**球季累計**\n{season}"

    async def _season_stats(self, player_id: str, season: int) -> str:
        data = await self._get(
            f"people/{player_id}/stats",
            stats="season",
            group="hitting,pitching",
            season=season,
        )
        sections: list[str] = []
        for group in data.get("stats", []):
            splits = group.get("splits", [])
            if not splits:
                continue
            stat = splits[0].get("stat", {})
            group_name = group.get("group", {}).get("displayName", "")
            if group_name == "hitting":
                sections.append(
                    "打者：出賽 {gamesPlayed}｜打席 {plateAppearances}｜AVG {avg}｜"
                    "OBP {obp}｜SLG {slg}｜OPS {ops}".format_map(
                        defaultdict(lambda: "-", stat)
                    )
                )
            elif group_name == "pitching":
                sections.append(
                    "投手：出賽 {gamesPlayed}｜先發 {gamesStarted}｜{inningsPitched} 局｜"
                    "{wins}-{losses}｜中繼 {holds}｜救援 {saves}｜ERA {era}｜"
                    "WHIP {whip}".format_map(
                        defaultdict(lambda: "-", stat)
                    )
                )
        return "\n".join(sections) if sections else "資料來源未提供"


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _play_time(play: dict[str, Any], fallback: datetime) -> datetime:
    about = play.get("about", {})
    return _parse_time(about.get("endTime") or about.get("startTime")) if (
        about.get("endTime") or about.get("startTime")
    ) else fallback


def _half_inning_complete(feed: dict[str, Any], inning: int, half: str, pitcher_id: str) -> bool:
    linescore = feed.get("liveData", {}).get("linescore", {})
    current = int(linescore.get("currentInning", 0) or 0)
    current_half = linescore.get("inningHalf", "").lower()
    if current > inning:
        return True
    if current < inning:
        return False
    if half == "top" and current_half in {"bottom", "end"}:
        return True
    if half == current_half:
        current_pitcher_id = str(linescore.get("defense", {}).get("pitcher", {}).get("id", ""))
        if current_pitcher_id and current_pitcher_id != pitcher_id:
            return True
    status = feed.get("gameData", {}).get("status", {}).get("abstractGameState")
    return status == "Final"


def _format_batting(stat: dict[str, Any]) -> str:
    return (
        "打者：{atBats} 打數、{plateAppearances} 打席、{hits} 安打、"
        "{strikeOuts} 三振、{baseOnBalls} 保送、{doubles} 二壘打、"
        "{triples} 三壘打、{homeRuns} 全壘打、{runs} 得分、"
        "{rbi} 打點、{stolenBases} 盜壘"
    ).format_map(defaultdict(lambda: 0, stat))


def _format_pitching(stat: dict[str, Any]) -> str:
    return (
        "投手：{inningsPitched} 局、{hits} 被安打、{runs} 失分、"
        "{earnedRuns} 自責分、{baseOnBalls} 保送、{strikeOuts} 三振、"
        "{numberOfPitches} 球"
    ).format_map(defaultdict(lambda: 0, stat))
