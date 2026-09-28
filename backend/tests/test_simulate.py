import numpy as np
import pandas as pd
import pytest

from ratings import DixonColes
from simulate import betting_backtest, simulate_season, simulate_timeline, standings
from test_ratings import synthetic_league


def _played(rows):
    return pd.DataFrame(rows, columns=["home", "away", "fthg", "ftag"])


def test_standings_points_and_order():
    t = standings(_played([("A", "B", 2, 0), ("B", "C", 1, 1), ("C", "A", 0, 3)]))
    assert list(t["team"]) == ["A", "B", "C"]      # B y C a 1 punto: B tiene mejor gd
    assert t.set_index("team").loc["A", ["pts", "gd", "pj"]].tolist() == [6, 5, 2]


def test_nothing_left_to_play_means_the_table_is_final():
    df, *_ = synthetic_league(rounds=1)
    dc = DixonColes(max_days=10_000).fit(df)
    f = simulate_season(dc, df, df.iloc[0:0], n_sims=200, seed=0)
    leader = standings(df)["team"].iloc[0]
    assert f.table.set_index("team").loc[leader, "p_campeon"] == 1.0


def test_season_probabilities_are_consistent():
    df, attack, defense, _ = synthetic_league(rounds=2, seed=3)
    dc = DixonColes(max_days=10_000).fit(df)
    played, remaining = df.iloc[:100], df.iloc[100:][["date", "home", "away"]]
    f = simulate_season(dc, played, remaining, n_sims=2000, seed=1, zones=(1, 4, 3))
    np.testing.assert_allclose(f.positions.sum(axis=0), 1.0)      # every place is taken
    np.testing.assert_allclose(f.positions.sum(axis=1), 1.0)      # every team finishes somewhere
    assert f.table["p_campeon"].sum() == pytest.approx(1.0)
    assert f.table["p_descenso"].sum() == pytest.approx(3.0)
    # The strongest generated team should be among the favourites.
    best = max(attack, key=lambda t: attack[t] - defense[t])
    assert f.table.set_index("team").loc[best, "p_campeon"] >= f.table["p_campeon"].median()


def test_timeline_matches_its_score():
    for seed in range(20):
        t = simulate_timeline(1.6, 1.1, -0.05, seed=seed)
        assert sum(g["side"] == "home" for g in t["goals"]) == t["score"][0]
        assert sum(g["side"] == "away" for g in t["goals"]) == t["score"][1]
        minutes = [g["minute"] for g in t["goals"]]
        assert minutes == sorted(minutes) and all(1 <= m <= 90 for m in minutes)
    assert simulate_timeline(1.6, 1.1, seed=7) == simulate_timeline(1.6, 1.1, seed=7)


def test_betting_only_takes_value_and_accounts_correctly():
    pred = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-08"]), "home": ["A", "C"], "away": ["B", "D"],
        "fthg": [1, 0], "ftag": [0, 2],
        "p_home": [0.60, 0.30], "p_draw": [0.25, 0.30], "p_away": [0.15, 0.40],
        "avg_h": [2.0, 3.0], "avg_d": [3.5, 3.2], "avg_a": [6.0, 2.4],   # value: A home (1.2), none in 2nd
        "close_h": [1.8, 3.0], "close_d": [3.6, 3.2], "close_a": [6.5, 2.4],
    })
    r = betting_backtest(pred, edge=0.05)
    assert r["bets"] == 1 and r["log"].iloc[0]["pick"] == "H"
    assert r["profit"] == pytest.approx(1.0) and r["roi"] == pytest.approx(1.0)
    assert r["clv_mean"] == pytest.approx(2.0 / 1.8 - 1)
