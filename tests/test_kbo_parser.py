from tracker.providers.kbo import KboProvider, _translate_kbo
from tracker.models import EventKind, League, Player


def test_kbo_translation():
    assert _translate_kbo("강백호 : 삼진 아웃") == "강백호 : 三振出局"
    assert _translate_kbo("김도영 : 좌전 안타") == "김도영 : 左外野方向 安打"
    assert _translate_kbo("최인호 : 우월 솔로홈런") == "최인호 : 우월 陽春全壘打"
    assert _translate_kbo("박재현 : 2루수 땅볼 아웃") == "박재현 : 二壘手 滾地球出局"


def test_kbo_parse_relays_and_record():
    provider = KboProvider(session=None)  # type: ignore

    # Test parse relays
    relays = [
        {
            "seqno": 101,
            "text": "김도영 : 중전 안타",
            "currentGameState": {"batter": "52600", "pitcher": "56719"},
            "currentPlayersInfo": {
                "home": {
                    "playerType": "pitcher",
                    "currentGamePlayerStats": {
                        "inn": "5.0",
                        "hit": 3,
                        "run": 1,
                        "bb": 2,
                        "kk": 6,
                        "strikeCount": 50,
                        "ballCount": 25,
                    },
                }
            },
        }
    ]

    events = provider._parse_relays(relays, {"52600", "56719"}, "20260818HTHH02026")
    assert len(events) == 2

    pa_event = next(e for e in events if e.kind == EventKind.PLATE_APPEARANCE)
    assert pa_event.player_id == "52600"
    assert "中外野方向 安打" in pa_event.body

    ip_event = next(e for e in events if e.kind == EventKind.PITCHING_INNING)
    assert ip_event.player_id == "56719"
    assert "5.0 局" in ip_event.body
    assert "6 三振" in ip_event.body


def test_kbo_parse_final_record():
    provider = KboProvider(session=None)  # type: ignore

    record = {
        "gameInfo": {"status": "RESULT"},
        "battersBoxscore": {
            "away": [
                {
                    "playerCode": "52600",
                    "ab": 4,
                    "hit": 2,
                    "hr": 1,
                    "run": 2,
                    "rbi": 3,
                    "bb": 1,
                    "kk": 0,
                    "sb": 1,
                }
            ]
        },
        "pitchersBoxscore": {
            "home": [
                {
                    "pcode": "56719",
                    "inn": "6.0",
                    "hit": 4,
                    "r": 2,
                    "er": 1,
                    "bb": 2,
                    "kk": 7,
                    "bf": 95,
                    "wls": "승",
                }
            ]
        },
    }

    events = provider._parse_record(record, {"52600", "56719"}, "20260818HTHH02026")
    assert len(events) == 2

    batter_final = next(e for e in events if e.player_id == "52600")
    assert batter_final.kind == EventKind.GAME_FINAL
    assert "4 打數" in batter_final.body
    assert "2 安打" in batter_final.body
    assert "1 全壘打" in batter_final.body

    pitcher_final = next(e for e in events if e.player_id == "56719")
    assert pitcher_final.kind == EventKind.GAME_FINAL
    assert "6.0 局" in pitcher_final.body
    assert "1 自責分" in pitcher_final.body
    assert "（勝投）" in pitcher_final.body
