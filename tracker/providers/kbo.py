from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
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
    ("헛스윙 삼진 아웃", "揮棒落空三振出局"),
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
    ("땅볼로 출루", "滾地球上壘"),
    ("땅볼 아웃", "滾地球出局"),
    ("땅볼", "滾地球"),
    ("파울플라이", "界外飛球"),
    ("플라이 아웃", "飛球出局"),
    ("플라이", "飛球"),
    ("직선타", "平飛球"),
    ("라인드라이브", "平飛球"),
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
    ("좌중간", "左中間方向"),
    ("우중간", "右中間方向"),
    ("좌전", "左外野方向"),
    ("우전", "右外野方向"),
    ("중전", "中外野方向"),
    ("오른쪽", "右側"),
    ("왼쪽", "左側"),
    ("가운데", "中間"),
    ("내야", "內野"),
    ("외야", "外野"),
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
    ("스트라이크 낫아웃", "不死三振"),
    ("낫아웃", "不死三振"),
    ("헛스윙", "揮棒落空"),
    ("파울", "界外球"),
    ("스트라이크", "好球"),
    ("볼", "壞球"),
    ("출루", "上壘"),
    ("진루", "進壘"),
    ("홈인", "回本壘得分"),
    ("터치아웃", "觸殺出局"),
    ("태그아웃", "觸殺出局"),
    ("송구아웃", "傳球刺殺出局"),
    ("포스아웃", "封殺出局"),
    ("병살타 아웃", "雙殺打出局"),
    ("파울플라이 아웃", "界外飛球出局"),
    ("대타", "代打"),
    ("대주자", "代跑"),
    ("교체", "更換"),
    ("앞", "前"),
    ("뒤", "後方"),
    ("전거리", "距離"),
    ("거리", "距離"),
    ("아웃", "出局"),
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
            "Referer": "https://m.sports.naver.com/baseball",
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

        # 查詢 Naver Sports KBO 賽程（逐日查詢以避免跨日筆數限制導致當日賽程被截斷）
        current_d = start
        sched_tasks = []
        while current_d <= end:
            d_str = current_d.isoformat()
            url = (
                f"{self.naver_api_base}/schedule/games?"
                f"upperCategoryId=kbaseball&category=kbo&fromDate={d_str}&toDate={d_str}&size=50&pageSize=50"
            )
            sched_tasks.append(self._get_json(url))
            current_d += timedelta(days=1)

        sched_results = await asyncio.gather(*sched_tasks, return_exceptions=True)
        games_list: list[dict[str, Any]] = []
        for r in sched_results:
            if isinstance(r, dict):
                games_list.extend((r.get("result") or {}).get("games") or [])
        game_dates = {
            g.get("gameId"): g.get("gameDate")
            for g in games_list
            if g.get("gameId")
        }
        game_ids = [
            g.get("gameId")
            for g in games_list
            if g.get("gameId") and (
                "KBO" in g.get("gameId", "")
                or g.get("categoryName") == "KBO"
                or g.get("categoryId", "").lower() == "kbo"
            )
        ]

        if not game_ids:
            return []

        # 1. 抓取 record 以得知各場比賽進行局數與球員資料
        record_tasks = [
            self._get_json(f"{self.naver_api_base}/schedule/games/{gid}/record")
            for gid in game_ids
        ]
        record_results = await asyncio.gather(*record_tasks, return_exceptions=True)

        # 2. 依據各場比賽局數，併發抓取各局 relay 與即時 default relay
        relay_tasks = []
        game_meta: list[tuple[str, str, Any, list[int]]] = []

        for i, gid in enumerate(game_ids):
            rec_data = record_results[i]
            g_date = game_dates.get(gid) or date.today().isoformat()
            cur_inn = 1
            if isinstance(rec_data, dict):
                rec = (rec_data.get("result") or {}).get("recordData") or {}
                sb = rec.get("scoreBoard") or {}
                inns = sb.get("inn") or {}
                cur_inn = max(len(inns.get("away", [])), len(inns.get("home", [])), 1)

            t_indices: list[int] = []
            # 各局完整 relay（inning=1..cur_inn）
            for inn_num in range(1, cur_inn + 1):
                t_indices.append(len(relay_tasks))
                relay_tasks.append(
                    self._get_json(f"{self.naver_api_base}/schedule/games/{gid}/relay?inning={inn_num}")
                )
            # 即時 relay（涵蓋當前半局最新動態）
            t_indices.append(len(relay_tasks))
            relay_tasks.append(self._get_json(f"{self.naver_api_base}/schedule/games/{gid}/relay"))

            game_meta.append((gid, g_date, rec_data, t_indices))

        relay_results = await asyncio.gather(*relay_tasks, return_exceptions=True)
        events: list[TrackingEvent] = []

        for gid, g_date, record_data, t_indices in game_meta:
            # 建立球員姓名與投手官方成績對照表
            player_names: dict[str, str] = {}
            pitcher_box_stats: dict[str, dict[str, Any]] = {}
            if isinstance(record_data, dict):
                rec = (record_data.get("result") or {}).get("recordData") or {}
                for p in (rec.get("pitchersBoxscore") or {}).get("home", []) + (rec.get("pitchersBoxscore") or {}).get("away", []):
                    pcode = str(p.get("pcode", p.get("playerCode", "")))
                    if pcode:
                        player_names[pcode] = p.get("name", "")
                        pitcher_box_stats[pcode] = p
                for b in (rec.get("battersBoxscore") or {}).get("home", []) + (rec.get("battersBoxscore") or {}).get("away", []):
                    bcode = str(b.get("playerCode", b.get("pcode", "")))
                    if bcode:
                        player_names[bcode] = b.get("name", "")

            # 彙整所有局數文字速報與陣容名單投手
            text_relays = []
            for idx in t_indices:
                r_data = relay_results[idx]
                if isinstance(r_data, dict):
                    res = r_data.get("result") or {}
                    text_relay_data = res.get("textRelayData") or {}
                    text_relays.extend(text_relay_data.get("textRelays") or [])
                    for p in (text_relay_data.get("awayLineup", {}).get("pitcher", [])) + (text_relay_data.get("homeLineup", {}).get("pitcher", [])):
                        pcode = str(p.get("pcode", p.get("playerCode", "")))
                        if pcode and pcode not in pitcher_box_stats:
                            pitcher_box_stats[pcode] = p

            if text_relays:
                events.extend(self._parse_relays(text_relays, tracked, gid, g_date, player_names, pitcher_box_stats))

            # 解析終場攻守紀錄表
            if isinstance(record_data, dict):
                res = record_data.get("result") or {}
                rec = res.get("recordData") or {}
                if rec:
                    events.extend(self._parse_record(rec, tracked, gid, g_date))

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
        self,
        relays: list[dict[str, Any]],
        tracked: set[str],
        game_id: str,
        game_date: str = "",
        player_names: dict[str, str] | None = None,
        pitcher_box_stats: dict[str, dict[str, Any]] | None = None,
    ) -> list[TrackingEvent]:
        events: list[TrackingEvent] = []
        event_date = game_date or date.today().isoformat()
        names = player_names or {}
        p_box_map = pitcher_box_stats or {}
        seen_keys: set[str] = set()

        # 彙整並按 seqno 排序所有 options
        all_options: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for item in relays:
            for opt in item.get("textOptions") or []:
                all_options.append((item, opt))

        if all_options:
            all_options.sort(key=lambda x: x[1].get("seqno", 0))
            # 投手累計數據追蹤 (依 pitcher_id 獨立統計)
            pitcher_counts: dict[str, dict[str, int]] = {}
            half_inning_3outs: dict[tuple[int, str], bool] = {}
            half_inning_last_ts: dict[tuple[int, str], datetime] = {}
            pitcher_appearances: dict[str, list[tuple[int, str]]] = defaultdict(list)
            pitcher_at_3outs: dict[str, set[tuple[int, str]]] = defaultdict(set)
            pitcher_replaced_by: dict[str, str] = {}
            last_pitcher_by_side: dict[str, str] = {}
            batting_order_slots: dict[str, dict[int, str]] = {"上": {}, "下": {}}
            for item, opt in all_options:
                half_num = item.get("homeOrAway")
                half = "上" if half_num in (0, "0", "away") else "下"
                state = opt.get("currentGameState") or {}
                b_id = str(state.get("batter", ""))
                if b_id and b_id not in batting_order_slots[half].values():
                    if len(batting_order_slots[half]) < 9:
                        batting_order_slots[half][len(batting_order_slots[half]) + 1] = b_id

            for item, opt in all_options:
                inn = item.get("inn", 0)
                half_num = item.get("homeOrAway")
                half = "上" if half_num in (0, "0", "away") else "下"
                inn_str = f"{inn}局{half}" if inn else ""

                text = opt.get("text", "")
                seqno = opt.get("seqno", 0)
                state = opt.get("currentGameState") or {}

                batter_id = str(state.get("batter", ""))
                pitcher_id = str(state.get("pitcher", ""))
                base_now = datetime.now(UTC)
                event_ts = base_now - timedelta(seconds=max(0, 7200 - seqno * 10))

                if pitcher_id:
                    def_side = "home" if half == "上" else "away"
                    prev_p = last_pitcher_by_side.get(def_side)
                    if prev_p and prev_p != pitcher_id:
                        pitcher_replaced_by[prev_p] = pitcher_id
                    last_pitcher_by_side[def_side] = pitcher_id

                    if (inn, half) not in pitcher_appearances[pitcher_id]:
                        pitcher_appearances[pitcher_id].append((inn, half))

                if state.get("out") in (3, "3"):
                    half_inning_3outs[(inn, half)] = True
                    half_inning_last_ts[(inn, half)] = event_ts
                    if pitcher_id:
                        pitcher_at_3outs[pitcher_id].add((inn, half))

                # 1. 判斷打席結束事件（帶有 ':' 且非跑者進壘、非代打/代跑換人、非勝投標註）
                is_pa_outcome = (
                    ":" in text
                    and "주자" not in text
                    and "교체" not in text
                    and "수비" not in text
                    and "승리투수" not in text
                )

                if is_pa_outcome:
                    parts = text.split(":", 1)
                    raw_batter_name = parts[0].strip()
                    raw_outcome = parts[1].strip()
                    tw_outcome = _translate_kbo(raw_outcome)

                    batter_name = names.get(batter_id, raw_batter_name)
                    opp_pitcher = names.get(pitcher_id, "")

                    # 追蹤打序與次打者 (ON_DECK)
                    slots = batting_order_slots[half]
                    current_slot = None
                    for s_idx, pid in slots.items():
                        if pid == batter_id:
                            current_slot = s_idx
                            break
                    if current_slot is None and len(slots) < 9 and batter_id:
                        current_slot = len(slots) + 1
                        slots[current_slot] = batter_id

                    if current_slot is not None:
                        next_slot = (current_slot % 9) + 1
                        next_batter_id = slots.get(next_slot)
                        if next_batter_id and next_batter_id in tracked:
                            on_deck_key = f"KBO:{game_id}:ON_DECK:{seqno}:{next_batter_id}"
                            if on_deck_key not in seen_keys:
                                seen_keys.add(on_deck_key)
                                outs = int(state.get("out", 0) or 0)
                                events.append(
                                    TrackingEvent(
                                        key=on_deck_key,
                                        league=League.KBO,
                                        game_id=game_id,
                                        player_id=next_batter_id,
                                        kind=EventKind.ON_DECK,
                                        occurred_at=event_ts - timedelta(seconds=1),
                                        title=f"{inn_str}｜即將上場打擊" if inn_str else "即將上場打擊",
                                        body=f"目前 {outs} 出局，下一棒即將輪到打擊！",
                                        game_date=event_date,
                                    )
                                )

                    # 追蹤投手的被安打、保送、三振
                    if pitcher_id:
                        if pitcher_id not in pitcher_counts:
                            pitcher_counts[pitcher_id] = {"h": 0, "bb": 0, "kk": 0, "inn": 0}
                        pt = pitcher_counts[pitcher_id]
                        if any(h in raw_outcome for h in ["안타", "2루타", "3루타", "홈런", "내야안타"]):
                            pt["h"] += 1
                        if any(b in raw_outcome for b in ["4구", "볼넷", "고의4구", "몸에 맞는 볼"]):
                            pt["bb"] += 1
                        if "삼진" in raw_outcome:
                            pt["kk"] += 1

                    # 打者本人打席通知
                    if batter_id in tracked:
                        key = f"KBO:{game_id}:PA:{seqno}:{batter_id}"
                        if key not in seen_keys:
                            seen_keys.add(key)
                            pa_title = (
                                f"{inn_str}｜面對 {opp_pitcher}"
                                if opp_pitcher and inn_str
                                else (f"{inn_str}｜打席結束" if inn_str else "打席結束")
                            )
                            events.append(
                                TrackingEvent(
                                    key=key,
                                    league=League.KBO,
                                    game_id=game_id,
                                    player_id=batter_id,
                                    kind=EventKind.PLATE_APPEARANCE,
                                    occurred_at=event_ts,
                                    title=pa_title,
                                    body=f"{batter_name} {tw_outcome}" if batter_name else tw_outcome,
                                    game_date=event_date,
                                )
                            )

                    # 投手面對打者通知 (PVB)
                    if pitcher_id in tracked:
                        key = f"KBO:{game_id}:PVB:{seqno}:{pitcher_id}:{batter_id}"
                        if key not in seen_keys:
                            seen_keys.add(key)
                            pvb_title = (
                                f"{inn_str}｜面對 {batter_name}"
                                if inn_str and batter_name
                                else (f"面對 {batter_name}" if batter_name else "面對打者")
                            )
                            events.append(
                                TrackingEvent(
                                    key=key,
                                    league=League.KBO,
                                    game_id=game_id,
                                    player_id=pitcher_id,
                                    kind=EventKind.PLATE_APPEARANCE,
                                    occurred_at=event_ts,
                                    title=pvb_title,
                                    body=tw_outcome,
                                    game_date=event_date,
                                )
                            )

                # 2. 局結束投球統計（達到3出局時）
                if pitcher_id in tracked and state.get("out") in (3, "3"):
                    if pitcher_id not in pitcher_counts:
                        pitcher_counts[pitcher_id] = {"h": 0, "bb": 0, "kk": 0, "inn": 0}
                    pt = pitcher_counts[pitcher_id]
                    pt["inn"] += 1
                    cur_inn_num = inn if inn else pt["inn"]

                    p_box = p_box_map.get(pitcher_id) or {}
                    if not p_box:
                        cpi = opt.get("currentPlayersInfo") or {}
                        for s_name in ["away", "home"]:
                            pi = cpi.get(s_name) or {}
                            if pi.get("playerType") == "pitcher":
                                cs = pi.get("currentGamePlayerStats") or {}
                                if cs.get("inn"):
                                    p_box = {
                                        "inn": cs.get("inn"),
                                        "hit": cs.get("hit", 0),
                                        "r": cs.get("run", 0),
                                        "bb": cs.get("bb", 0),
                                        "kk": cs.get("kk", 0),
                                        "bf": (cs.get("strikeCount", 0) or 0) + (cs.get("ballCount", 0) or 0),
                                    }
                                    break
                    box_inn = str(p_box.get("inn", ""))

                    # 若為該局結束與 boxscore 相符，直接採用官方累積成績
                    if box_inn in (f"{cur_inn_num}.0", str(cur_inn_num)):
                        cur_inn_str = box_inn
                        hit = p_box.get("hit", pt["h"])
                        run = p_box.get("r", p_box.get("run", 0))
                        er = p_box.get("er", 0)
                        bb = p_box.get("bb", pt["bb"])
                        kk = p_box.get("kk", pt["kk"])
                        balls = p_box.get("bf", p_box.get("ballCount", 0))
                    else:
                        cur_inn_str = f"{cur_inn_num}.0"
                        hit = pt["h"]
                        run = p_box.get("r", p_box.get("run", 0))
                        er = p_box.get("er", 0)
                        bb = pt["bb"]
                        kk = pt["kk"]
                        balls = p_box.get("bf", p_box.get("ballCount", 0))

                    er_str = f"（{er} 責失）" if er else ""
                    balls_str = f"、{balls} 球" if balls else ""
                    body = (
                        f"目前累計成績：{cur_inn_str} 局、{hit} 安打、{run} 失分{er_str}、"
                        f"{bb} 保送、{kk} 三振{balls_str}"
                    )
                    key = f"KBO:{game_id}:IP_END:{inn}:{half}:{pitcher_id}"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        events.append(
                            TrackingEvent(
                                key=key,
                                league=League.KBO,
                                game_id=game_id,
                                player_id=pitcher_id,
                                kind=EventKind.PITCHING_INNING,
                                occurred_at=event_ts + timedelta(seconds=1),
                                title=f"{inn_str}投球結束" if inn_str else "投球結束",
                                body=body,
                                game_date=event_date,
                            )
                        )
            # 3. 投手退場通知（PITCHING_EXIT）
            for pid in tracked:
                if pid in pitcher_appearances:
                    p_box = p_box_map.get(pid) or {}
                    has_end = bool(p_box.get("hasPlayerEnd"))
                    is_replaced = (pid in pitcher_replaced_by) or has_end

                    if is_replaced:
                        last_inn, last_half = pitcher_appearances[pid][-1]
                        completed = (last_inn, last_half) in pitcher_at_3outs[pid]
                        inn_finished = half_inning_3outs.get((last_inn, last_half), False)

                        # 狀況一：吃完完整局數退場（該局 3 出局完成）
                        # 狀況二：非完整局數退場（局中被換），依要求「在該局結束後通知」
                        should_emit_exit = (completed and inn_finished) or (not completed and inn_finished)

                        if should_emit_exit:
                            key = f"KBO:{game_id}:PITCHING_EXIT:{pid}"
                            if key not in seen_keys:
                                seen_keys.add(key)
                                pt = pitcher_counts.get(pid, {"h": 0, "bb": 0, "kk": 0, "inn": 0})
                                cur_inn_str = str(p_box.get("inn") or f"{pt['inn']}.0")
                                hit = p_box.get("hit", pt["h"])
                                run = p_box.get("r", p_box.get("run", 0))
                                er = p_box.get("er", 0)
                                bb = p_box.get("bb", pt["bb"])
                                kk = p_box.get("kk", pt["kk"])
                                balls = p_box.get("bf", p_box.get("ballCount", 0))

                                er_str = f"（{er} 責失）" if er else ""
                                balls_str = f"、{balls} 球" if balls else ""
                                body = (
                                    f"今日投球成績：{cur_inn_str} 局、{hit} 安打、{run} 失分{er_str}、"
                                    f"{bb} 保送、{kk} 三振{balls_str}"
                                )
                                exit_ts = half_inning_last_ts.get((last_inn, last_half), event_ts) + timedelta(seconds=2)
                                events.append(
                                    TrackingEvent(
                                        key=key,
                                        league=League.KBO,
                                        game_id=game_id,
                                        player_id=pid,
                                        kind=EventKind.PITCHING_EXIT,
                                        occurred_at=exit_ts,
                                        title="投球工作結束（退場）",
                                        body=body,
                                        game_date=event_date,
                                    )
                                )
        else:
                # 兼容簡易結構（如單元測試）
                text = item.get("text", "")
                seqno = item.get("seqno", 0)
                state = item.get("currentGameState") or {}
                batter_id = str(state.get("batter", ""))
                pitcher_id = str(state.get("pitcher", ""))

                if batter_id in tracked and text and ":" in text:
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
                            game_date=event_date,
                        )
                    )

                if pitcher_id in tracked and text and ":" in text:
                    parts = text.split(":", 1)
                    batter_name = parts[0].strip()
                    tw_outcome = _translate_kbo(parts[1].strip())
                    key = f"KBO:{game_id}:PVB:{seqno}:{pitcher_id}:{batter_id}"
                    events.append(
                        TrackingEvent(
                            key=key,
                            league=League.KBO,
                            game_id=game_id,
                            player_id=pitcher_id,
                            kind=EventKind.PLATE_APPEARANCE,
                            occurred_at=datetime.now(UTC),
                            title=f"面對 {batter_name}" if batter_name else "面對打者",
                            body=tw_outcome,
                            game_date=event_date,
                        )
                    )

                if pitcher_id in tracked:
                    players_info = item.get("currentPlayersInfo") or {}
                    for side in ["home", "away"]:
                        p_info = players_info.get(side) or {}
                        if p_info.get("playerType") == "pitcher":
                            curr_stats = p_info.get("currentGamePlayerStats") or {}
                            inn_v = curr_stats.get("inn")
                            if inn_v:
                                kk = curr_stats.get("kk", 0)
                                bb = curr_stats.get("bb", 0)
                                hit = curr_stats.get("hit", 0)
                                run = curr_stats.get("run", 0)
                                balls = (curr_stats.get("strikeCount", 0) or 0) + (curr_stats.get("ballCount", 0) or 0)
                                body = (
                                    f"目前局內/累計成績：{inn_v} 局、{hit} 安打、{run} 失分、"
                                    f"{bb} 保送、{kk} 三振、{balls} 球"
                                )
                                key = f"KBO:{game_id}:IP:{pitcher_id}:{inn_v}:{balls}"
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
                                        game_date=event_date,
                                    )
                                )
        return events

    def _parse_record(
        self, rec: dict[str, Any], tracked: set[str], game_id: str, game_date: str = ""
    ) -> list[TrackingEvent]:
        events: list[TrackingEvent] = []
        event_date = game_date or date.today().isoformat()
        # 檢查是否為終場
        is_final = False
        game_info = rec.get("gameInfo") or {}
        status_val = str(game_info.get("status", "")).upper()
        status_code = str(game_info.get("statusCode", "")).upper()
        if status_val in {"RESULT", "END", "CANCEL"} or status_code in {"4", "RESULT", "END", "CANCEL"}:
            is_final = True
        elif bool(rec.get("pitchingResult")):
            is_final = True

        if not is_final:
            return []

        batters_box = rec.get("battersBoxscore") or {}
        pitchers_box = rec.get("pitchersBoxscore") or {}

        for side in ["away", "home"]:
            # 打者
            for b in (batters_box.get(side) or []):
                pcode = str(b.get("playerCode", b.get("pcode", "")))
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
                            game_date=event_date,
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
                            game_date=event_date,
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
        try:
            url_p = f"{self.kbo_official_base}/Record/Player/PitcherDetail/Basic.aspx?playerId={player_id}"
            tables = (await self._get_html(url_p)).find_all("table")
            if tables:
                s0, s1 = _table_to_dict(tables[0]), _table_to_dict(tables[1]) if len(tables) > 1 else {}
                if "ERA" in s0 and "IP" in s0:
                    return (
                        f"投手：出賽 {s0.get('G', '-')}｜{s0.get('IP', '-')} 局｜"
                        f"{s0.get('W', '-')}勝-{s0.get('L', '-')}敗｜"
                        f"中繼 {s0.get('HLD', '-')}｜救援 {s0.get('SV', '-')}｜"
                        f"ERA {s0.get('ERA', '-')}｜WHIP {s1.get('WHIP', '-')}"
                    )
            url_h = f"{self.kbo_official_base}/Record/Player/HitterDetail/Basic.aspx?playerId={player_id}"
            tables = (await self._get_html(url_h)).find_all("table")
            if tables:
                s0, s1 = _table_to_dict(tables[0]), _table_to_dict(tables[1]) if len(tables) > 1 else {}
                if "AVG" in s0 and "PA" in s0:
                    return (
                        f"打者：出賽 {s0.get('G', '-')}｜打席 {s0.get('PA', '-')}｜"
                        f"AVG {s0.get('AVG', '-')}｜OBP {s1.get('OBP', '-')}｜"
                        f"SLG {s1.get('SLG', '-')}｜OPS {s1.get('OPS', '-')}"
                    )
        except Exception as exc:
            log.warning("取得 KBO 球員 %s 累計成績失敗：%s", player_id, exc)
        return "資料來源未提供"


def _table_to_dict(table: Any) -> dict[str, str]:
    rows = table.find_all("tr")
    if len(rows) < 2:
        return {}
    keys = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
    vals = [c.get_text(" ", strip=True) for c in rows[1].find_all(["th", "td"])]
    return dict(zip(keys, vals))


def _translate_kbo(text: str) -> str:
    result = text
    for kr, tw in KBO_REPLACE_MAP:
        result = result.replace(kr, tw)
    return result
