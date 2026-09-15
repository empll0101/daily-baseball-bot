import pytest
from tracker.providers.npb import (
    _parse_npb_change_summary,
    _parse_npb_ip_outs,
    _parse_npb_walks,
)
from bs4 import BeautifulSoup
import re


def test_npb_ip_outs_parsing():
    assert _parse_npb_ip_outs("0.2") == 2
    assert _parse_npb_ip_outs("0.1") == 1
    assert _parse_npb_ip_outs("4.1") == 13
    assert _parse_npb_ip_outs("4.2") == 14
    assert _parse_npb_ip_outs("1") == 3
    assert _parse_npb_ip_outs("6") == 18
    assert _parse_npb_ip_outs("1/3") == 1
    assert _parse_npb_ip_outs("2/3") == 2
    assert _parse_npb_ip_outs("4 1/3") == 13
    assert _parse_npb_ip_outs("4 2/3") == 14
    assert _parse_npb_ip_outs("-") == 0
    assert _parse_npb_ip_outs("0") == 0


def test_npb_walks_parsing():
    sd1 = {"与四球": "2", "与死球": "1"}
    assert _parse_npb_walks(sd1) == 3

    sd2 = {"与四球": "0", "与死球": "0"}
    assert _parse_npb_walks(sd2) == 0

    sd3 = {"与四死球": "2"}
    assert _parse_npb_walks(sd3) == 2


def test_npb_substitution_does_not_trigger_batter_event():
    html_snippet = """
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">8回表</h1>
      <li class="bb-liveText__item">
        <div class="bb-liveText__content">
          <div class="bb-liveText__text">
            <p class="bb-liveText__batter">
              <span class="bb-liveText__order">7番</span>
              <a class="bb-liveText__player" href="/npb/player/1000035/top">今宮 健太</a>
            </p>
            <p class="bb-liveText__summary bb-liveText__summary--change">
              <span class="bb-liveText__state">投手交代:</span>
              <a class="bb-liveText__player" href="/npb/player/2106890/top">孫易磊</a>
              <span class="bb-liveText__state">→</span>
              <a class="bb-liveText__player" href="/npb/player/1900092/top">佐藤一</a>
            </p>
            <p class="bb-liveText__summary">
              <span class="bb-liveText__state">ワンバウンドした球に空振り、三振を喫する 1アウト</span>
            </p>
          </div>
        </div>
      </li>
    </section>
    """
    soup = BeautifulSoup(html_snippet, "html.parser")
    tracked_pitcher = "2106890"  # 孫易磊
    tracked_batter = "1000035"   # 今宮 健太

    for item in soup.select("li.bb-liveText__item"):
        # 確保打者欄位不會誤抓到孫易磊
        batter_link = item.select_one("p.bb-liveText__batter a.bb-liveText__player")
        assert batter_link is not None
        match = re.search(r"/npb/player/(\d+)/", batter_link.get("href", ""))
        assert match.group(1) == tracked_batter
        assert match.group(1) != tracked_pitcher


