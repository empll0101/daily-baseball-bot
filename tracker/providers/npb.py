from __future__ import annotations

import asyncio
import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import aiohttp
from bs4 import BeautifulSoup

from ..models import EventKind, League, Player, TrackingEvent
from .base import DataProvider, ProviderUnavailable
from .npb_dict import INNINGS_MAP, REPLACE_MAP, translate_npb_text


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
        name_elem = soup.select_one("h2.bb-profile__name, .bb-profile__name, h1.bb-headform__title")
        name = name_elem.get_text(" ", strip=True) if name_elem else ""
        if not name:
            heading = soup.find("h1") or soup.find("h2")
            name = heading.get_text(" ", strip=True) if heading else f"NPB球員 {player_id}"
            if "スポーツナビ" in name:
                name = f"NPB球員 {player_id}"

        team_elem = soup.select_one(".bb-title02__title, .bb-headform__team")
        team = team_elem.get_text(strip=True) if team_elem else ""

        prof = soup.select_one(".bb-profile")
        prof_text = prof.get_text(" ", strip=True) if prof else ""
        pos_m = re.search(r"\b(投手|捕手|内野手|外野手)\b", prof_text)
        pos = pos_m.group(1) if pos_m else ""

        return Player(League.NPB, player_id, name, team, pos)

    async def collect_events(self, player_ids: Iterable[str], start: date, end: date) -> list[TrackingEvent]:
        tracked = {p.external_id if isinstance(p, Player) else str(p) for p in player_ids}
        if not tracked:
            return []

        # 1. 取得當日比賽列表（同時檢查首頁與賽程頁面，並支援任意比賽連結後綴）
        game_ids: set[str] = set()
        pages_to_check: list[str] = []
        if start and end:
            cur = start
            while cur <= end:
                pages_to_check.append(f"/npb/schedule/?date={cur.isoformat()}")
                cur += timedelta(days=1)
        elif start:
            pages_to_check.append(f"/npb/schedule/?date={start.isoformat()}")

        # 若是查詢今日（或即時追蹤未指定具體歷史日期），同時加入即時首頁與即時賽程
        if not start or start == date.today():
            pages_to_check.extend(["/npb/", "/npb/schedule/"])

        for page_url in pages_to_check:
            try:
                page_soup = await self._html(page_url)
                for a in page_soup.select('a[href*="/npb/game/"]'):
                    href = a.get("href", "")
                    m = re.search(r"/npb/game/(\d+)", href)
                    if m:
                        game_ids.add(m.group(1))
            except Exception:
                continue

        events: list[TrackingEvent] = []
        for game_id in sorted(game_ids):
            text_html, stats_html = await asyncio.gather(
                self._html(f"/npb/game/{game_id}/text"),
                self._html(f"/npb/game/{game_id}/stats"),
                return_exceptions=True
            )

            # 取得比賽真實日期，並檢查是否在查詢區間內
            actual_game_date: str | None = None
            for soup_candidate in [stats_html, text_html]:
                if not isinstance(soup_candidate, Exception) and soup_candidate.title:
                    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", soup_candidate.title.get_text())
                    if m:
                        actual_game_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                        break

            if start and end and actual_game_date:
                if not (start.isoformat() <= actual_game_date <= end.isoformat()):
                    continue

            game_date_str = actual_game_date or (start.isoformat() if start else date.today().isoformat())

            # 判斷本場比賽是否已結束（僅檢查本場比賽專屬區塊，避免被頁面全域頂部導覽列中其他已結束比賽干擾）
            final = False
            if not isinstance(text_html, Exception):
                for sec in text_html.select("section.bb-liveText"):
                    for state in sec.select("p.bb-liveText__summary span.bb-liveText__state"):
                        text_val = state.get_text(strip=True)
                        if "試合終了" in text_val or "コールド" in text_val:
                            final = True
                            break
                    if final:
                        break

            if not final:
                try:
                    top_html = await self._html(f"/npb/game/{game_id}/index")
                    card_state = top_html.select_one(".bb-gameCard .bb-gameCard__state")
                    if card_state:
                        text_val = card_state.get_text(strip=True)
                        if any(k in text_val for k in ["試合終了", "コールド"]):
                            final = True
                except Exception:
                    pass

            # 1. 整理投手數據與先發 (stats_html)
            pitcher_stats: dict[str, dict[str, str]] = {}
            pitcher_names: dict[str, str] = {}
            current_pitchers: dict[str, str] = {}
            if not isinstance(stats_html, Exception):
                score_tables = [
                    t for t in stats_html.find_all("table")
                    if any("投球回" in th.get_text() for th in t.find_all(["th", "td"]))
                ]
                for half_key, table in zip(["裏", "表"], score_tables):
                    headers = [th.get_text(" ", strip=True) for th in table.find_all("tr")[0].find_all(["th", "td"])] if table.find_all("tr") else []
                    for row in table.find_all("tr")[1:]:
                        link = row.select_one('a[href*="/npb/player/"]')
                        if not link:
                            continue
                        m = re.search(r"/npb/player/(\d+)", link.get("href", ""))
                        if m:
                            pid = m.group(1)
                            pitcher_names[pid] = link.get_text(" ", strip=True)
                            if half_key not in current_pitchers:
                                current_pitchers[half_key] = pid
                            pitcher_stats[pid] = dict(zip(headers, [td.get_text(" ", strip=True) for td in row.find_all(["th", "td"])]))

            # 1.1 整理打者打序 (stats_html)
            batting_order_slots: dict[str, dict[int, str]] = {"裏": {}, "表": {}}
            if not isinstance(stats_html, Exception):
                batter_tables = [
                    t for t in stats_html.find_all("table")
                    if "打数" in [th.get_text(" ", strip=True) for th in t.find_all(["th", "td"])]
                ]
                for half_key, table in zip(["表", "裏"], batter_tables):
                    slot_idx = 1
                    for row in table.find_all("tr")[1:]:
                        link = row.select_one('a[href*="/npb/player/"]')
                        if link:
                            m = re.search(r"/npb/player/(\d+)", link.get("href", ""))
                            if m:
                                pid = m.group(1)
                                if slot_idx <= 9:
                                    batting_order_slots[half_key][slot_idx] = pid
                                    slot_idx += 1

            event_seq = 0
            base_time = datetime.now(UTC)

            def next_event_time() -> datetime:
                nonlocal event_seq
                event_seq += 1
                return base_time + timedelta(seconds=event_seq)

            # 2. 逐局解析打席與投球結算 (text_html)
            if not isinstance(text_html, Exception):
                sections = text_html.select("section.bb-liveText")
                # Yahoo Sportsnavi 比賽進行中時局數常為倒序（如 9回表 -> 8回裏 ... -> 1回表），
                # 必須先強制依 1回表 -> 1回裏 ... 正序排序，以確保投手替換與局數推進符合真實時間軸
                sections = sorted(sections, key=_inning_sort_key)
                pitcher_sections: dict[str, list[int]] = defaultdict(list)
                last_pitcher_in_sec: dict[int, str] = {}
                section_done: dict[int, bool] = {}
                pitcher_replaced: dict[str, bool] = {}
                last_pitcher_by_side: dict[str, str] = {}

                for sec_idx, inning_section in enumerate(sections):
                    inning_title = inning_section.select_one("h1.bb-liveText__inning")
                    raw_inning = inning_title.get_text(" ", strip=True) if inning_title else "未知局數"
                    inning_str = INNINGS_MAP.get(raw_inning, raw_inning)
                    half = "裏" if "裏" in raw_inning else "表"
                    inning_pitchers: set[str] = set()

                    # Yahoo Sportsnavi 進行中時項目為倒序 (如 4: -> 3: -> 1:)，完賽後為正序 (1: -> 2: -> 4:)
                    # 強制依照項目序號 (1, 2, 3...) 正序排序，確保時間軸完全正確
                    items = sorted(inning_section.select("li.bb-liveText__item"), key=_item_seq_key)

                    for item in items:
                        item_seq = _item_seq_key(item)
                        change = item.select_one("p.bb-liveText__summary--change")
                        if change:
                            new_pitcher, subs = _parse_npb_change_summary(change)
                            if new_pitcher:
                                pid, pname = new_pitcher
                                old_p = current_pitchers.get(half)
                                if old_p and old_p != pid:
                                    pitcher_replaced[old_p] = True
                                current_pitchers[half] = pid
                                pitcher_names[pid] = pname

                            for sub_pid, sub_name, sub_kind, sub_desc in subs:
                                if sub_pid in tracked:
                                    sub_title_map = {
                                        "PINCH_RUNNER": f"{inning_str}｜上場代走",
                                        "PINCH_HIT": f"{inning_str}｜代打上場",
                                        "DEFENSE": f"{inning_str}｜守備替補/更換",
                                        "PITCHER": f"{inning_str}｜登板投球",
                                    }
                                    sub_key = f"NPB:{game_id}:SUB:{raw_inning}:{sub_pid}:{sub_kind}"
                                    events.append(TrackingEvent(
                                        key=sub_key,
                                        league=League.NPB,
                                        game_id=game_id,
                                        player_id=sub_pid,
                                        kind=EventKind.PLATE_APPEARANCE,
                                        occurred_at=next_event_time(),
                                        title=sub_title_map.get(sub_kind, f"{inning_str}｜選手更換"),
                                        body=translate_npb_text(sub_desc),
                                        game_date=game_date_str,
                                    ))

                        pitcher_id = current_pitchers.get(half, "")
                        if pitcher_id:
                            inning_pitchers.add(pitcher_id)
                            last_pitcher_in_sec[sec_idx] = pitcher_id
                            if sec_idx not in pitcher_sections[pitcher_id]:
                                pitcher_sections[pitcher_id].append(sec_idx)
                            prev_p = last_pitcher_by_side.get(half)
                            if prev_p and prev_p != pitcher_id:
                                pitcher_replaced[prev_p] = True
                            last_pitcher_by_side[half] = pitcher_id

                        batter_link = item.select_one("p.bb-liveText__batter a.bb-liveText__player")
                        if not batter_link:
                            continue
                        m = re.search(r"/npb/player/(\d+)", batter_link.get("href", ""))
                        if not m:
                            continue
                        batter_id = m.group(1)
                        batter_name = batter_link.get_text(" ", strip=True)

                        order_tag = item.select_one("p.bb-liveText__batter span.bb-liveText__order")
                        order_num = None
                        if order_tag:
                            om = re.search(r"(\d+)番", order_tag.get_text())
                            if om:
                                order_num = int(om.group(1))
                                batting_order_slots[half][order_num] = batter_id

                        # 次打者提前預告 (ON_DECK)
                        if order_num:
                            next_slot = (order_num % 9) + 1
                            next_batter_id = batting_order_slots[half].get(next_slot)
                            if next_batter_id and next_batter_id in tracked:
                                state_tag = item.select_one("p.bb-liveText__batter span.bb-liveText__state")
                                outs = 0
                                if state_tag:
                                    st = state_tag.get_text()
                                    if "二死" in st or "2死" in st:
                                        outs = 2
                                    elif "一死" in st or "1死" in st:
                                        outs = 1
                                    elif "無死" in st or "0死" in st:
                                        outs = 0
                                events.append(TrackingEvent(
                                    key=f"NPB:{game_id}:ON_DECK:{raw_inning}:{item_seq}:{next_batter_id}",
                                    league=League.NPB,
                                    game_id=game_id,
                                    player_id=next_batter_id,
                                    kind=EventKind.ON_DECK,
                                    occurred_at=next_event_time(),
                                    title=f"{inning_str}｜即將上場打擊",
                                    body=f"目前 {outs} 出局，下一棒即將輪到打擊！",
                                    game_date=game_date_str,
                                ))

                        summaries = item.select("p.bb-liveText__summary:not(.bb-liveText__summary--change) span.bb-liveText__state")
                        if not summaries:
                            continue
                        raw_outcome = summaries[-1].get_text(" ", strip=True)
                        if not raw_outcome or raw_outcome in {"→", "->", "－"}:
                            continue
                        outcome = translate_npb_text(raw_outcome)

                        # 打者打席通知
                        if batter_id in tracked:
                            key = f"NPB:{game_id}:PA:{raw_inning}:{batter_id}:{hashlib.sha1(raw_outcome.encode()).hexdigest()[:12]}"
                            opp_pitcher = pitcher_names.get(pitcher_id, "")
                            pa_title = f"{inning_str}｜面對 {opp_pitcher}" if opp_pitcher else f"{inning_str}｜打席結束"
                            events.append(TrackingEvent(
                                key=key, league=League.NPB, game_id=game_id, player_id=batter_id,
                                kind=EventKind.PLATE_APPEARANCE, occurred_at=next_event_time(),
                                title=pa_title, body=outcome, game_date=game_date_str,
                            ))

                        # 投手面對打者通知
                        if pitcher_id in tracked:
                            key = f"NPB:{game_id}:PVB:{raw_inning}:{pitcher_id}:{batter_id}:{hashlib.sha1(raw_outcome.encode()).hexdigest()[:12]}"
                            events.append(TrackingEvent(
                                key=key, league=League.NPB, game_id=game_id, player_id=pitcher_id,
                                kind=EventKind.PLATE_APPEARANCE, occurred_at=next_event_time(),
                                title=f"{inning_str}｜面對 {batter_name}", body=outcome, game_date=game_date_str,
                            ))

                    # 該局結束結算（確切換局：footer 得分非 '-' / 包含 3 出局 / 包含賽事終止關鍵字 / 已有後續局數）
                    footer_data = inning_section.select_one("footer.bb-liveText__footer td.bb-liveTextTable__data")
                    has_score_footer = bool(footer_data and footer_data.get_text(strip=True) not in {"-", ""})
                    has_3outs = "3アウト" in inning_section.get_text()
                    has_walkoff_or_end = any(k in inning_section.get_text() for k in ["試合終了", "コールド", "サヨナラ", "ゲームセット"])
                    is_past_inning = sec_idx < len(sections) - 1
                    inning_done = has_score_footer or has_3outs or has_walkoff_or_end or is_past_inning
                    if inning_done:
                        section_done[sec_idx] = True
                        for pid in inning_pitchers:
                            if pid in tracked and pid in pitcher_stats:
                                # 若該投手是在該局中途被換下（非本局最後一人，且已被換掉），不發送 IP_END，待該半局結束時發送 PITCHING_EXIT
                                is_subbed_mid_inning = pitcher_replaced.get(pid, False) and last_pitcher_in_sec.get(sec_idx) != pid
                                if not is_subbed_mid_inning:
                                    sd = pitcher_stats[pid]
                                    ip_str = sd.get("投球回", "0")
                                    er = sd.get("自責点")
                                    er_str = f"（{er} 責失）" if er is not None and er != "-" else ""
                                    body = (f"目前累計成績：{ip_str} 局、{sd.get('被安打', '0')} 安打、"
                                            f"{sd.get('失点', '0')} 失分{er_str}、{_parse_npb_walks(sd)} 保送、"
                                            f"{sd.get('奪三振', '0')} 三振、{sd.get('投球数', '0')} 球")
                                    key = f"NPB:{game_id}:IP_END:{raw_inning}:{pid}"
                                    events.append(TrackingEvent(
                                        key=key, league=League.NPB, game_id=game_id, player_id=pid,
                                        kind=EventKind.PITCHING_INNING, occurred_at=next_event_time(),
                                        title=f"{inning_str}投球結束", body=body, game_date=game_date_str,
                                    ))

                # 投手退場通知（PITCHING_EXIT）
                for pid in tracked:
                    if pid in pitcher_sections and pitcher_stats.get(pid):
                        # 若該半邊已換上新投手，代表已退場
                        is_replaced = pitcher_replaced.get(pid, False)
                        if is_replaced:
                            last_sec = pitcher_sections[pid][-1]
                            completed = (last_pitcher_in_sec.get(last_sec) == pid)
                            inn_finished = section_done.get(last_sec, False)

                            # 狀況一：完整局數吃完後退場（該局已完成換局）
                            # 狀況二：非完整局數吃完後退場（局中被換），等待該半局 3 出局結束後通知
                            should_emit_exit = (completed and inn_finished) or (not completed and inn_finished)

                            if should_emit_exit:
                                key = f"NPB:{game_id}:PITCHING_EXIT:{pid}"
                                sd = pitcher_stats[pid]
                                ip_str = sd.get("投球回", "0")
                                er = sd.get("自責点")
                                er_str = f"（{er} 責失）" if er is not None and er != "-" else ""
                                body = (f"今日投球成績：{ip_str} 局、{sd.get('被安打', '0')} 安打、"
                                        f"{sd.get('失点', '0')} 失分{er_str}、{_parse_npb_walks(sd)} 保送、"
                                        f"{sd.get('奪三振', '0')} 三振、{sd.get('投球数', '0')} 球")
                                events.append(TrackingEvent(
                                    key=key, league=League.NPB, game_id=game_id, player_id=pid,
                                    kind=EventKind.PITCHING_EXIT, occurred_at=next_event_time(),
                                    title="投球工作結束（退場）", body=body, game_date=game_date_str,
                                ))


            # 3. GAME_FINAL
            if final:
                for player_id in tracked:
                    final_sections: list[str] = []
                    if not isinstance(stats_html, Exception):
                        for table in stats_html.find_all("table"):
                            rows = table.find_all("tr")
                            if not rows:
                                continue
                            headers = [th.get_text(" ", strip=True) for th in rows[0].find_all(["th", "td"])]

                            # 擷取打擊成績（支援各種 table class）
                            if "打数" in headers and any(k in headers for k in ["選手名", "選手", "打者", "名前"]):
                                for row in rows[1:]:
                                    link = row.select_one('a[href*="/npb/player/"]')
                                    if not link:
                                        continue
                                    m = re.search(r"/npb/player/(\d+)", link.get("href", ""))
                                    if not m or m.group(1) != player_id:
                                        continue
                                    cols = [td.get_text(" ", strip=True) for td in row.find_all(["th", "td"])]
                                    sd = dict(zip(headers, cols))
                                    ab = sd.get("打数", "0")
                                    h = sd.get("安打", "0")
                                    r = sd.get("得点", "0")
                                    rbi = sd.get("打点", "0")
                                    so = sd.get("三振", "0")
                                    bb = (
                                        int(sd.get("四球", 0) or 0) + int(sd.get("死球", 0) or 0)
                                        if ("四球" in sd or "死球" in sd)
                                        else sd.get("四死球", "0")
                                    )
                                    hr = sd.get("本塁打", "0")
                                    sb = sd.get("盗塁", "0")
                                    final_sections.append(
                                        f"打者：{ab} 打數、{h} 安打、{hr} 全壘打、{r} 得分、{rbi} 打點、{bb} 保送、{so} 三振、{sb} 盜壘"
                                    )

                            # 擷取投球成績（支援各種 table class）
                            if "投球回" in headers and any(k in headers for k in ["選手名", "選手", "投手", "名前"]):
                                for row in rows[1:]:
                                    link = row.select_one('a[href*="/npb/player/"]')
                                    if not link:
                                        continue
                                    m = re.search(r"/npb/player/(\d+)", link.get("href", ""))
                                    if not m or m.group(1) != player_id:
                                        continue
                                    cols = [td.get_text(" ", strip=True) for td in row.find_all(["th", "td"])]
                                    sd = dict(zip(headers, cols))
                                    ip = sd.get("投球回", "0")
                                    h = sd.get("被安打", "0")
                                    r = sd.get("失点", "0")
                                    er = sd.get("自責点", r)
                                    walks = _parse_npb_walks(sd)
                                    so = sd.get("奪三振", "0")
                                    np = sd.get("投球数", "0")
                                    final_sections.append(
                                        f"投手：{ip} 局、{h} 被安打、{r} 失分、{er} 自責分、{walks} 保送、{so} 三振、{np} 球"
                                    )

                    if final_sections:
                        body_content = "\n".join(final_sections)
                    else:
                        # 檢查是否在出賽名單中
                        played = False
                        if not isinstance(stats_html, Exception):
                            for link in stats_html.select('a[href*="/npb/player/"]'):
                                m = re.search(r"/npb/player/(\d+)", link.get("href", ""))
                                if m and m.group(1) == player_id:
                                    played = True
                                    break
                        if not played and not isinstance(text_html, Exception):
                            for link in text_html.select('a[href*="/npb/player/"]'):
                                m = re.search(r"/npb/player/(\d+)", link.get("href", ""))
                                if m and m.group(1) == player_id:
                                    played = True
                                    break
                        if not played:
                            continue
                        body_content = "比賽結束，本日出賽細節請參考打席與投球紀錄。"

                    key = f"NPB:{game_id}:FINAL:{player_id}"
                    events.append(TrackingEvent(
                        key=key,
                        league=League.NPB,
                        game_id=game_id,
                        player_id=player_id,
                        kind=EventKind.GAME_FINAL,
                        occurred_at=next_event_time(),
                        title="終場成績",
                        body=body_content,
                        game_date=game_date_str,
                    ))
                        
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

        events.sort(key=lambda event: event.occurred_at)
        return events

    async def daily_summary(self, player: Player, start: date, end: date) -> str:
        events = await self.collect_events([player.external_id], start, end)
        finals = [event.body for event in events if event.kind == EventKind.GAME_FINAL]
        season = await self._season_stats(player.external_id)
        if finals:
            games = "\n\n".join(finals)
        else:
            pa_events = [
                e for e in events
                if e.player_id == player.external_id and e.kind == EventKind.PLATE_APPEARANCE and "面對" in e.title
            ]
            ip_events = [
                e for e in events
                if e.player_id == player.external_id and e.kind == EventKind.PITCHING_INNING
            ]
            if pa_events or ip_events:
                lines = []
                for pa in pa_events:
                    lines.append(f"- {pa.title}：{pa.body}")
                for ip in ip_events:
                    lines.append(f"- {ip.title}：{ip.body}")
                games = "本日出賽紀錄（未結算或比賽進行中）：\n" + "\n".join(lines)
            else:
                games = "這段期間沒有可用的出賽紀錄。"
        cleaned_games = games.replace(f"\n\n**球季累計**\n{season}", "")
        return f"{cleaned_games}\n\n**球季累計**\n{season}"

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


