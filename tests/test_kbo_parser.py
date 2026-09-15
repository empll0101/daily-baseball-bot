import pytest
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
    assert len(events) == 3

    pa_event = next(e for e in events if e.kind == EventKind.PLATE_APPEARANCE and e.player_id == "52600")
    assert pa_event.player_id == "52600"
    assert "中外野方向 安打" in pa_event.body

    pvb_event = next(e for e in events if e.kind == EventKind.PLATE_APPEARANCE and e.player_id == "56719")
    assert "面對 김도영" in pvb_event.title
    assert "中外野方向 安打" in pvb_event.body

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


@pytest.mark.asyncio
async def test_kbo_collect_events_category_id():
    from datetime import date
    from unittest.mock import patch

    provider = KboProvider(session=None)  # type: ignore

    mock_schedule = {
        "result": {
            "games": [
                {
                    "gameId": "20260901HHKT02026",
                    "categoryId": "kbo",
                    "gameDate": "2026-09-01",
                },
                {
                    "gameId": "20260901OTHER1",
                    "categoryId": "other",
                    "gameDate": "2026-09-01",
                }
            ]
        }
    }

    mock_record = {
        "result": {
            "recordData": {
                "gameInfo": {"status": "RESULT"},
                "pitchersBoxscore": {
                    "away": [
                        {
                            "pcode": "56719",
                            "inn": "5",
                            "hit": 3,
                            "r": 1,
                            "er": 1,
                            "bb": 1,
                            "kk": 5,
                            "bf": 80,
                            "wls": "승",
                        }
                    ]
                }
            }
        }
    }

    async def mock_get_json(url):
        if "schedule/games?" in url:
            return mock_schedule
        if "record" in url:
            return mock_record
        return {}

    with patch.object(provider, "_get_json", side_effect=mock_get_json), \
         patch.object(provider, "_season_stats", return_value="投手：出賽 20｜100 局"):
        events = await provider.collect_events(["56719"], date(2026, 9, 1), date(2026, 9, 1))
        assert len(events) == 1
        assert events[0].player_id == "56719"
        assert events[0].game_date == "2026-09-01"
        assert "5 局" in events[0].body
        assert "（勝投）" in events[0].body


def test_kbo_pitcher_pvb_every_plate_appearance():
    provider = KboProvider(session=None)  # type: ignore

    # 模擬 Naver Sports 官方 textOptions 結構
    relays = [
        {
            "inn": 5,
            "homeOrAway": 0,
            "title": "5회초 공격",
            "textOptions": [
                {
                    "seqno": 201,
                    "text": "강백호 : 헛스윙 삼진 아웃",
                    "type": 13,
                    "currentGameState": {"pitcher": "56719", "batter": "68050", "out": 1},
                },
                {
                    "seqno": 202,
                    "text": "최인호 : 우중간 1루타",
                    "type": 13,
                    "currentGameState": {"pitcher": "56719", "batter": "50707", "out": 1},
                },
                {
                    "seqno": 203,
                    "text": "박정현 : 3루수 앞 땅볼로 출루",
                    "type": 13,
                    "currentGameState": {"pitcher": "56719", "batter": "50709", "out": 3},
                    "currentPlayersInfo": {
                        "away": {
                            "playerType": "pitcher",
                            "currentGamePlayerStats": {
                                "inn": "5.0",
                                "hit": 4,
                                "run": 1,
                                "bb": 1,
                                "kk": 6,
                                "strikeCount": 55,
                                "ballCount": 25,
                            }
                        }
                    }
                }
            ]
        }
    ]

    player_names = {
        "56719": "王彥程",
        "68050": "姜白虎",
        "50707": "崔仁浩",
        "50709": "朴廷鉉",
    }

    # 追蹤投手 56719 (王彥程)
    events = provider._parse_relays(relays, {"56719"}, "20260901HHKT02026", "2026-09-01", player_names)
    
    # 應有 3 個面對打者通知 (PVB) + 1 個局結束投球通知 (IP_END)
    pvb_events = [e for e in events if "面對" in e.title]
    assert len(pvb_events) == 3
    assert pvb_events[0].title == "5局上｜面對 姜白虎"
    assert "揮棒落空三振" in pvb_events[0].body
    assert pvb_events[1].title == "5局上｜面對 崔仁浩"
    assert "右中間方向 一壘安打" in pvb_events[1].body
    assert pvb_events[2].title == "5局上｜面對 朴廷鉉"
    assert "滾地球上壘" in pvb_events[2].body

    ip_events = [e for e in events if "投球結束" in e.title]
    assert len(ip_events) == 1
    assert ip_events[0].title == "5局上投球結束"
    assert "5.0 局" in ip_events[0].body
    assert "6 三振" in ip_events[0].body


