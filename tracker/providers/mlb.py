from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from ..models import EventKind, League, Player, TrackingEvent
from .base import DataProvider, ProviderUnavailable

TAIPEI = ZoneInfo("Asia/Taipei")


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

        boxscore = live.get("boxscore", {})
        batting_order_slots = {"top": {}, "bottom": {}}
        for side_name, half_key in [("away", "top"), ("home", "bottom")]:
            team_data = boxscore.get("teams", {}).get(side_name, {})
            for pkey, pdata in team_data.get("players", {}).items():
                bo_str = pdata.get("battingOrder")
                if bo_str and bo_str.isdigit():
                    slot = int(bo_str) // 100
                    if 1 <= slot <= 9:
                        batting_order_slots[half_key][slot] = str(pdata.get("person", {}).get("id", ""))

        for play in plays:
            matchup = play.get("matchup", {})
            batter_id = str(matchup.get("batter", {}).get("id", ""))
            pitcher_id = str(matchup.get("pitcher", {}).get("id", ""))
            pitcher_name = matchup.get("pitcher", {}).get("fullName", "")
            about = play.get("about", {})
            half_inning = about.get("halfInning", "")
            index = about.get("atBatIndex", play.get("atBatIndex", 0))
            inning = about.get("inning", "?")
            half = "上" if half_inning == "top" else "下"

            # 次打者提前預告 (ON_DECK)
            slots = batting_order_slots.get(half_inning, {})
            current_slot = None
            for slot_num, pid in slots.items():
                if pid == batter_id:
                    current_slot = slot_num
                    break

            if current_slot is not None:
                next_slot = (current_slot % 9) + 1
                next_batter_id = slots.get(next_slot)
                if next_batter_id and next_batter_id in tracked:
                    outs = int(about.get("startOuts", 0) or 0)
                    result.append(
                        TrackingEvent(
                            key=f"MLB:{game_id}:ON_DECK:{index}:{next_batter_id}",
                            league=League.MLB,
                            game_id=game_id,
                            player_id=next_batter_id,
                            kind=EventKind.ON_DECK,
                            occurred_at=_play_time(play, default_time) - timedelta(seconds=1),
                            title=f"第 {inning} 局{half}｜即將上場打擊",
                            body=f"目前 {outs} 出局，下一棒即將輪到打擊！",
                            game_date=game_date,
                        )
                    )

            play_result = play.get("result", {})
            ended = bool(about.get("isComplete", play_result.get("event")))
            if batter_id in tracked and ended:
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

                if pitcher_name:
                    pa_title = (
                        f"第 {inning} 局{half}｜面對 {pitcher_name}｜{event_name}"
                        if event_name and event_name != "打席結束"
                        else f"第 {inning} 局{half}｜面對 {pitcher_name}"
                    )
                else:
                    pa_title = f"第 {inning} 局{half}｜{event_name}"

                result.append(
                    TrackingEvent(
                        key=f"MLB:{game_id}:PA:{index}:{batter_id}",
                        league=League.MLB,
                        game_id=game_id,
                        player_id=batter_id,
                        kind=EventKind.PLATE_APPEARANCE,
                        occurred_at=_play_time(play, default_time),
                        title=pa_title,
                        body=description,
                        game_date=game_date,
                    )
                )

        pitching_groups: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
        pitcher_innings: dict[str, list[tuple[int, str]]] = defaultdict(list)
        last_pitcher_in_half: dict[tuple[int, str], str] = {}

        for play in plays:
            matchup = play.get("matchup", {})
            pitcher_id = str(matchup.get("pitcher", {}).get("id", ""))
            about = play.get("about", {})
            inning = int(about.get("inning", 0) or 0)
            half = about.get("halfInning", "")
            if pitcher_id and inning and half:
                last_pitcher_in_half[(inning, half)] = pitcher_id
                if (inning, half) not in pitcher_innings[pitcher_id]:
                    pitcher_innings[pitcher_id].append((inning, half))
            if pitcher_id in tracked and inning and _half_inning_complete(feed, inning, half):
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

        # 投手退場通知（PITCHING_EXIT）
        teams = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
        linescore = feed.get("liveData", {}).get("linescore", {})
        current_pitcher_id = str(linescore.get("defense", {}).get("pitcher", {}).get("id", ""))
        is_final = (game_data.get("status", {}).get("abstractGameState") == "Final")

        for side in ["away", "home"]:
            team_box = teams.get(side, {})
            team_pitchers = [str(pid) for pid in team_box.get("pitchers", [])]
            for pid in tracked:
                if pid in team_pitchers and pid in pitcher_innings:
                    idx = team_pitchers.index(pid)
                    has_subsequent = (idx < len(team_pitchers) - 1)
                    is_replaced = has_subsequent or (current_pitcher_id and current_pitcher_id != pid) or is_final

                    if is_replaced:
                        last_inn, last_half = pitcher_innings[pid][-1]
                        completed = (last_pitcher_in_half.get((last_inn, last_half)) == pid)
                        inn_finished = _half_inning_complete(feed, last_inn, last_half)

                        # 狀況一：完整局數吃完後退場（該半局結束）
                        # 狀況二：非完整局數退場（局中被換），等待該半局結束後通知
                        should_emit_exit = (completed and inn_finished) or (not completed and inn_finished)

                        if should_emit_exit:
                            p_stats = (
                                team_box.get("players", {})
                                .get(f"ID{pid}", {})
                                .get("stats", {})
                                .get("pitching", {})
                            )
                            inn_v = p_stats.get("inningsPitched", "0.0")
                            hit = p_stats.get("hits", 0)
                            run = p_stats.get("runs", 0)
                            er = p_stats.get("earnedRuns")
                            er_str = f"（{er} 責失）" if er is not None else ""
                            bb = p_stats.get("baseOnBalls", 0)
                            kk = p_stats.get("strikeOuts", 0)
                            pitches = p_stats.get("numberOfPitches", 0)
                            body = (
                                f"今日投球成績：{inn_v} 局、{hit} 被安打、{run} 失分{er_str}、"
                                f"{bb} 保送、{kk} 三振、{pitches} 球"
                            )
                            result.append(
                                TrackingEvent(
                                    key=f"MLB:{game_id}:PITCHING_EXIT:{pid}",
                                    league=League.MLB,
                                    game_id=game_id,
                                    player_id=pid,
                                    kind=EventKind.PITCHING_EXIT,
                                    occurred_at=default_time,
                                    title="投球工作結束（退場）",
                                    body=body,
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
        # 涵蓋前一日美東晚場賽事（臺灣時間上午開打）
        query_start = start - timedelta(days=1)
        events = await self.collect_events([player.external_id], query_start, end)
        finals = [
            event for event in events
            if event.kind == EventKind.GAME_FINAL
            and (start <= event.occurred_at.astimezone(TAIPEI).date() <= end or start.isoformat() <= event.game_date <= end.isoformat())
        ]
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


def _half_inning_complete(feed: dict[str, Any], inning: int, half: str, pitcher_id: str | None = None) -> bool:
    linescore = feed.get("liveData", {}).get("linescore", {})
    current = int(linescore.get("currentInning", 0) or 0)
    current_half = linescore.get("inningHalf", "").lower()
    if current > inning:
        return True
    if current < inning:
        return False
    if half == "top" and current_half in {"bottom", "end"}:
        return True
    if half == "bottom" and current_half in {"end"}:
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