def test_npb_pinch_runner_and_defensive_sub_not_misidentified_as_pitcher():
    """
    測試代走與野手守備替補不會被誤判為投手，且不會收到後續打者的面對通知。
    """
    text_html = """
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">9回表</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/2105283/top">平良 竜哉</a></p>
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">投手交代:</span>
          <a class="bb-liveText__player" href="/npb/player/2117852/top">東山</a>
          <span class="bb-liveText__state">→</span>
          <a class="bb-liveText__player" href="/npb/player/1600150/top">山岡</a>
        </p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">サードゴロ 1アウト</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/2103740/top">YG安田</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">センターへのヒットで出塁 一塁</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/1950205/top">吉納 翼</a></p>
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">一塁走者</span>
          <a class="bb-liveText__player" href="/npb/player/2103740/top">YG安田</a>
          <span class="bb-liveText__state">→代走:</span>
          <a class="bb-liveText__player" href="/npb/player/2117858/top">陽</a>
        </p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">フォアボール 一二塁</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/1800118/top">太田 光</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">空振り三振でバッターアウト 2アウト</span></p>
      </li>
      <footer class="bb-liveText__footer"></footer>
    </section>
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">9回裏</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/1751068/top">野口 智哉</a></p>
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">投手交代:</span>
          <a class="bb-liveText__player" href="/npb/player/2112429/top">江原</a>
          <span class="bb-liveText__state">→</span>
          <a class="bb-liveText__player" href="/npb/player/1300076/top">加治屋</a>
          <span class="bb-liveText__state">守備変更:</span>
          <a class="bb-liveText__player" href="/npb/player/2105283/top">平良</a>
          <span class="bb-liveText__state">セカンド→サード　守備変更:</span>
          <a class="bb-liveText__player" href="/npb/player/2117858/top">陽</a>
          <span class="bb-liveText__state">→セカンド　守備変更:</span>
          <a class="bb-liveText__player" href="/npb/player/1900113/top">黒川</a>
          <span class="bb-liveText__state">サード→ファースト</span>
        </p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">フォアボール 一塁</span></p>
      </li>
      <footer class="bb-liveText__footer"></footer>
    </section>
    """
    stats_html = """
    <table class="bb-scoreTable">
      <tr><th>選手名</th><th>投球回</th></tr>
      <tr><td><a href="/npb/player/2117852/top">東山</a></td><td>1.0</td></tr>
      <tr><td><a href="/npb/player/1600150/top">山岡</a></td><td>1.0</td></tr>
    </table>
    <table class="bb-scoreTable">
      <tr><th>選手名</th><th>投球回</th></tr>
      <tr><td><a href="/npb/player/2112429/top">江原</a></td><td>1.0</td></tr>
      <tr><td><a href="/npb/player/1300076/top">加治屋</a></td><td>1.0</td></tr>
    </table>
    """
    from tracker.models import EventKind, League, TrackingEvent
    from tracker.providers.npb_dict import INNINGS_MAP, translate_npb_text
    import hashlib
    from datetime import datetime, UTC, date

    t_soup = BeautifulSoup(text_html, "html.parser")
    s_soup = BeautifulSoup(stats_html, "html.parser")
    tracked = {"2117858"}  # 追蹤 陽 柏翔
    game_id = "2021039341"

    pitcher_names = {}
    current_pitchers = {}
    score_tables = s_soup.select("table.bb-scoreTable")
    for half_key, table in zip(["裏", "表"], score_tables):
        for row in table.find_all("tr")[1:]:
            link = row.select_one('a[href*="/npb/player/"]')
            if link:
                m = re.search(r"/npb/player/(\d+)", link.get("href", ""))
                if m:
                    pid = m.group(1)
                    pitcher_names[pid] = link.get_text(" ", strip=True)
                    if half_key not in current_pitchers:
                        current_pitchers[half_key] = pid

    events = []
    for inning_section in t_soup.select("section.bb-liveText"):
        inning_title = inning_section.select_one("h1.bb-liveText__inning")
        raw_inning = inning_title.get_text(" ", strip=True) if inning_title else "未知局數"
        inning_str = INNINGS_MAP.get(raw_inning, raw_inning)
        half = "裏" if "裏" in raw_inning else "表"

        for item in inning_section.select("li.bb-liveText__item"):
            change = item.select_one("p.bb-liveText__summary--change")
            if change:
                new_pitcher, subs = _parse_npb_change_summary(change)
                if new_pitcher:
                    pid, pname = new_pitcher
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
                            occurred_at=datetime.now(UTC),
                            title=sub_title_map.get(sub_kind, f"{inning_str}｜選手更換"),
                            body=translate_npb_text(sub_desc),
                            game_date=date.today().isoformat(),
                        ))

            pitcher_id = current_pitchers.get(half, "")
            batter_link = item.select_one("p.bb-liveText__batter a.bb-liveText__player")
            if not batter_link:
                continue
            m = re.search(r"/npb/player/(\d+)", batter_link.get("href", ""))
            if not m:
                continue
            batter_id = m.group(1)
            batter_name = batter_link.get_text(" ", strip=True)

            summaries = item.select("p.bb-liveText__summary:not(.bb-liveText__summary--change) span.bb-liveText__state")
            if not summaries:
                continue
            raw_outcome = summaries[-1].get_text(" ", strip=True)
            outcome = translate_npb_text(raw_outcome)

            # 打者打席
            if batter_id in tracked:
                key = f"NPB:{game_id}:PA:{raw_inning}:{batter_id}:{hashlib.sha1(raw_outcome.encode()).hexdigest()[:12]}"
                opp_pitcher = pitcher_names.get(pitcher_id, "")
                pa_title = f"{inning_str}｜面對 {opp_pitcher}" if opp_pitcher else f"{inning_str}｜打席結束"
                events.append(TrackingEvent(
                    key=key, league=League.NPB, game_id=game_id, player_id=batter_id,
                    kind=EventKind.PLATE_APPEARANCE, occurred_at=datetime.now(UTC),
                    title=pa_title, body=outcome, game_date=date.today().isoformat()
                ))

            # 投手面對打者
            if pitcher_id in tracked:
                key = f"NPB:{game_id}:PVB:{raw_inning}:{pitcher_id}:{batter_id}:{hashlib.sha1(raw_outcome.encode()).hexdigest()[:12]}"
                events.append(TrackingEvent(
                    key=key, league=League.NPB, game_id=game_id, player_id=pitcher_id,
                    kind=EventKind.PLATE_APPEARANCE, occurred_at=datetime.now(UTC),
                    title=f"{inning_str}｜面對 {batter_name}", body=outcome, game_date=date.today().isoformat()
                ))

    # 驗證事件：
    # 1. 陽 柏翔 在9回表有上場代走事件
    # 2. 陽 柏翔 在9回裏有守備替補事件
    # 3. 絕對不會有「陽 柏翔 | 面對 太田 光」或「面對 吉納 翼」等投手面對打者事件！
    assert len(events) == 2
    assert events[0].title == "九局上｜上場代走"
    assert "陽" in events[0].body
    assert events[1].title == "九局下｜守備替補/更換"
    assert "二壘" in events[1].body