def _inning_sort_key(section: BeautifulSoup) -> tuple[int, int]:
    """將 Yahoo NPB 局數區塊正規化為可排序的時間軸鍵值 (局數, 表/裏)"""
    h1 = section.select_one("h1.bb-liveText__inning")
    if not h1:
        return (0, 0)
    text = h1.get_text(strip=True)
    m = re.search(r"(\d+)回(表|裏)", text)
    if not m:
        return (0, 0)
    inning_num = int(m.group(1))
    half_order = 0 if m.group(2) == "表" else 1
    return (inning_num, half_order)


def _item_seq_key(item: BeautifulSoup) -> int:
    """提取 Yahoo NPB 打席/事件序號 (如 1：, 2：)，以利不論即時倒序或賽後正序皆能正序排序。"""
    num_tag = item.select_one(".bb-liveText__number, span.bb-liveText__num, p.bb-liveText__num")
    if num_tag:
        m = re.search(r"(\d+)", num_tag.get_text())
        if m:
            return int(m.group(1))
    return 0


def _parse_npb_change_summary(change_tag: BeautifulSoup) -> tuple[tuple[str, str] | None, list[tuple[str, str, str, str]]]:
    """
    解析 Yahoo NPB bb-liveText__summary--change 標籤。
    回傳：
      new_pitcher: tuple[str, str] | None -> (pitcher_id, pitcher_name)
      substitutions: list[tuple[str, str, str, str]] -> (player_id, player_name, sub_kind, description)
    """
    new_pitcher: tuple[str, str] | None = None
    substitutions: list[tuple[str, str, str, str]] = []

    raw_nodes: list[tuple[str, str] | tuple[str, str, str]] = []
    for elem in change_tag.children:
        if isinstance(elem, str):
            t = elem.strip()
            if t:
                raw_nodes.append(("text", t))
        elif hasattr(elem, "name") and elem.name == "a" and "bb-liveText__player" in elem.get("class", []):
            href = elem.get("href", "")
            m = re.search(r"/npb/player/(\d+)", href)
            pid = m.group(1) if m else ""
            name = elem.get_text(" ", strip=True)
            if pid:
                raw_nodes.append(("player", pid, name))
        elif hasattr(elem, "get_text"):
            t = elem.get_text(" ", strip=True)
            if t:
                raw_nodes.append(("text", t))

    nodes: list[tuple[str, str] | tuple[str, str, str]] = []
    for item in raw_nodes:
        if item[0] == "text":
            text = str(item[1])
            for kw in [
                "守備交代:", "守備交代：", "守備変更:", "守備変更：", "守備位置変更:", "守備位置変更：",
                "代走:", "代走：", "代走", "代打:", "代打：", "代打",
                "投手交代:", "投手交代：", "ピッチャー交代:", "ピッチャー交代：",
                "ピッチャー", "投手"
            ]:
                text = text.replace(kw, f" {kw} ")
            parts = [p.strip() for p in re.split(r"[\s\u3000]+", text) if p.strip()]
            for p in parts:
                nodes.append(("text", p))
        else:
            nodes.append(item)

    current_mode = "unknown"
    saw_arrow = False
    pos_context = ""

    i = 0
    while i < len(nodes):
        node = nodes[i]
        if node[0] == "text":
            text = str(node[1])
            if any(k in text for k in ["投手交代", "ピッチャー交代", "ピッチャー", "投手", "マウンドにあがる", "マウンドへ"]):
                current_mode = "pitcher"
                if any(k in text for k in ["→", "->", "に代わって", "にかわって"]):
                    saw_arrow = True
            elif "代走" in text:
                current_mode = "pinch_runner"
                if any(k in text for k in ["→", "->", "に代わって", "にかわって", "代走"]):
                    saw_arrow = True
            elif "代打" in text:
                current_mode = "pinch_hitter"
                if any(k in text for k in ["→", "->", "に代わって", "にかわって", "代打"]):
                    saw_arrow = True
            elif any(k in text for k in ["守備変更", "守備交代", "守備位置変更"]):
                current_mode = "defense"
                pos_context = text.replace("守備交代:", "").replace("守備交代：", "").replace("守備変更:", "").replace("守備変更：", "").strip()
                if any(k in text for k in ["→", "->"]):
                    saw_arrow = True
            elif any(k in text for k in ["→", "->", "に代わって", "にかわって"]):
                saw_arrow = True
            elif current_mode == "defense" and not pos_context:
                pos_context = text

        elif node[0] == "player":
            pid, name = str(node[1]), str(node[2])
            next_text = str(nodes[i + 1][1]) if i + 1 < len(nodes) and nodes[i + 1][0] == "text" else ""

            if current_mode == "pitcher":
                if saw_arrow or "マウンド" in next_text:
                    new_pitcher = (pid, name)
                    substitutions.append((pid, name, "PITCHER", f"投手更換登板：{name}"))
                    saw_arrow = False
                elif any(k in next_text for k in ["→", "->", "に代わって", "にかわって"]):
                    pass
                else:
                    has_later_pitcher = any(
                        n[0] == "player"
                        for n in nodes[i + 1 :]
                        if not any(k in str(n) for k in ["守備変更", "代走", "代打", "守備交代"])
                    )
                    if not has_later_pitcher:
                        new_pitcher = (pid, name)
                        substitutions.append((pid, name, "PITCHER", f"投手登板：{name}"))

            elif current_mode == "pinch_runner":
                if saw_arrow or "代走" in next_text:
                    substitutions.append((pid, name, "PINCH_RUNNER", f"上場代走：{name}"))
                    saw_arrow = False

            elif current_mode == "pinch_hitter":
                if saw_arrow or "代打" in next_text:
                    substitutions.append((pid, name, "PINCH_HIT", f"代打上場：{name}"))
                    saw_arrow = False

            elif current_mode == "defense":
                pos = pos_context or next_text.split("守備")[0].strip()
                pos_context = ""
                if "ピッチャー" in pos or "投手" in pos:
                    new_pitcher = (pid, name)
                    substitutions.append((pid, name, "PITCHER", f"更換守備位置為投手：{name}"))
                else:
                    pos_translated = translate_npb_text(pos)
                    pos_str = f" ({pos_translated})" if pos_translated else ""
                    substitutions.append((pid, name, "DEFENSE", f"替補上場守備：{name}{pos_str}"))
        i += 1

    return new_pitcher, substitutions


