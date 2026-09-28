import pandas as pd
import pytest

from odds_live import _norm, fair_probabilities, find_value, match_events


def test_names_normalise_accents_and_suffixes():
    assert _norm("Málaga CF") == "malaga"
    assert _norm("Atlético Madrid") == "atletico madrid"


def test_events_match_fixtures_by_date_and_both_names():
    fixtures = pd.DataFrame({"date": pd.to_datetime(["2026-10-09", "2026-10-10", "2026-10-10"]),
                             "home": ["Malaga", "Ath Madrid", "Betis"], "away": ["Espanol", "Celta", "Getafe"]})
    events = [
        {"id": "a", "commence_time": "2026-10-09T19:00:00Z", "home_team": "Málaga", "away_team": "Espanyol"},
        {"id": "b", "commence_time": "2026-10-10T16:15:00Z", "home_team": "Atlético Madrid", "away_team": "Celta Vigo"},
        {"id": "c", "commence_time": "2026-10-10T16:15:00Z", "home_team": "Real Betis", "away_team": "Nowhere FC"},
    ]
    m = match_events(events, fixtures, known={"Atlético Madrid": "Ath Madrid"})
    assert m == {"a": ("Malaga", "Espanol"), "b": ("Ath Madrid", "Celta")}   # c: one name only, rejected


def _snap(rows):
    df = pd.DataFrame(rows, columns=["bookmaker", "outcome", "price"])
    return df.assign(event_id="e", league="SP1", kickoff="2099-01-01T00:00:00Z", home="A", away="B",
                     home_src="A", away_src="B", market="h2h", point=0.0, fetched_at="2026-01-01")


def test_fair_probability_prefers_pinnacle_and_removes_margin():
    g = _snap([("pinnacle", "home", 2.0), ("pinnacle", "draw", 3.5), ("pinnacle", "away", 4.0),
               ("betfair_ex_eu", "home", 1.5), ("betfair_ex_eu", "draw", 4.0), ("betfair_ex_eu", "away", 6.0)])
    probs, ref = fair_probabilities(g)
    assert ref == "pinnacle" and sum(probs.values()) == pytest.approx(1)
    assert probs["home"] < 0.5


def test_value_is_a_soft_price_above_the_fair_probability():
    snap = _snap([("pinnacle", "home", 2.0), ("pinnacle", "draw", 3.6), ("pinnacle", "away", 4.2),
                  ("unibet", "home", 2.2), ("unibet", "draw", 3.3), ("unibet", "away", 3.9)])
    picks = find_value(snap, min_ev=0.02)
    assert list(picks["outcome"]) == ["home"] and picks["bookmaker"].iat[0] == "unibet"
    assert picks["ev"].iat[0] == pytest.approx(picks["fair_p"].iat[0] * 2.2 - 1)


def test_power_method_takes_more_margin_from_long_shots():
    import numpy as np
    from odds_live import remove_margin

    prices = np.array([1.5, 4.2, 7.5])
    power = remove_margin(prices)
    proportional = (1 / prices) / (1 / prices).sum()
    assert power.sum() == pytest.approx(1)
    assert power[2] < proportional[2] and power[0] > proportional[0]


def test_a_pick_is_only_scored_against_a_later_snapshot(tmp_path, monkeypatch):
    import store
    import odds_live

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "t.db")
    conn = odds_live.connect()
    rows = lambda at, home_price: [(at, "SP1", "e", "2099-01-01T00:00:00Z", "A", "B", "A", "B", book, "h2h", out, None, price)
                                   for book, out, price in [("pinnacle", "home", 2.0), ("pinnacle", "draw", 3.6),
                                                            ("pinnacle", "away", 4.2), ("unibet", "home", home_price)]]
    conn.executemany(f"INSERT INTO odds_snapshots VALUES ({', '.join('?' * 13)})", rows("2026-01-01T10:00:00", 2.2))
    picks = odds_live.find_value(odds_live.latest(conn), 0.02)
    odds_live.record_picks(conn, picks)
    assert odds_live.score_picks(conn).empty                     # same snapshot: not scored
    conn.executemany(f"INSERT INTO odds_snapshots VALUES ({', '.join('?' * 13)})", rows("2030-01-01T10:00:00", 2.2))
    scored = odds_live.score_picks(conn)
    assert len(scored) == 1