def test_npb_pitcher_facing_batter_and_inning_end():
    text_html = """
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">8回表</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">投手交代:</span>
          <a class="bb-liveText__player" href="/npb/player/100/top">前任</a>
          <span class="bb-liveText__state">→</span>
          <a class="bb-liveText__player" href="/npb/player/2106890/top">孫易磊</a>
        </p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/1001/top">打者甲</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">三振 1アウト</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/1002/top">打者乙</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">ヒット 一塁</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">投手交代:</span>
          <a class="bb-liveText__player" href="/npb/player/2106890/top">孫易磊</a>
          <span class="bb-liveText__state">→</span>
          <a class="bb-liveText__player" href="/npb/player/200/top">後援投手</a>
        </p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/1003/top">打者丙</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">空振り三振 3アウト</span></p>
      </li>
      <footer class="bb-liveText__footer"></footer>
    </section>
    """
    stats_html = """
    <table class="bb-scoreTable">
      <tr><th>選手名</th><th>投球回</th><th>被安打</th><th>奪三振</th><th>与四球</th><th>与死球</th><th>失点</th><th>自責点</th><th>投球数</th></tr>
      <tr><td><a href="/npb/player/100/top">前任</a></td><td>7</td><td>4</td><td>5</td><td>1</td><td>0</td><td>1</td><td>1</td><td>90</td></tr>
      <tr><td><a href="/npb/player/2106890/top">孫易磊</a></td><td>0.1</td><td>1</td><td>1</td><td>0</td><td>0</td><td>0</td><td>0</td><td>12</td></tr>
      <tr><td><a href="/npb/player/200/top">後援</a></td><td>0.2</td><td>0</td><td>1</td><td>0</td><td>0</td><td>0</td><td>0</td><td>8</td></tr>
    </table>
    """
    import hashlib
    from tracker.models import EventKind, League, TrackingEvent
    from tracker.providers.npb_dict import INNINGS_MAP, REPLACE_MAP
    from datetime import date, datetime, UTC

    t_soup = BeautifulSoup(text_html, "html.parser")
    s_soup = BeautifulSoup(stats_html, "html.parser")
    tracked = {"2106890"}
    game_id = "test_game"

    pitcher_stats = {}
    pitcher_names = {}
    current_pitchers = {}
    for half_key, table in zip(["裏", "表"], s_soup.select("table.bb-scoreTable")):
        headers = [th.get_text(" ", strip=True) for th in table.find_all("tr")[0].find_all(["th", "td"])]
        for row in table.find_all("tr")[1:]:
            link = row.select_one('a[href*="/npb/player/"]')
            if link:
                m = re.search(r"/npb/player/(\d+)", link.get("href", ""))
                if m:
                    pid = m.group(1)
                    pitcher_names[pid] = link.get_text(" ", strip=True)
                    if half_key not in current_pitchers:
                        current_pitchers[half_key] = pid
                    pitcher_stats[pid] = dict(zip(headers, [td.get_text(" ", strip=True) for td in row.find_all(["th", "td"])]))

    events = []
    sections = t_soup.select("section.bb-liveText")
    for sec_idx, inning_section in enumerate(sections):
        inning_title = inning_section.select_one("h1.bb-liveText__inning")
        raw_inning = inning_title.get_text(" ", strip=True) if inning_title else "未知局數"
        inning_str = INNINGS_MAP.get(raw_inning, raw_inning)
        half = "裏" if "裏" in raw_inning else "表"
        inning_pitchers = set()

        for item in inning_section.select("li.bb-liveText__item"):
            change = item.select_one("p.bb-liveText__summary--change")
            if change:
                new_pitcher, subs = _parse_npb_change_summary(change)
                if new_pitcher:
                    pid, pname = new_pitcher
                    current_pitchers[half] = pid
                    pitcher_names[pid] = pname

            pitcher_id = current_pitchers.get(half, "")
            if pitcher_id:
                inning_pitchers.add(pitcher_id)

            batter_link = item.select_one("p.bb-liveText__batter a.bb-liveText__player")
            if not batter_link:
                continue
            m = re.search(r"/npb/player/(\d+)", batter_link.get("href", ""))
            if not m:
                continue
            batter_id = m.group(1)
            batter_name = batter_link.get_text(" ", strip=True)

            summaries = item.select("p.bb-liveText__summary:not(.bb-liveText__summary--change) span.bb-liveText__state")
            if not summaries:
                continue
            raw_outcome = summaries[-1].get_text(" ", strip=True)
            outcome = raw_outcome
            for jp_text, tw_text in REPLACE_MAP:
                outcome = outcome.replace(jp_text, tw_text)

            if pitcher_id in tracked:
                key = f"NPB:{game_id}:PVB:{raw_inning}:{pitcher_id}:{batter_id}:{hashlib.sha1(raw_outcome.encode()).hexdigest()[:12]}"
                events.append(TrackingEvent(
                    key=key, league=League.NPB, game_id=game_id, player_id=pitcher_id,
                    kind=EventKind.PLATE_APPEARANCE, occurred_at=datetime.now(UTC),
                    title=f"{inning_str}｜面對 {batter_name}", body=outcome, game_date=date.today().isoformat()
                ))

        inning_done = bool(inning_section.select_one("footer.bb-liveText__footer")) or "3アウト" in inning_section.get_text()
        if inning_done:
            for pid in inning_pitchers:
                if pid in tracked and pid in pitcher_stats:
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
                        kind=EventKind.PITCHING_INNING, occurred_at=datetime.now(UTC),
                        title=f"{inning_str}投球結束", body=body, game_date=date.today().isoformat()
                    ))

    # 孫易磊面對打者甲、乙 -> 2個 PA 事件
    pvb_events = [e for e in events if "面對" in e.title]
    assert len(pvb_events) == 2
    assert "面對 打者甲" in pvb_events[0].title
    assert "面對 打者乙" in pvb_events[1].title

    # 孫易磊在半局結束時產出 1 個投球結算事件
    ip_events = [e for e in events if e.kind == EventKind.PITCHING_INNING]
    assert len(ip_events) == 1
    assert ip_events[0].title == "八局上投球結束"
    assert "目前累計成績：0.1 局、1 安打、0 失分（0 責失）、0 保送、1 三振、12 球" in ip_events[0].body


def test_npb_batter_facing_pitcher():
    text_html = """
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">8回表</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">投手交代:</span>
          <a class="bb-liveText__player" href="/npb/player/100/top">前任</a>
          <span class="bb-liveText__state">→</span>
          <a class="bb-liveText__player" href="/npb/player/2106890/top">孫易磊</a>
        </p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/1001/top">打者甲</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">三振 1アウト</span></p>
      </li>
    </section>
    """
    stats_html = """
    <table class="bb-scoreTable">
      <tr><th>選手名</th><th>投球回</th></tr>
      <tr><td><a href="/npb/player/2106890/top">孫易磊</a></td><td>0.1</td></tr>
    </table>
    """
    from bs4 import BeautifulSoup
    import re
    import hashlib
    from tracker.models import EventKind, League, TrackingEvent
    from tracker.providers.npb_dict import INNINGS_MAP, translate_npb_text
    from datetime import datetime, UTC, date

    t_soup = BeautifulSoup(text_html, "html.parser")
    s_soup = BeautifulSoup(stats_html, "html.parser")
    tracked = {"1001"}  # 追蹤打者甲
    game_id = "test_game_batter"

    pitcher_names = {}
    current_pitchers = {}
    for half_key, table in zip(["裏", "表"], s_soup.select("table.bb-scoreTable")):
        for row in table.find_all("tr")[1:]:
            link = row.select_one('a[href*="/npb/player/"]')
            if link:
                m = re.search(r"/npb/player/(\d+)", link.get("href", ""))
                if m:
                    pid = m.group(1)
                    pitcher_names[pid] = link.get_text(" ", strip=True)
                    if half_key not in current_pitchers:
                        current_pitchers[half_key] = pid

    events = []
    for inning_section in t_soup.select("section.bb-liveText"):
        raw_inning = "8回表"
        inning_str = INNINGS_MAP.get(raw_inning, raw_inning)
        half = "表"
        for item in inning_section.select("li.bb-liveText__item"):
            change = item.select_one("p.bb-liveText__summary--change")
            if change:
                new_pitcher, subs = _parse_npb_change_summary(change)
                if new_pitcher:
                    pid, pname = new_pitcher
                    current_pitchers[half] = pid
                    pitcher_names[pid] = pname

            pitcher_id = current_pitchers.get(half, "")
            batter_link = item.select_one("p.bb-liveText__batter a.bb-liveText__player")
            batter_id = "1001"
            raw_outcome = "三振 1アウト"
            outcome = translate_npb_text(raw_outcome)

            if batter_id in tracked:
                key = f"NPB:{game_id}:PA:{raw_inning}:{batter_id}:{hashlib.sha1(raw_outcome.encode()).hexdigest()[:12]}"
                opp_pitcher = pitcher_names.get(pitcher_id, "")
                pa_title = f"{inning_str}｜面對 {opp_pitcher}" if opp_pitcher else f"{inning_str}｜打席結束"
                events.append(TrackingEvent(
                    key=key, league=League.NPB, game_id=game_id, player_id=batter_id,
                    kind=EventKind.PLATE_APPEARANCE, occurred_at=datetime.now(UTC),
                    title=pa_title, body=outcome, game_date=date.today().isoformat()
                ))

    assert len(events) == 1
    assert events[0].title == "八局上｜面對 孫易磊"
    assert events[0].body == "三振 1出局"


