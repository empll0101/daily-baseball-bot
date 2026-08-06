from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime

import aiohttp
from bs4 import BeautifulSoup

from ..models import EventKind, League, Player, TrackingEvent
from .base import DataProvider, ProviderUnavailable
from .npb_dict import INNINGS_MAP, REPLACE_MAP


class NpbProvider(DataProvider):
    """Yahoo! JAPAN NPB 公開賽況頁爬蟲。"""
    league = League.NPB
    base_url = "https://baseball.yahoo.co.jp"

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def _html(self, path: str) -> BeautifulSoup:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        last_exc = None
        for attempt in range(3):
            try:
                async with self.session.get(url) as response:
                    response.raise_for_status()
                    return BeautifulSoup(await response.text(), "html.parser")
            except (aiohttp.ClientError, ValueError) as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(1.0 * (attempt + 1))
        raise ProviderUnavailable(f"Yahoo! JAPAN NPB 無法使用：{last_exc}") from last_exc

    async def search_players(self, query: str) -> list[Player]:
        raise ProviderUnavailable("Yahoo! NPB 搜尋尚未接通；請以球員頁 URL 的數字 ID 手動訂閱。")

    async def get_player(self, player_id: str) -> Player:
        soup = await self._html(f"/npb/player/{player_id}/top")
        heading = soup.find("h1") or soup.find("h2")
        if not heading:
            raise ValueError(f"找不到 NPB 球員 ID {player_id}")
        return Player(League.NPB, player_id, heading.get_text(" ", strip=True))

    async def collect_events(self, player_ids: Iterable[str], start: date, end: date) -> list[TrackingEvent]:
        tracked = set(player_ids)
        if not tracked:
            return []

        home = await self._html("/npb/")
        paths = {a.get("href") for a in home.select('a[href*="/npb/game/"][href$="/index"]')}
        events: list[TrackingEvent] = []
        for path in sorted(path for path in paths if path):
            match = re.search(r"game/(\d+)", path)
            if not match:
                continue
            game_id = match.group(1)
            try:
                game = await self._html(path)
            except ProviderUnavailable:
                continue
            final = "試合終了" in game.get_text(" ", strip=True)

            text_html, stats_html = await asyncio.gather(
                self._html(f"/npb/game/{game_id}/text"),
                self._html(f"/npb/game/{game_id}/stats"),
                return_exceptions=True
            )

            # 1. PLATE_APPEARANCE (from text_html)
            if not isinstance(text_html, Exception):
                for inning_section in text_html.select("section.bb-liveText"):
                    inning_title = inning_section.select_one("h1.bb-liveText__inning")
                    raw_inning = inning_title.get_text(" ", strip=True) if inning_title else "未知局數"
                    inning_str = INNINGS_MAP.get(raw_inning, raw_inning)
                    
                    for item in inning_section.select("li.bb-liveText__item"):
                        player_link = item.select_one("a.bb-liveText__player")
                        if not player_link:
                            continue
                        match = re.search(r"/npb/player/(\d+)/", player_link.get("href", ""))
                        if not match:
                            continue
                        batter_id = match.group(1)
                        if batter_id in tracked:
                            summaries = item.select("p.bb-liveText__summary span.bb-liveText__state")
                            if summaries:
                                raw_outcome = summaries[-1].get_text(" ", strip=True)
                                outcome = raw_outcome
                                for jp_text, tw_text in REPLACE_MAP:
                                    outcome = outcome.replace(jp_text, tw_text)
                                key = f"NPB:{game_id}:PA:{raw_inning}:{batter_id}:{hashlib.sha1(raw_outcome.encode()).hexdigest()[:12]}"
                                events.append(TrackingEvent(
                                    key=key,
                                    league=League.NPB,
                                    game_id=game_id,
                                    player_id=batter_id,
                                    kind=EventKind.PLATE_APPEARANCE,
                                    occurred_at=datetime.now(UTC),
                                    title=f"{inning_str}｜打席結束",
                                    body=outcome,
                                    game_date=date.today().isoformat()
                                ))

            # 2. PITCHING_INNING (from stats_html)
            if not isinstance(stats_html, Exception):
                for table in stats_html.select("table.bb-scoreTable"):
                    rows = table.find_all("tr")
                    if not rows: continue
                    headers = [th.get_text(" ", strip=True) for th in rows[0].find_all(["th", "td"])]
                    if "投球回" in headers and "投手" in headers:
                        for row in rows[1:]:
                            player_link = row.select_one("a")
                            if not player_link: continue
                            match = re.search(r"/npb/player/(\d+)/", player_link.get("href", ""))
                            if not match: continue
                            pitcher_id = match.group(1)
                            if pitcher_id in tracked:
                                cols = [td.get_text(" ", strip=True) for td in row.find_all(["th", "td"])]
                                stats_dict = dict(zip(headers, cols))
                                ip_str = stats_dict.get("投球回", "0")
                                if ip_str != "0" and ip_str != "-":
                                    outs = 0
                                    if "1/3" in ip_str:
                                        outs = int(ip_str.split()[0]) * 3 + 1 if ip_str.split()[0].isdigit() else 1
                                    elif "2/3" in ip_str:
                                        outs = int(ip_str.split()[0]) * 3 + 2 if ip_str.split()[0].isdigit() else 2
                                    else:
                                        try:
                                            outs = int(ip_str) * 3
                                        except ValueError:
                                            pass
                                    
                                    if outs > 0:
                                        body = (f"目前局內/累計成績：{ip_str} 局、{stats_dict.get('被安打', '0')} 安打、"
                                                f"{stats_dict.get('失点', '0')} 失分、{stats_dict.get('与四死球', '0')} 保送、"
                                                f"{stats_dict.get('奪三振', '0')} 三振、{stats_dict.get('投球数', '0')} 球")
                                        key = f"NPB:{game_id}:IP:{pitcher_id}:{outs}"
                                        events.append(TrackingEvent(
                                            key=key,
                                            league=League.NPB,
                                            game_id=game_id,
                                            player_id=pitcher_id,
                                            kind=EventKind.PITCHING_INNING,
                                            occurred_at=datetime.now(UTC),
                                            title="投球成績更新",
                                            body=body,
                                            game_date=date.today().isoformat()
                                        ))

            # 3. GAME_FINAL
            if final:
                for player_id in tracked:
                    played = False
                    if not isinstance(stats_html, Exception):
                        for link in stats_html.select(f'a[href*="/npb/player/{player_id}/"]'):
                            played = True
                            break
                    if played:
                        key = f"NPB:{game_id}:FINAL:{player_id}"
                        events.append(TrackingEvent(
                            key=key,
                            league=League.NPB,
                            game_id=game_id,
                            player_id=player_id,
                            kind=EventKind.GAME_FINAL,
                            occurred_at=datetime.now(UTC),
                            title="終場成績",
                            body="比賽結束，本日成績請參考球季累計與各打席。",
                            game_date=date.today().isoformat()
                        ))
                        
        return events

    async def daily_summary(self, player: Player, start: date, end: date) -> str:
        events = await self.collect_events([player.external_id], start, end)
        finals = [event.body for event in events if event.kind == EventKind.GAME_FINAL]
        games = "\n".join(finals) if finals else "本日沒有可用的出賽紀錄。"
        return f"{games}\n\n**球季累計**\n{await self._season_stats(player.external_id)}"

    async def _season_stats(self, player_id: str) -> str:
        soup = await self._html(f"/npb/player/{player_id}/top")
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
            if "打率" in headers and "試合" in headers:
                values = [cell.get_text(" ", strip=True) for cell in rows[1].find_all(["th", "td"])] if len(rows) > 1 else []
                second_headers = [cell.get_text(" ", strip=True) for cell in rows[2].find_all(["th", "td"])] if len(rows) > 2 else []
                second_values = [cell.get_text(" ", strip=True) for cell in rows[3].find_all(["th", "td"])] if len(rows) > 3 else []
                stats = dict(zip(headers, values))
                stats.update(dict(zip(second_headers, second_values)))
                return (f"打者：出賽 {stats.get('試合', '-')}｜打席 {stats.get('打席', '-')}｜"
                        f"AVG {stats.get('打率', '-')}｜OBP {stats.get('出塁率', '-')}｜"
                        f"SLG {stats.get('長打率', '-')}｜OPS {stats.get('OPS', '-')}")
            if "防御率" in headers and "投球回" in headers:
                stats = {}
                values = [cell.get_text(" ", strip=True) for cell in rows[1].find_all(["th", "td"])] if len(rows) > 1 else []
                stats.update(dict(zip(headers, values)))
                # Yahoo 會把 WHIP 放在第二組投手欄位列。
                for index, row in enumerate(rows):
                    row_headers = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                    if "WHIP" not in row_headers or index + 1 >= len(rows):
                        continue
                    row_values = [cell.get_text(" ", strip=True) for cell in rows[index + 1].find_all(["th", "td"])]
                    stats.update(dict(zip(row_headers, row_values)))
                    break
                appearances = stats.get("登板", stats.get("試合", "-"))
                starts = stats.get("先発", stats.get("先発登板", "-"))
                decisions = f"{stats.get('勝利', '-')}勝-{stats.get('敗戦', '-')}敗"
                relief = f"中繼 {stats.get('ホールド', '-')}｜救援 {stats.get('セーブ', '-')}"
                return (f"投手：出賽 {appearances}｜先發 {starts}｜"
                        f"{stats.get('投球回', '-')} 局｜{decisions}｜{relief}｜"
                        f"ERA {stats.get('防御率', '-')}｜WHIP {stats.get('WHIP', '-')}")
        return "資料來源未提供"