def test_kbo_pitcher_exit_complete_and_mid_inning():
    provider = KboProvider(session=None)  # type: ignore

    # 情境 A: 局中被換下（3.1 局），尚未 3 出局時不發送退場通知，等到 3 出局時才發送
    mid_inn_relay_ongoing = [
        {
            "inn": 4,
            "homeOrAway": 1,
            "textOptions": [
                {
                    "seqno": 10,
                    "text": "타자1 : 삼진 아웃",
                    "currentGameState": {"pitcher": "56719", "batter": "101", "out": 1},
                },
                {
                    "seqno": 11,
                    "text": "투수교체",
                    "currentGameState": {"pitcher": "67703", "batter": "102", "out": 1},
                },
                {
                    "seqno": 12,
                    "text": "타자2 : 뜬공 아웃",
                    "currentGameState": {"pitcher": "67703", "batter": "102", "out": 2},
                },
            ],
        }
    ]
    p_box = {
        "56719": {
            "pcode": "56719",
            "inn": "3.1",
            "hit": 6,
            "r": 5,
            "er": 5,
            "bb": 4,
            "kk": 1,
            "bf": 75,
            "hasPlayerEnd": True,
        }
    }
    # 進行中（僅 2 出局）
    events_ongoing = provider._parse_relays(
        mid_inn_relay_ongoing, {"56719"}, "20260903HHKT02026", "2026-09-03", pitcher_box_stats=p_box
    )
    exit_events_ongoing = [e for e in events_ongoing if e.kind == EventKind.PITCHING_EXIT]
    assert len(exit_events_ongoing) == 0, "局中未滿 3 出局不應提早發送退場通知"

    # 該局達到 3 出局結束換局
    mid_inn_relay_done = [
        {
            "inn": 4,
            "homeOrAway": 1,
            "textOptions": mid_inn_relay_ongoing[0]["textOptions"]
            + [
                {
                    "seqno": 13,
                    "text": "타자3 : 땅볼 아웃",
                    "currentGameState": {"pitcher": "67703", "batter": "103", "out": 3},
                }
            ],
        }
    ]
    events_done = provider._parse_relays(
        mid_inn_relay_done, {"56719"}, "20260903HHKT02026", "2026-09-03", pitcher_box_stats=p_box
    )
    exit_events_done = [e for e in events_done if e.kind == EventKind.PITCHING_EXIT]
    assert len(exit_events_done) == 1, "該半局 3 出局後應立即發送退場通知"
    assert exit_events_done[0].title == "投球工作結束（退場）"
    assert "3.1 局" in exit_events_done[0].body
    assert "6 安打" in exit_events_done[0].body
    assert "5 失分（5 責失）" in exit_events_done[0].body
    assert "75 球" in exit_events_done[0].body


def test_kbo_on_deck_event_generation():
    provider = KboProvider(session=None)  # type: ignore

    relays = [
        {
            "inn": 1,
            "homeOrAway": 0,
            "textOptions": [
                {
                    "seqno": 10,
                    "text": "타자1 : 우전 안타",
                    "currentGameState": {"batter": "101", "pitcher": "901", "out": 0},
                },
                {
                    "seqno": 20,
                    "text": "김도영 : 좌월 투런홈런",
                    "currentGameState": {"batter": "52600", "pitcher": "901", "out": 0},
                },
            ],
        }
    ]

    # 當 101 打擊時，次打者為 52600 (김도영)
    events = provider._parse_relays(relays, {"52600"}, "2026091501", "2026-09-15")
    assert len(events) == 2

    on_deck = events[0]
    assert on_deck.kind == EventKind.ON_DECK
    assert on_deck.player_id == "52600"
    assert on_deck.title == "1局上｜即將上場打擊"
    assert "0 出局" in on_deck.body
    assert "下一棒即將輪到打擊" in on_deck.body

    pa = events[1]
    assert pa.kind == EventKind.PLATE_APPEARANCE
    assert pa.player_id == "52600"
    assert "全壘打" in pa.body
    assert on_deck.occurred_at < pa.occurred_at