def test_npb_dict_translations():
    from tracker.providers.npb_dict import translate_npb_text

    # 1. 跑者與全壘打、左中外野、三分砲、比分隊名縮寫
    t1 = translate_npb_text("ランナー一、三塁の0-2から左中間への3ランホームラン！ ヤ 0-7 西")
    assert "跑者一、三壘" in t1
    assert "左中外野方向的三分全壘打" in t1
    assert "養樂多 0-7 西武" in t1

    # 2. 偏低直球與中外野飛球
    t2 = translate_npb_text("低めの真っ直ぐを打つもセンターフライ 3アウト")
    assert "偏低的直球擊出但形成中外野飛球" in t2
    assert "3出局" in t2

    # 3. 偏高球與擊出但形成
    t3 = translate_npb_text("高めの球を打つもレフトフライ 3アウト")
    assert "對於偏高球擊出但形成左外野飛球" in t3

    # 4. 右外野看台全壘打
    t4 = translate_npb_text("ライトスタンドへのホームラン！ ヤ 3-1 西")
    assert "右外野看台方向的全壘打" in t4
    assert "養樂多 3-1 西武" in t4

    # 5. 教練走上投手丘
    t5 = translate_npb_text("－ヤクルト:コーチマウンドへむかう－")
    assert "－養樂多:教練走上投手丘－" == t5

    # 6. 球數與站著不動三振
    t6 = translate_npb_text("カウント1-2から見逃し三振 3アウト")
    assert "球數1-2，站著不動被三振 3出局" == t6

    # 7. 空振與避免撞詞 (吞下揮棒落空的三振)
    t7 = translate_npb_text("カウント2-2から空振り三振 3アウト")
    assert "球數2-2，揮棒落空被三振 3出局" == t7

    t7_ext = translate_npb_text("カウント2-2から空振り三振を喫する 3アウト")
    assert "吞下揮棒落空的三振" in t7_ext
    assert "揮空被三振" not in t7_ext


def test_npb_dict_no_harmful_collisions():
    from tracker.providers.npb_dict import REPLACE_MAP

    harmful = []
    for i, (jp1, tw1) in enumerate(REPLACE_MAP):
        for j in range(i + 1, len(REPLACE_MAP)):
            jp2, tw2 = REPLACE_MAP[j]
            if jp2 in tw1 and jp2 != tw2:
                harmful.append((jp1, tw1, jp2, tw2))

    assert len(harmful) == 0, f"Found harmful dictionary replacement collisions: {harmful}"


def test_npb_premature_final_prevented_when_other_game_finished():
    """
    測試：當頁面頂部導覽列含有其他已結束比賽的「試合終了」時，本場比賽不得被誤判為已結束。
    """
    # 模擬 17:00 開始的比賽，在 15:14 時頁面頂部出現了 13:00 比賽的「試合終了」
    text_html = """
    <header class="bb-modCommon03">
      <nav class="bb-scoreList">
        <a class="bb-scoreList__state" href="/npb/game/2021039357/">試合終了</a>
      </nav>
    </header>
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">試合前情報</h1>
      <p class="bb-liveText__detail">先発ピッチャー予告</p>
    </section>
    """
    soup = BeautifulSoup(text_html, "html.parser")

    final = False
    for sec in soup.select("section.bb-liveText"):
        for state in sec.select("p.bb-liveText__summary span.bb-liveText__state"):
            text_val = state.get_text(strip=True)
            if "試合終了" in text_val or "コールド" in text_val:
                final = True
                break
        if final:
            break

    # 確保不會因為頂部導覽列有其他場次結束而被誤判為 True
    assert final is False


def test_npb_real_final_detected():
    """
    測試：當本場比賽在 liveText 或主比分卡中真正出現「試合終了」時，能正確判定已結束。
    """
    # 情況 1：liveText 最後一局出現試合終了
    text_html_1 = """
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">9回表</h1>
      <p class="bb-liveText__summary"><span class="bb-liveText__state">ファーストゴロ 3アウト</span></p>
      <p class="bb-liveText__summary"><span class="bb-liveText__state">試合終了</span></p>
    </section>
    """
    soup_1 = BeautifulSoup(text_html_1, "html.parser")
    final_1 = False
    for sec in soup_1.select("section.bb-liveText"):
        for state in sec.select("p.bb-liveText__summary span.bb-liveText__state"):
            if "試合終了" in state.get_text() or "コールド" in state.get_text():
                final_1 = True
                break
    assert final_1 is True

    # 情況 2：主比分卡片 (.bb-gameCard) 出現試合終了
    index_html = """
    <div class="bb-gameCard">
      <p class="bb-gameCard__state">試合終了</p>
    </div>
    """
    soup_2 = BeautifulSoup(index_html, "html.parser")
    card_state = soup_2.select_one(".bb-gameCard .bb-gameCard__state")
    final_2 = bool(card_state and any(k in card_state.get_text() for k in ["試合終了", "コールド"]))
    assert final_2 is True


