"""API tests on a synthetic league stored in a temporary database."""

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import store
from ingest import season_code
from test_ratings import synthetic_league


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = store.connect(db)
    df, *_ = synthetic_league(n_teams=6, rounds=3)
    season = season_code(date.today())
    # Last round is "not played yet": it becomes the fixture list.
    played, pending = df.iloc[:-15], df.iloc[-15:]
    played = played.assign(league="SP1", season=season, date=played["date"].dt.strftime("%Y-%m-%d"))
    store.replace_season(conn, "SP1", season, played)
    future = pd.Timestamp(date.today()) + pd.Timedelta(days=3)
    conn.executemany("INSERT INTO fixtures VALUES (?,?,?,?,?)",
                     [("SP1", season, future.strftime("%Y-%m-%d"), h, a) for h, a in pending[["home", "away"]].itertuples(index=False)])
    conn.commit()

    import api
    import engine
    monkeypatch.setattr(api, "Engine", lambda: engine.Engine(db))
    with TestClient(api.app) as c:
        yield c


def test_leagues_and_table(client):
    sp1 = next(l for l in client.get("/api/leagues").json() if l["code"] == "SP1")
    assert sp1["has_fixtures"] and sp1["played"] == 75
    table = client.get("/api/leagues/SP1/table").json()
    assert [row["position"] for row in table] == list(range(1, 7))
    assert sum(row["pj"] for row in table) == 150


def test_predict_is_a_distribution(client):
    p = client.post("/api/predict", json={"league": "SP1", "home": "T00", "away": "T01"}).json()
    assert p["p_home"] + p["p_draw"] + p["p_away"] == pytest.approx(1, abs=1e-3)
    assert len(p["score_matrix"]) == 6 and p["ratings"]["home"]["rank"] >= 1


def test_errors_are_404(client):
    assert client.get("/api/leagues/XX/table").status_code == 404
    assert client.post("/api/predict", json={"league": "SP1", "home": "T00", "away": "Nobody"}).status_code == 404


def test_fixtures_are_predicted_and_stored(client):
    fx = client.get("/api/leagues/SP1/fixtures?limit=5").json()
    assert len(fx) == 5
    import api
    stored = api.engine.conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    assert stored == 5
    client.get("/api/leagues/SP1/fixtures?limit=5")          # same predictions: not duplicated
    assert api.engine.conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 5


def test_forecast_and_simulators(client):
    f = client.get("/api/leagues/SP1/forecast?sims=1000").json()
    assert f["remaining"] == 15 and sum(r["p_campeon"] for r in f["table"]) == pytest.approx(1, abs=1e-3)
    inplay = client.post("/api/predict/inplay", json={"league": "SP1", "home": "T00", "away": "T01",
                                                        "score_home": 3, "score_away": 0, "minute": 89}).json()
    assert inplay["p_home"] > 0.95
    t = client.post("/api/simulate/match", json={"league": "SP1", "home": "T00", "away": "T01", "seed": 3}).json()
    assert len(t["goals"]) == sum(t["score"])


def test_track_scores_only_predictions_made_before_the_match(client):
    import api
    conn = api.engine.conn
    first = conn.execute("SELECT date, home, away, fthg, ftag FROM matches ORDER BY date LIMIT 2").fetchall()
    conn.execute("UPDATE matches SET avg_h = 2.0, avg_d = 3.4, avg_a = 4.0")
    rows = []
    for k, (day, h, a, *_ ) in enumerate(first):
        before = (pd.Timestamp(day) - pd.Timedelta(days=2)).isoformat()
        rows.append((before, "v1", "SP1", day, h, a, 0.5, 0.3, 0.2))
        rows.append(((pd.Timestamp(day) - pd.Timedelta(days=1)).isoformat(), "v2", "SP1", day, h, a, 0.6, 0.25, 0.15))
    # Made on the match day itself: might be after kick-off, so it never counts.
    day, h, a, *_ = first[0]
    rows.append((pd.Timestamp(day).isoformat(), "v3", "SP1", day, h, a, 0.99, 0.005, 0.005))
    conn.executemany("INSERT INTO predictions (created_at, model_version, league, date, home, away,"
                     " p_home, p_draw, p_away) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    api.engine.reload()
    t = client.get("/api/track").json()
    assert t["n"] == 2 and [v["version"] for v in t["by_version"]] == ["v2"]   # the latest before the day
    import numpy as np
    expected = np.mean([-np.log([0.6, 0.25, 0.15][0 if g > f else 1 if g == f else 2]) for _, _, _, g, f in first])
    assert t["model"] == pytest.approx(expected, abs=1e-4)