def _parse_npb_ip_outs(ip_str: str) -> int:
    ip_str = ip_str.strip()
    if not ip_str or ip_str in {"-", "0"}:
        return 0
    if "1/3" in ip_str:
        parts = ip_str.split()
        return int(parts[0]) * 3 + 1 if len(parts) > 1 and parts[0].isdigit() else 1
    if "2/3" in ip_str:
        parts = ip_str.split()
        return int(parts[0]) * 3 + 2 if len(parts) > 1 and parts[0].isdigit() else 2
    if "." in ip_str:
        try:
            full, frac = ip_str.split(".", 1)
            full_inn = int(full) if full else 0
            frac_out = int(frac[0]) if frac else 0
            return full_inn * 3 + min(frac_out, 2)
        except ValueError:
            return 0
    try:
        return int(ip_str) * 3
    except ValueError:
        return 0


def _parse_npb_walks(sd: dict[str, str]) -> int:
    if "与四球" in sd or "与死球" in sd:
        bb = int(sd.get("与四球", 0) or 0) if str(sd.get("与四球", "")).isdigit() else 0
        hbp = int(sd.get("与死球", 0) or 0) if str(sd.get("与死球", "")).isdigit() else 0
        return bb + hbp
    val = sd.get("与四死球", "0")
    return int(val) if str(val).isdigit() else 0