def test_npb_pitcher_replaced_by_mound_syntax():
    """
    測試日職速報常見句型「ピッチャー A に代わって B がマウンドにあがる」能否正確切換新投手。
    """
    from tracker.providers.npb import _parse_npb_change_summary

    h1 = """
    <p class="bb-liveText__summary bb-liveText__summary--change">
      <span class="bb-liveText__state">ピッチャー</span>
      <a class="bb-liveText__player" href="/npb/player/2106890/top">孫</a>
      <span class="bb-liveText__state">に代わって</span>
      <a class="bb-liveText__player" href="/npb/player/1000164/top">島本</a>
      <span class="bb-liveText__state">がマウンドにあがる</span>
    </p>
    """
    soup1 = BeautifulSoup(h1, "html.parser")
    p1, subs1 = _parse_npb_change_summary(soup1.find("p"))
    assert p1 == ("1000164", "島本")
    assert any(s[0] == "1000164" and s[2] == "PITCHER" for s in subs1)

    h2 = """
    <p class="bb-liveText__summary bb-liveText__summary--change">
      <span class="bb-liveText__state">ピッチャー</span>
      <a class="bb-liveText__player" href="/npb/player/1000164/top">島本</a>
      <span class="bb-liveText__state">に代わって</span>
      <a class="bb-liveText__player" href="/npb/player/1600133/top">堀</a>
      <span class="bb-liveText__state">がマウンドにあがる　守備交代:センター</span>
      <a class="bb-liveText__player" href="/npb/player/2108090/top">カストロ</a>
    </p>
    """
    soup2 = BeautifulSoup(h2, "html.parser")
    p2, subs2 = _parse_npb_change_summary(soup2.find("p"))
    assert p2 == ("1600133", "堀")
    assert any(s[0] == "2108090" and s[2] == "DEFENSE" for s in subs2)


def test_npb_bat_broken_translation():
    from tracker.providers.npb_dict import translate_npb_text

    raw = "バットを折りながらもライトへヒットを放つ 一、二塁"
    res = translate_npb_text(raw)
    assert "バット" not in res
    assert "折り" not in res
    assert "打斷球棒依然" in res or "斷棒但仍" in res
    assert "右外野方向" in res
    assert "安打" in res
    assert "一、二壘" in res


@pytest.mark.asyncio
async def test_npb_live_reversed_sections_chronological_order():
    from tracker.providers.npb import NpbProvider
    from unittest.mock import patch
    from datetime import date

    # 模擬 Yahoo 即時賽況倒序呈現：第9局在前面，第1局在後面
    reversed_text_html = """
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">9回表</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">投手交代:</span>
          <a class="bb-liveText__player" href="/npb/player/100/top">先發</a>
          <span class="bb-liveText__state">→</span>
          <a class="bb-liveText__player" href="/npb/player/2106890/top">孫易磊</a>
        </p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/501/top">打者九</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">空振り三振 3アウト</span></p>
      </li>
      <footer class="bb-liveText__footer">得点0ヒット0四死球0</footer>
    </section>
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">8回表</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/502/top">打者八</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">ショートゴロ 3アウト</span></p>
      </li>
      <footer class="bb-liveText__footer">得点0ヒット0四死球0</footer>
    </section>
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">1回表</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/503/top">打者一</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">三振 3アウト</span></p>
      </li>
      <footer class="bb-liveText__footer">得点0ヒット0四死球0</footer>
    </section>
    """
    stats_html = """
    <table class="bb-scoreTable">
      <tr><th>選手名</th><th>投球回</th><th>被安打</th><th>奪三振</th><th>与四球</th><th>与死球</th><th>失点</th><th>自責点</th><th>投球数</th></tr>
      <tr><td><a href="/npb/player/200/top">對方先發</a></td><td>8</td><td>4</td><td>5</td><td>1</td><td>0</td><td>1</td><td>1</td><td>90</td></tr>
    </table>
    <table class="bb-scoreTable">
      <tr><th>選手名</th><th>投球回</th><th>被安打</th><th>奪三振</th><th>与四球</th><th>与死球</th><th>失点</th><th>自責点</th><th>投球数</th></tr>
      <tr><td><a href="/npb/player/100/top">先發</a></td><td>8</td><td>4</td><td>5</td><td>1</td><td>0</td><td>1</td><td>1</td><td>90</td></tr>
      <tr><td><a href="/npb/player/2106890/top">孫易磊</a></td><td>1</td><td>0</td><td>1</td><td>0</td><td>0</td><td>0</td><td>0</td><td>15</td></tr>
    </table>
    """
    provider = NpbProvider(None)
    schedule_soup = BeautifulSoup('<a href="/npb/game/999999/index">Game</a>', "html.parser")
    t_soup = BeautifulSoup(reversed_text_html, "html.parser")
    s_soup = BeautifulSoup(stats_html, "html.parser")

    async def mock_html(path):
        if "schedule" in path or path == "/npb/":
            return schedule_soup
        if "text" in path:
            return t_soup
        if "stats" in path:
            return s_soup
        return BeautifulSoup("<html></html>", "html.parser")

    with patch.object(provider, "_html", side_effect=mock_html), \
         patch.object(provider, "_season_stats", return_value=""):
        events = await provider.collect_events(["2106890"], date.today(), date.today())
        # 孫易磊只在第 9 局上場，絕不能出現 1 局上或 8 局上的面對打者通知
        pvb_events = [e for e in events if "面對" in e.title]
        assert len(pvb_events) == 1
        assert "九局上" in pvb_events[0].title
        assert "打者九" in pvb_events[0].title
        # 投球結束通知也僅能屬於九局上
        ip_events = [e for e in events if "投球結束" in e.title]
        assert len(ip_events) == 1
        assert "九局上" in ip_events[0].title


