from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from ..models import EventKind, League, Player, TrackingEvent
from .base import DataProvider, ProviderUnavailable

log = logging.getLogger(__name__)

# 中文譯名對照表（方便臺灣使用者直接搜尋）
KBO_NAME_ALIASES: dict[str, str] = {
    "王彥程": "왕옌청",
    "古林睿煬": "구린루이양",
    "林安可": "린안커",
    "潘文輝": "판원후이",
    "陳睦衡": "천무헝",
    "孫易磊": "쑨이레이",
}

# 韓文字速報詞彙翻譯字典
KBO_REPLACE_MAP: list[tuple[str, str]] = [
    ("삼진 아웃", "三振出局"),
    ("헛스윙 삼진", "揮棒落空三振"),
    ("루킹 삼진", "站著不動被三振"),
    ("솔로홈런", "陽春全壘打"),
    ("투런홈런", "兩分全壘打"),
    ("쓰리런홈런", "三分全壘打"),
    ("만루홈런", "滿貫全壘打"),
    ("홈런", "全壘打"),
    ("1루타", "一壘安打"),
    ("2루타", "二壘安打"),
    ("3루타", "三壘安打"),
    ("안타", "安打"),
    ("볼넷", "四壞保送"),
    ("고의4구", "故意四壞保送"),
    ("4구", "四壞保送"),
    ("사구", "觸身球"),
    ("몸에 맞는 볼", "觸身球"),
    ("땅볼 아웃", "滾地球出局"),
    ("땅볼", "滾地球"),
    ("파울플라이", "界外飛球"),
    ("플라이 아웃", "飛球出局"),
    ("플라이", "飛球"),
    ("직선타", "平飛球"),
    ("병살타", "雙殺打"),
    ("희생플라이", "高飛犧牲打"),
    ("희생번트", "犧牲觸擊"),
    ("번트", "觸擊"),
    ("도루자", "盜壘出局"),
    ("도루", "盜壘"),
    ("폭투", "暴投"),
    ("포일", "捕逸"),
    ("실책", "失誤"),
    ("야수선택", "野手選擇"),
    ("좌전", "左外野方向"),
    ("우전", "右外野方向"),
    ("중전", "中外野方向"),
    ("내야", "內野"),
    ("삼진", "三振"),
    ("우익수", "右外野手"),
    ("좌익수", "左外野手"),
    ("중견수", "中外野手"),
    ("1루수", "一壘手"),
    ("2루수", "二壘手"),
    ("3루수", "三壘手"),
    ("유격수", "游擊手"),
    ("투수", "投手"),
    ("포수", "捕手"),
]


