from tracker.models import EventKind
from tracker.providers.mlb import MlbProvider


def test_formatters_cover_requested_game_fields():
    from tracker.providers.mlb import _format_batting, _format_pitching

    batting = _format_batting(
        {
            "atBats": 4,
            "plateAppearances": 5,
            "hits": 2,
            "strikeOuts": 1,
            "baseOnBalls": 1,
            "doubles": 1,
            "triples": 0,
            "homeRuns": 1,
            "runs": 2,
            "rbi": 3,
            "stolenBases": 1,
        }
    )
    assert "4 打數" in batting
    assert "5 打席" in batting
    assert "3 打點" in batting
    assert "1 盜壘" in batting

    pitching = _format_pitching(
        {
            "inningsPitched": "6.0",
            "hits": 4,
            "runs": 2,
            "earnedRuns": 1,
            "baseOnBalls": 2,
            "strikeOuts": 8,
            "numberOfPitches": 91,
        }
    )
    assert "6.0 局" in pitching
    assert "1 自責分" in pitching
    assert "91 球" in pitching


def test_player_mapping():
    player = MlbProvider._player(
        {
            "id": 999,
            "fullName": "Example Player",
            "currentTeam": {"name": "Example Club"},
            "primaryPosition": {"abbreviation": "P"},
        }
    )
    assert player.external_id == "999"
    assert player.team == "Example Club"


def test_mlb_parse_game_batter_pa_with_pitcher():
    from unittest.mock import MagicMock
    provider = MlbProvider(MagicMock())
    feed = {
        "gameData": {
            "status": {"abstractGameState": "Live"},
            "datetime": {"officialDate": "2026-08-26", "dateTime": "2026-08-26T12:00:00Z"},
        },
        "liveData": {
            "plays": {
                "allPlays": [
                    {
                        "about": {"atBatIndex": 1, "inning": 1, "halfInning": "top", "isComplete": True},
                        "matchup": {
                            "batter": {"id": 660271, "fullName": "Shohei Ohtani"},
                            "pitcher": {"id": 543037, "fullName": "Gerrit Cole"},
                        },
                        "result": {"event": "Home Run", "description": "Shohei Ohtani homers to center."},
                        "playEvents": [
                            {
                                "hitData": {
                                    "launchSpeed": 108.5,
                                    "launchAngle": 28,
                                    "totalDistance": 420,
                                }
                            }
                        ],
                    }
                ]
            }
        },
    }
    events = provider._parse_game(feed, {"660271"}, "123456")
    assert len(events) == 1
    assert events[0].title == "第 1 局上｜面對 Gerrit Cole｜Home Run"
    assert "Shohei Ohtani homers to center." in events[0].body
    assert "初速: 108.5 mph" in events[0].body