@pytest.mark.asyncio
async def test_npb_daily_summary_date_filtering():
    from tracker.providers.npb import NpbProvider
    from tracker.models import Player, League
    from unittest.mock import patch
    from datetime import date

    provider = NpbProvider(None)
    player = Player(League.NPB, "1660299", "林安可")

    # 模擬 2026-09-01 的比賽 stats 與 2026-09-02 的比賽 stats
    game_0901_stats = """
    <html><head><title>2026年9月1日 羅德vs.西武 試合出場成績 - プロ野球 - スポーツナビ</title></head>
    <body>
      <table>
        <tr><th>選手名</th><th>打数</th><th>安打</th><th>本塁打</th><th>得点</th><th>打点</th><th>四球</th><th>死球</th><th>三振</th><th>盗塁</th></tr>
        <tr><td><a href="/npb/player/1660299/top">林安可</a></td><td>3</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>1</td><td>0</td></tr>
      </table>
      <div class="bb-gameCard"><div class="bb-gameCard__state">試合終了</div></div>
    </body></html>
    """

    async def mock_html(path):
        if "schedule" in path or path == "/npb/":
            return BeautifulSoup('<a href="/npb/game/2021039365/index">Game 0901</a>', "html.parser")
        if "2021039365" in path:
            return BeautifulSoup(game_0901_stats, "html.parser")
        return BeautifulSoup("<html></html>", "html.parser")

    with patch.object(provider, "_html", side_effect=mock_html), \
         patch.object(provider, "_season_stats", return_value="打者：出賽 64｜打席 223"):
        # 查詢 2026-09-02：該比賽為 2026-09-01，應被過濾，不應回傳出賽成績
        summary_0902 = await provider.daily_summary(player, date(2026, 9, 2), date(2026, 9, 2))
        assert "這段期間沒有可用的出賽紀錄" in summary_0902
        assert "3 打數、0 安打" not in summary_0902

        # 查詢 2026-09-01：該比賽日期相符，應正確回傳出賽成績
        summary_0901 = await provider.daily_summary(player, date(2026, 9, 1), date(2026, 9, 1))
        assert "3 打數、0 安打" in summary_0901


@pytest.mark.asyncio
async def test_npb_pitcher_exit_on_inning_done():
    from datetime import date
    from unittest.mock import MagicMock, patch
    from tracker.models import Player, League, EventKind
    from tracker.providers.npb import NpbProvider
    provider = NpbProvider(session=MagicMock())
    player = Player(League.NPB, "2106890", "孫易磊", "火腿")

    schedule_html = '<a href="/npb/game/2026090301/index">Game</a>'

    # 8回表：孫易磊先投，後被換下（後援投手接替），該局包含 3アウト 與 footer（換局完成）
    text_html = """
    <html><head><title>2026年9月3日 比賽</title></head><body>
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">8回表</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">投手交代:</span>
          <a class="bb-liveText__player" href="/npb/player/100/top">前任</a>
          <span class="bb-liveText__state">→</span>
          <a class="bb-liveText__player" href="/npb/player/2106890/top">孫易磊</a>
        </p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/1001/top">打者甲</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">三振 1アウト</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">投手交代:</span>
          <a class="bb-liveText__player" href="/npb/player/2106890/top">孫易磊</a>
          <span class="bb-liveText__state">→</span>
          <a class="bb-liveText__player" href="/npb/player/200/top">後援投手</a>
        </p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/1002/top">打者乙</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">空振り三振 3アウト</span></p>
      </li>
      <footer class="bb-liveText__footer"></footer>
    </section>
    """

    stats_html = """
    <html><body>
      <table class="bb-scoreTable">
        <tr><th>選手名</th><th>投球回</th><th>被安打</th><th>奪三振</th><th>与四球</th><th>与死球</th><th>失点</th><th>自責点</th><th>投球数</th></tr>
      </table>
      <table class="bb-scoreTable">
        <tr><th>選手名</th><th>投球回</th><th>被安打</th><th>奪三振</th><th>与四球</th><th>与死球</th><th>失点</th><th>自責点</th><th>投球数</th></tr>
        <tr><td><a href="/npb/player/2106890/top">孫易磊</a></td><td>0.1</td><td>0</td><td>1</td><td>0</td><td>0</td><td>0</td><td>0</td><td>6</td></tr>
        <tr><td><a href="/npb/player/200/top">後援投手</a></td><td>0.2</td><td>0</td><td>1</td><td>0</td><td>0</td><td>0</td><td>0</td><td>8</td></tr>
      </table>
      <div class="bb-gameCard"><div class="bb-gameCard__state">試合中</div></div>
    </body></html>
    """

    async def mock_html(path):
        if "schedule" in path or path == "/npb/":
            return BeautifulSoup(schedule_html, "html.parser")
        if "text" in path:
            return BeautifulSoup(text_html, "html.parser")
        if "stats" in path:
            return BeautifulSoup(stats_html, "html.parser")
        return BeautifulSoup("<html></html>", "html.parser")

    with patch.object(provider, "_html", side_effect=mock_html):
        events = await provider.collect_events([player], start=date(2026, 9, 3), end=date(2026, 9, 3))
        exit_events = [e for e in events if e.kind == EventKind.PITCHING_EXIT]
        assert len(exit_events) == 1
        assert exit_events[0].title == "投球工作結束（退場）"
        assert "0.1 局" in exit_events[0].body
        assert "1 三振" in exit_events[0].body
        assert "6 球" in exit_events[0].body


