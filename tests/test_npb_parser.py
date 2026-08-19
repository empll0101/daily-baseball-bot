from tracker.providers.npb import _parse_npb_ip_outs, _parse_npb_walks
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