class KboProvider(DataProvider):
    """KBO 韓國職棒資料源（結合 Naver Sports API 與 KBO 官方網站）。"""

    league = League.KBO
    naver_api_base = "https://api-gw.sports.naver.com"
    kbo_official_base = "https://www.koreabaseball.com"

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def _get_json(self, url: str) -> dict[str, Any]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://m.sports.naver.com/kbaseball",
            "Origin": "https://m.sports.naver.com",
        }
        last_error = None
        for attempt in range(3):
            try:
                async with self.session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    return await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(1.0 * (attempt + 1))
        raise ProviderUnavailable(f"Naver KBO API 無法使用：{last_error}") from last_error

    async def _get_html(self, url: str) -> BeautifulSoup:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        last_error = None
        for attempt in range(3):
            try:
                async with self.session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    html = await response.text()
                    return BeautifulSoup(html, "html.parser")
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(1.0 * (attempt + 1))
        raise ProviderUnavailable(f"KBO 官方網站無法使用：{last_error}") from last_error

    async def search_players(self, query: str) -> list[Player]:
        query_str = query.strip()
        search_term = KBO_NAME_ALIASES.get(query_str, query_str)
        encoded = urllib.parse.quote(search_term)
        url = f"{self.kbo_official_base}/Player/Search.aspx?searchWord={encoded}"
        soup = await self._get_html(url)
        players: list[Player] = []
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
            if "선수명" not in headers or "등번호" not in headers:
                continue
            for row in rows[1:]:
                link = row.select_one('a[href*="playerId="]')
                if not link:
                    continue
                match = re.search(r"playerId=(\d+)", link.get("href", ""))
                if not match:
                    continue
                player_id = match.group(1)
                cols = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
                data = dict(zip(headers, cols))
                name = data.get("선수명", link.get_text(strip=True))
                team = data.get("팀명", "")
                pos = data.get("포지션", "")
                players.append(Player(League.KBO, player_id, name, team, pos))
        return players[:10]

    async def get_player(self, player_id: str) -> Player:
        # 查詢投手或打者基本資料
        for sub in ["PitcherDetail", "HitterDetail"]:
            url = f"{self.kbo_official_base}/Record/Player/{sub}/Basic.aspx?playerId={player_id}"
            try:
                soup = await self._get_html(url)
                text = soup.get_text(" ", strip=True)
                name_match = re.search(r"선수명\s*:\s*([^\s]+)", text)
                team_match = re.search(r"([가-힣A-Za-z]+)\s*(?:이글스|트윈스|라이온즈|베어스|랜더스|타이거즈|다이노스|위즈|자이언츠|히어로즈)", text)
                pos_match = re.search(r"포지션\s*:\s*([^\s]+)", text)
                if name_match:
                    name = name_match.group(1)
                    team = team_match.group(0) if team_match else ""
                    pos = pos_match.group(1) if pos_match else ""
                    return Player(League.KBO, player_id, name, team, pos)
            except Exception:
                continue
        return Player(League.KBO, player_id, f"KBO球員 {player_id}")

    async def collect_events(
        self, player_ids: Iterable[str], start: date, end: date
    ) -> list[TrackingEvent]:
        tracked = {str(pid) for pid in player_ids}
        if not tracked:
            return []

        # 查詢 Naver Sports KBO 賽程
        schedule_url = (
            f"{self.naver_api_base}/schedule/games?"
            f"upperCategoryId=kbaseball&category=kbo&fromDate={start.isoformat()}&toDate={end.isoformat()}"
        )
        data = await self._get_json(schedule_url)
        games_list = (data.get("result") or {}).get("games") or []
        game_ids = [
            g.get("gameId")
            for g in games_list
            if g.get("gameId") and ("KBO" in g.get("gameId", "") or g.get("categoryName") == "KBO")
        ]

        if not game_ids:
            return []

        # 併發抓取 relay 與 record
        tasks = []
        for gid in game_ids:
            tasks.append(self._get_json(f"{self.naver_api_base}/schedule/games/{gid}/relay"))
            tasks.append(self._get_json(f"{self.naver_api_base}/schedule/games/{gid}/record"))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        events: list[TrackingEvent] = []

        for i, gid in enumerate(game_ids):
            relay_data = results[i * 2]
            record_data = results[i * 2 + 1]

            # 1. 解析打席與投球即時文字速報
            if isinstance(relay_data, dict):
                res = relay_data.get("result") or {}
                text_relay_data = res.get("textRelayData") or {}
                text_relays = text_relay_data.get("textRelays") or []
                if text_relays:
                    events.extend(self._parse_relays(text_relays, tracked, gid))

            # 2. 解析終場攻守紀錄表
            if isinstance(record_data, dict):
                res = record_data.get("result") or {}
                rec = res.get("recordData") or {}
                if rec:
                    events.extend(self._parse_record(rec, tracked, gid))

        events.sort(key=lambda e: e.occurred_at)

        final_player_ids = {
            event.player_id for event in events if event.kind == EventKind.GAME_FINAL
        }
        if final_player_ids:
            stats_results = await asyncio.gather(
                *(self._season_stats(player_id) for player_id in final_player_ids),
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

        return events

    def _parse_relays(
        self, relays: list[dict[str, Any]], tracked: set[str], game_id: str
    ) -> list[TrackingEvent]:
        events: list[TrackingEvent] = []
        for item in relays:
            text = item.get("text", "")
            state = item.get("currentGameState") or {}
            players_info = item.get("currentPlayersInfo") or {}
            seqno = item.get("seqno", 0)

            batter_id = str(state.get("batter", ""))
            pitcher_id = str(state.get("pitcher", ""))

            # 1. 打席事件
            if batter_id in tracked and text and ":" in text:
                # 只有當該文字帶有打擊結果（非純換人或純投球）
                tw_text = _translate_kbo(text)
                key = f"KBO:{game_id}:PA:{seqno}:{batter_id}"
                events.append(
                    TrackingEvent(
                        key=key,
                        league=League.KBO,
                        game_id=game_id,
                        player_id=batter_id,
                        kind=EventKind.PLATE_APPEARANCE,
                        occurred_at=datetime.now(UTC),
                        title="打席結束",
                        body=tw_text,
                        game_date=date.today().isoformat(),
                    )
                )

            # 2. 投手即時數據更新
            if pitcher_id in tracked:
                for side in ["home", "away"]:
                    p_info = players_info.get(side) or {}
                    if p_info.get("playerType") == "pitcher":
                        curr_stats = p_info.get("currentGamePlayerStats") or {}
                        inn = curr_stats.get("inn")
                        if inn:
                            kk = curr_stats.get("kk", 0)
                            bb = curr_stats.get("bb", 0)
                            hit = curr_stats.get("hit", 0)
                            run = curr_stats.get("run", 0)
                            balls = (curr_stats.get("strikeCount", 0) or 0) + (curr_stats.get("ballCount", 0) or 0)
                            body = (
                                f"目前局內/累計成績：{inn} 局、{hit} 安打、{run} 失分、"
                                f"{bb} 保送、{kk} 三振、{balls} 球"
                            )
                            key = f"KBO:{game_id}:IP:{pitcher_id}:{inn}:{balls}"
                            events.append(
                                TrackingEvent(
                                    key=key,
                                    league=League.KBO,
                                    game_id=game_id,
                                    player_id=pitcher_id,
                                    kind=EventKind.PITCHING_INNING,
                                    occurred_at=datetime.now(UTC),
                                    title="投球成績更新",
                                    body=body,
                                    game_date=date.today().isoformat(),
                                )
                            )
        return events

    def _parse_record(
        self, rec: dict[str, Any], tracked: set[str], game_id: str
    ) -> list[TrackingEvent]:
        events: list[TrackingEvent] = []
        # 檢查是否為終場
        is_final = False
        game_info = rec.get("gameInfo") or {}
        if game_info.get("status") in {"RESULT", "END", "CANCEL"}:
            is_final = True
        elif rec.get("pitchingResult") or rec.get("scoreBoard"):
            is_final = True

        if not is_final:
            return []

        batters_box = rec.get("battersBoxscore") or {}
        pitchers_box = rec.get("pitchersBoxscore") or {}

        for side in ["away", "home"]:
            # 打者
            for b in (batters_box.get(side) or []):
                pcode = str(b.get("playerCode", ""))
                if pcode in tracked:
                    ab = b.get("ab", 0)
                    hit = b.get("hit", 0)
                    hr = b.get("hr", 0)
                    run = b.get("run", 0)
                    rbi = b.get("rbi", 0)
                    bb = b.get("bb", 0)
                    kk = b.get("kk", 0)
                    sb = b.get("sb", 0)
                    body = (
                        f"打者：{ab} 打數、{hit} 安打、{hr} 全壘打、{run} 得分、"
                        f"{rbi} 打點、{bb} 保送、{kk} 三振、{sb} 盜壘"
                    )
                    key = f"KBO:{game_id}:FINAL:{pcode}"
                    events.append(
                        TrackingEvent(
                            key=key,
                            league=League.KBO,
                            game_id=game_id,
                            player_id=pcode,
                            kind=EventKind.GAME_FINAL,
                            occurred_at=datetime.now(UTC),
                            title="終場成績",
                            body=body,
                            game_date=date.today().isoformat(),
                        )
                    )

            # 投手
            for p in (pitchers_box.get(side) or []):
                pcode = str(p.get("pcode", p.get("playerCode", "")))
                if pcode in tracked:
                    inn = p.get("inn", "0")
                    hit = p.get("hit", 0)
                    r = p.get("r", 0)
                    er = p.get("er", 0)
                    bb = p.get("bb", 0)
                    kk = p.get("kk", 0)
                    bf = p.get("bf", 0)
                    wls = p.get("wls", "")
                    wls_text = {
                        "승": "（勝投）",
                        "패": "（敗投）",
                        "세": "（救援成功）",
                        "홀": "（中繼成功）",
                    }.get(wls, "")
                    body = (
                        f"投手：{inn} 局、{hit} 被安打、{r} 失分、{er} 自責分、"
                        f"{bb} 保送、{kk} 三振、{bf} 球{wls_text}"
                    )
                    key = f"KBO:{game_id}:FINAL:{pcode}"
                    events.append(
                        TrackingEvent(
                            key=key,
                            league=League.KBO,
                            game_id=game_id,
                            player_id=pcode,
                            kind=EventKind.GAME_FINAL,
                            occurred_at=datetime.now(UTC),
                            title="終場成績",
                            body=body,
                            game_date=date.today().isoformat(),
                        )
                    )
        return events

    async def daily_summary(self, player: Player, start: date, end: date) -> str:
        events = await self.collect_events([player.external_id], start, end)
        finals = [event.body for event in events if event.kind == EventKind.GAME_FINAL]
        season = await self._season_stats(player.external_id)
        if finals:
            games = "\n\n".join(finals)
        else:
            games = "這段期間沒有可用的出賽紀錄。"
        cleaned_games = games.replace(f"\n\n**球季累計**\n{season}", "")
        return f"{cleaned_games}\n\n**球季累計**\n{season}"

    async def _season_stats(self, player_id: str) -> str:
        # 嘗試從 KBO 官方網站爬取賽季成績
        try:
            # 先試投手
            url_pitcher = f"{self.kbo_official_base}/Record/Player/PitcherDetail/Basic.aspx?playerId={player_id}"
            soup = await self._get_html(url_pitcher)
            tables = soup.find_all("table")
            if tables:
                t0_rows = tables[0].find_all("tr")
                if len(t0_rows) > 1:
                    h0 = [c.get_text(" ", strip=True) for c in t0_rows[0].find_all(["th", "td"])]
                    v0 = [c.get_text(" ", strip=True) for c in t0_rows[1].find_all(["th", "td"])]
                    s0 = dict(zip(h0, v0))
                    if "ERA" in s0 and "IP" in s0:
                        s1: dict[str, str] = {}
                        if len(tables) > 1:
                            t1_rows = tables[1].find_all("tr")
                            if len(t1_rows) > 1:
                                h1 = [c.get_text(" ", strip=True) for c in t1_rows[0].find_all(["th", "td"])]
                                v1 = [c.get_text(" ", strip=True) for c in t1_rows[1].find_all(["th", "td"])]
                                s1 = dict(zip(h1, v1))
                        return (
                            f"投手：出賽 {s0.get('G', '-')}｜{s0.get('IP', '-')} 局｜"
                            f"{s0.get('W', '-')}勝-{s0.get('L', '-')}敗｜"
                            f"中繼 {s0.get('HLD', '-')}｜救援 {s0.get('SV', '-')}｜"
                            f"ERA {s0.get('ERA', '-')}｜WHIP {s1.get('WHIP', '-')}"
                        )
            # 再試打者
            url_hitter = f"{self.kbo_official_base}/Record/Player/HitterDetail/Basic.aspx?playerId={player_id}"
            soup = await self._get_html(url_hitter)
            tables = soup.find_all("table")
            if tables:
                t0_rows = tables[0].find_all("tr")
                if len(t0_rows) > 1:
                    h0 = [c.get_text(" ", strip=True) for c in t0_rows[0].find_all(["th", "td"])]
                    v0 = [c.get_text(" ", strip=True) for c in t0_rows[1].find_all(["th", "td"])]
                    s0 = dict(zip(h0, v0))
                    if "AVG" in s0 and "PA" in s0:
                        s1 = {}
                        if len(tables) > 1:
                            t1_rows = tables[1].find_all("tr")
                            if len(t1_rows) > 1:
                                h1 = [c.get_text(" ", strip=True) for c in t1_rows[0].find_all(["th", "td"])]
                                v1 = [c.get_text(" ", strip=True) for c in t1_rows[1].find_all(["th", "td"])]
                                s1 = dict(zip(h1, v1))
                        return (
                            f"打者：出賽 {s0.get('G', '-')}｜打席 {s0.get('PA', '-')}｜"
                            f"AVG {s0.get('AVG', '-')}｜OBP {s1.get('OBP', '-')}｜"
                            f"SLG {s1.get('SLG', '-')}｜OPS {s1.get('OPS', '-')}"
                        )
        except Exception as exc:
            log.warning("取得 KBO 球員 %s 累計成績失敗：%s", player_id, exc)
        return "資料來源未提供"


def _translate_kbo(text: str) -> str:
    result = text
    for kr, tw in KBO_REPLACE_MAP:
        result = result.replace(kr, tw)
    return result