@pytest.mark.asyncio
async def test_npb_live_reversed_items_with_mid_inning_pitcher_change():
    """
    重現 2026-09-05 孫易磊 8局下登板、中途換下、9局下由後援接替之真實即時情境：
    1. 8局下即時項目為倒序 ([5, 4, 3, 2, 1])，第 1 項含「投手交代: 先發 -> 孫易磊」，第 5 項含「孫 に代わって 堀」
    2. 9局下即時項目為倒序 ([3, 2, 1])，第 1 項含「堀 に代わって 柳川」
    3. 驗證孫易磊的通知順序：
       - 八局下｜登板投球
       - 八局下｜面對 打者1 (宗山)
       - 八局下｜面對 打者2 (馬卡斯)
       - 八局下｜面對 打者3 (安田)
       - 八局下｜面對 打者4 (辰己)
       - 投球工作結束（退場） (8局結束後發送)
       - 絕不產生 9 局下的面對打者事件或投球結束事件！
       - 所有事件的時間戳 (occurred_at) 嚴格單調遞增！
    """
    from datetime import date
    from unittest.mock import MagicMock, patch
    from tracker.models import Player, League, EventKind
    from tracker.providers.npb import NpbProvider

    provider = NpbProvider(session=MagicMock())
    player = Player(League.NPB, "2106890", "孫易磊", "火腿")

    schedule_html = '<a href="/npb/game/2021039381/index">Game</a>'

    # 模擬 8局下 與 9局下 即時賽況（項目在 HTML 中為倒序呈現）
    text_html = """
    <html><head><title>2026年9月5日 樂天vs日本火腿</title></head><body>
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">9回裏</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">3：</p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/303/top">打者九3</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">空振り三振 3アウト</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">2：</p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/302/top">打者九2</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">レフトフライ 2アウト</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">1：</p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/301/top">打者九1</a></p>
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">ピッチャー</span>
          <a class="bb-liveText__player" href="/npb/player/1600133/top">堀</a>
          <span class="bb-liveText__state">に代わって</span>
          <a class="bb-liveText__player" href="/npb/player/2103635/top">柳川</a>
          <span class="bb-liveText__state">がマウンドにあがる</span>
        </p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">ライトフライ 1アウト</span></p>
      </li>
      <footer class="bb-liveText__footer">
        <table class="bb-liveTextTable"><tr><td class="bb-liveTextTable__data">0</td></tr></table>
      </footer>
    </section>

    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">8回裏</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">6：</p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/206/top">打者6</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">ファーストフライ 3アウト</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">5：</p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/205/top">打者5</a></p>
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">ピッチャー</span>
          <a class="bb-liveText__player" href="/npb/player/2106890/top">孫</a>
          <span class="bb-liveText__state">に代わって</span>
          <a class="bb-liveText__player" href="/npb/player/1600133/top">堀</a>
          <span class="bb-liveText__state">がマウンドにあがる</span>
        </p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">空振り三振 2アウト</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">4：</p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/204/top">辰己 涼介</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">フォアボールを選ぶ 一二塁</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">3：</p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/203/top">YG安田</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">センターへのタイムリーヒット 楽 2-5 日 一塁</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">2：</p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/202/top">マッカスカー</a></p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">センターフライ 1アウト</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">1：</p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/201/top">宗山 塁</a></p>
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">投手交代:</span>
          <a class="bb-liveText__player" href="/npb/player/100/top">伊藤</a>
          <span class="bb-liveText__state">→</span>
          <a class="bb-liveText__player" href="/npb/player/2106890/top">孫</a>
        </p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">ライトへのヒットで出塁 一塁</span></p>
      </li>
      <footer class="bb-liveText__footer">
        <table class="bb-liveTextTable"><tr><td class="bb-liveTextTable__data">1</td></tr></table>
      </footer>
    </section>
    </body></html>
    """

    stats_html = """
    <html><body>
      <table class="bb-scoreTable">
        <tr><th>選手名</th><th>投球回</th><th>被安打</th><th>奪三振</th><th>与四球</th><th>与死球</th><th>失点</th><th>自責点</th><th>投球数</th></tr>
        <tr><td><a href="/npb/player/100/top">伊藤</a></td><td>7.0</td><td>6</td><td>7</td><td>0</td><td>0</td><td>1</td><td>1</td><td>98</td></tr>
        <tr><td><a href="/npb/player/2106890/top">孫 易磊</a></td><td>0.1</td><td>2</td><td>0</td><td>1</td><td>0</td><td>1</td><td>1</td><td>17</td></tr>
        <tr><td><a href="/npb/player/1600133/top">堀 瑞輝</a></td><td>0.2</td><td>0</td><td>1</td><td>0</td><td>0</td><td>0</td><td>0</td><td>8</td></tr>
        <tr><td><a href="/npb/player/2103635/top">柳川 大晟</a></td><td>1.0</td><td>0</td><td>1</td><td>0</td><td>0</td><td>0</td><td>0</td><td>14</td></tr>
      </table>
      <table class="bb-scoreTable">
        <tr><th>選手名</th><th>投球回</th><th>被安打</th><th>奪三振</th><th>与四球</th><th>与死球</th><th>失点</th><th>自責点</th><th>投球数</th></tr>
      </table>
      <div class="bb-gameCard"><div class="bb-gameCard__state">試合終了</div></div>
    </body></html>
    """

    index_html = '<div class="bb-gameCard"><p class="bb-gameCard__state">試合終了</p></div>'

    async def mock_html(path):
        if "schedule" in path or path == "/npb/":
            return BeautifulSoup(schedule_html, "html.parser")
        if "text" in path:
            return BeautifulSoup(text_html, "html.parser")
        if "stats" in path:
            return BeautifulSoup(stats_html, "html.parser")
        if "index" in path:
            return BeautifulSoup(index_html, "html.parser")
        return BeautifulSoup("<html></html>", "html.parser")

    with patch.object(provider, "_html", side_effect=mock_html), \
         patch.object(provider, "_season_stats", return_value="投手：出賽 14｜先發 2｜24 局｜2勝-1敗"):
        events = await provider.collect_events([player], start=date(2026, 9, 5), end=date(2026, 9, 5))

        # 檢驗事件種類與名稱
        titles = [e.title for e in events]
        assert titles == [
            "八局下｜登板投球",
            "八局下｜面對 宗山 塁",
            "八局下｜面對 マッカスカー",
            "八局下｜面對 YG安田",
            "八局下｜面對 辰己 涼介",
            "投球工作結束（退場）",
            "終場成績",
        ]

        # 檢驗時間戳嚴格單調遞增
        timestamps = [e.occurred_at for e in events]
        for i in range(len(timestamps) - 1):
            assert timestamps[i] < timestamps[i + 1]

        # 檢驗退場內容數據
        exit_event = events[5]
        assert exit_event.kind == EventKind.PITCHING_EXIT
        assert "0.1 局" in exit_event.body
        assert "2 安打" in exit_event.body
        assert "1 失分（1 責失）" in exit_event.body
        assert "1 保送" in exit_event.body
        assert "17 球" in exit_event.body


