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