def test_mlb_pitcher_exit_on_half_inning_complete():
    from unittest.mock import MagicMock
    from tracker.models import EventKind
    provider = MlbProvider(MagicMock())

    feed_ongoing = {
        "gameData": {
            "status": {"abstractGameState": "Live"},
            "datetime": {"officialDate": "2026-08-26", "dateTime": "2026-08-26T12:00:00Z"},
        },
        "liveData": {
            "plays": {
                "allPlays": [
                    {
                        "about": {"atBatIndex": 1, "inning": 3, "halfInning": "top", "isComplete": True, "startOuts": 0},
                        "matchup": {"pitcher": {"id": 543037, "fullName": "Gerrit Cole"}},
                        "result": {"eventType": "strikeout"},
                        "count": {"outs": 1},
                    },
                    {
                        "about": {"atBatIndex": 2, "inning": 3, "halfInning": "top", "isComplete": True, "startOuts": 1},
                        "matchup": {"pitcher": {"id": 999999, "fullName": "Reliever"}},
                        "result": {"eventType": "strikeout"},
                        "count": {"outs": 2},
                    },
                ]
            },
            "linescore": {
                "currentInning": 3,
                "inningHalf": "top",
                "defense": {"pitcher": {"id": 999999}},
            },
            "boxscore": {
                "teams": {
                    "home": {
                        "pitchers": [543037, 999999],
                        "players": {
                            "ID543037": {
                                "stats": {
                                    "pitching": {
                                        "inningsPitched": "2.1",
                                        "hits": 3,
                                        "runs": 1,
                                        "earnedRuns": 1,
                                        "baseOnBalls": 1,
                                        "strikeOuts": 4,
                                        "numberOfPitches": 52,
                                    }
                                }
                            }
                        },
                    },
                    "away": {"pitchers": []},
                }
            },
        },
    }

    # 1. 局中換投，但該半局尚未結束（仍為 3 局上）：不應提前發出退場通知
    events_ongoing = provider._parse_game(feed_ongoing, {"543037"}, "123456")
    exits_ongoing = [e for e in events_ongoing if e.kind == EventKind.PITCHING_EXIT]
    assert len(exits_ongoing) == 0, "局中尚未結束時不應提早發送退場通知"

    # 2. 該半局正式結束（換到 3 局下）：應發送退場通知
    feed_complete = {
        **feed_ongoing,
        "liveData": {
            **feed_ongoing["liveData"],
            "linescore": {
                "currentInning": 3,
                "inningHalf": "bottom",
                "defense": {"pitcher": {"id": 888888}},
            },
        },
    }
    events_complete = provider._parse_game(feed_complete, {"543037"}, "123456")
    exits_complete = [e for e in events_complete if e.kind == EventKind.PITCHING_EXIT]
    assert len(exits_complete) == 1, "半局結束後應發送退場通知"
    assert exits_complete[0].title == "投球工作結束（退場）"
    assert "2.1 局" in exits_complete[0].body
    assert "4 三振" in exits_complete[0].body
    assert "52 球" in exits_complete[0].body


def test_mlb_on_deck_event_generation():
    provider = MlbProvider(session=None)  # type: ignore

    feed = {
        "gameData": {
            "datetime": {"officialDate": "2026-09-15", "dateTime": "2026-09-15T19:00:00Z"},
            "status": {"abstractGameState": "Live"},
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {
                        "players": {
                            "ID101": {"person": {"id": 101, "fullName": "打者一"}, "battingOrder": "100"},
                            "ID102": {"person": {"id": 102, "fullName": "張育成"}, "battingOrder": "200"},
                            "ID103": {"person": {"id": 103, "fullName": "打者三"}, "battingOrder": "300"},
                        }
                    },
                    "home": {"players": {}},
                }
            },
            "plays": {
                "allPlays": [
                    {
                        "about": {"atBatIndex": 0, "inning": 1, "halfInning": "top", "startOuts": 0, "isComplete": True},
                        "matchup": {"batter": {"id": 101, "fullName": "打者一"}, "pitcher": {"id": 901, "fullName": "對方投手"}},
                        "result": {"event": "Single", "description": "打者一 hits a single."},
                    },
                    {
                        "about": {"atBatIndex": 1, "inning": 1, "halfInning": "top", "startOuts": 0, "isComplete": True},
                        "matchup": {"batter": {"id": 102, "fullName": "張育成"}, "pitcher": {"id": 901, "fullName": "對方投手"}},
                        "result": {"event": "Home Run", "description": "張育成 hits a 2-run home run!"},
                    },
                ]
            },
            "linescore": {"defense": {"pitcher": {"id": 901}}},
        },
    }

    # 追蹤 張育成 (102)
    events = provider._parse_game(feed, {"102"}, "game_test")
    assert len(events) == 2

    # 1. 提前預告事件
    on_deck = events[0]
    assert on_deck.kind == EventKind.ON_DECK
    assert on_deck.player_id == "102"
    assert on_deck.title == "第 1 局上｜即將上場打擊"
    assert "0 出局" in on_deck.body
    assert "下一棒即將輪到打擊" in on_deck.body

    # 2. 打席結束事件
    pa = events[1]
    assert pa.kind == EventKind.PLATE_APPEARANCE
    assert pa.player_id == "102"
    assert "Home Run" in pa.title
    assert "2-run home run" in pa.body
    assert on_deck.occurred_at < pa.occurred_at