@pytest.mark.asyncio
async def test_npb_ongoing_inning_no_premature_ip_end():
    """
    測試進行中的半局（footer 得分為 '-' 且未滿 3 出局）不會提早觸發投球結束通知。
    """
    from datetime import date
    from unittest.mock import MagicMock, patch
    from tracker.models import Player, League
    from tracker.providers.npb import NpbProvider

    provider = NpbProvider(session=MagicMock())
    player = Player(League.NPB, "2106890", "孫易磊", "火腿")

    schedule_html = '<a href="/npb/game/2021039381/index">Game</a>'

    # 進行中的 8 局下（只有 1 個打席，得分為 '-'，未有 3 出局）
    text_html = """
    <html><head><title>2026年9月5日 樂天vs日本火腿</title></head><body>
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">8回裏</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">1：</p>
        <p class="bb-liveText__batter"><a class="bb-liveText__player" href="/npb/player/201/top">宗山 塁</a></p>
        <p class="bb-liveText__summary bb-liveText__summary--change">
          <span class="bb-liveText__state">投手交代:</span>
          <a class="bb-liveText__player" href="/npb/player/100/top">伊藤</a>
          <span class="bb-liveText__state">→</span>
          <a class="bb-liveText__player" href="/npb/player/2106890/top">孫</a>
        </p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">ライトへのヒットで出壘 一壘</span></p>
      </li>
      <footer class="bb-liveText__footer">
        <table class="bb-liveTextTable"><tr><td class="bb-liveTextTable__data">-</td></tr></table>
      </footer>
    </section>
    </body></html>
    """

    stats_html = """
    <html><body>
      <table class="bb-scoreTable">
        <tr><th>選手名</th><th>投球回</th><th>被安打</th><th>奪三振</th><th>与四球</th><th>与死球</th><th>失点</th><th>自責点</th><th>投球数</th></tr>
        <tr><td><a href="/npb/player/100/top">伊藤</a></td><td>7.0</td><td>6</td><td>7</td><td>0</td><td>0</td><td>1</td><td>1</td><td>98</td></tr>
        <tr><td><a href="/npb/player/2106890/top">孫 易磊</a></td><td>0.0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>
      </table>
      <table class="bb-scoreTable">
        <tr><th>選手名</th><th>投球回</th></tr>
      </table>
      <div class="bb-gameCard"><div class="bb-gameCard__state">試合中</div></div>
    </body></html>
    """

    async def mock_html(path):
        if "schedule" in path or path == "/npb/":
            return BeautifulSoup(schedule_html, "html.parser")
        if "text" in path:
            return BeautifulSoup(text_html, "html.parser")
        if "stats" in path:
            return BeautifulSoup(stats_html, "html.parser")
        return BeautifulSoup("<html></html>", "html.parser")

    with patch.object(provider, "_html", side_effect=mock_html):
        events = await provider.collect_events([player], start=date(2026, 9, 5), end=date(2026, 9, 5))
        # 進行中只有登板與面對打席事件，絕對不能有「投球結束」或「退場」事件
        assert len(events) == 2
        assert events[0].title == "八局下｜登板投球"
        assert events[1].title == "八局下｜面對 宗山 塁"
        assert not any("投球結束" in e.title for e in events)
        assert not any("退場" in e.title for e in events)


@pytest.mark.asyncio
async def test_npb_on_deck_event_generation():
    from datetime import date
    from unittest.mock import MagicMock, patch
    from tracker.models import Player, League, EventKind
    from tracker.providers.npb import NpbProvider

    provider = NpbProvider(session=MagicMock())
    player = Player(League.NPB, "1660299", "林安可", "西武")

    schedule_html = '<a href="/npb/game/2026091501/index">Game</a>'

    # 1局上：1番打者一打擊時（0出局），次打者為2番林安可
    text_html = """
    <html><head><title>2026年9月15日 比賽</title></head><body>
    <section class="bb-liveText">
      <h1 class="bb-liveText__inning">1回表</h1>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">1：</p>
        <p class="bb-liveText__batter">
          <span class="bb-liveText__order">1番</span>
          <a class="bb-liveText__player" href="/npb/player/1001/top">打者一</a>
          <span class="bb-liveText__state">無死走者なし</span>
        </p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">ライトへのヒット 一塁</span></p>
      </li>
      <li class="bb-liveText__item">
        <p class="bb-liveText__number">2：</p>
        <p class="bb-liveText__batter">
          <span class="bb-liveText__order">2番</span>
          <a class="bb-liveText__player" href="/npb/player/1660299/top">林安可</a>
          <span class="bb-liveText__state">無死一塁</span>
        </p>
        <p class="bb-liveText__summary"><span class="bb-liveText__state">ライトスタンドへの2ランホームラン！</span></p>
      </li>
      <footer class="bb-liveText__footer">
        <table class="bb-liveTextTable"><tr><td class="bb-liveTextTable__data">-</td></tr></table>
      </footer>
    </section>
    </body></html>
    """

    stats_html = """
    <html><body>
      <table class="bb-scoreTable">
        <tr><th>選手名</th><th>打数</th></tr>
        <tr><td><a href="/npb/player/1001/top">打者一</a></td><td>1</td></tr>
        <tr><td><a href="/npb/player/1660299/top">林安可</a></td><td>1</td></tr>
      </table>
      <table class="bb-scoreTable">
        <tr><th>選手名</th><th>投球回</th></tr>
        <tr><td><a href="/npb/player/999/top">對方投手</a></td><td>1.0</td></tr>
      </table>
      <div class="bb-gameCard"><div class="bb-gameCard__state">試合中</div></div>
    </body></html>
    """

    async def mock_html(path):
        if "schedule" in path or path == "/npb/":
            return BeautifulSoup(schedule_html, "html.parser")
        if "text" in path:
            return BeautifulSoup(text_html, "html.parser")
        if "stats" in path:
            return BeautifulSoup(stats_html, "html.parser")
        return BeautifulSoup("<html></html>", "html.parser")

    with patch.object(provider, "_html", side_effect=mock_html):
        events = await provider.collect_events([player], start=date(2026, 9, 15), end=date(2026, 9, 15))
        assert len(events) == 2

        on_deck = events[0]
        assert on_deck.kind == EventKind.ON_DECK
        assert on_deck.player_id == "1660299"
        assert on_deck.title == "一局上｜即將上場打擊"
        assert "0 出局" in on_deck.body
        assert "下一棒即將輪到打擊" in on_deck.body

        pa = events[1]
        assert pa.kind == EventKind.PLATE_APPEARANCE
        assert pa.player_id == "1660299"
        assert "全壘打" in pa.body
        assert on_deck.occurred_at < pa.occurred_at







