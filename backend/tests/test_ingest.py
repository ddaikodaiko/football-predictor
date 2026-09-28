"""Offline tests for the data layer: no network, synthetic inputs."""

import json
from datetime import date

import pandas as pd

import ingest
import store


def test_season_code_rolls_over_in_july():
    assert ingest.season_code(date(2024, 8, 15)) == "2425"
    assert ingest.season_code(date(2025, 5, 30)) == "2425"
    assert ingest.season_code(date(2026, 9, 28)) == "2627"
    assert ingest.seasons_from(2024, date(2026, 1, 1)) == ["2425", "2526"]


def test_parse_football_data_handles_old_and_new_column_names():
    old = (
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,AS,BbAvH,BbAvD,BbAvA\n"
        "SP1,28/08/10,Sevilla,Levante,4,1,H,15,8,1.4,4.5,8.0\n"
        "SP1,29/08/10,Malaga,Valencia,,,,,,,,\n"          # not played yet
    ).encode("latin-1")
    df = ingest.parse_football_data(old, "SP1", "1011")
    assert len(df) == 1
    row = df.iloc[0]
    assert (row["date"], row["home"], row["fthg"], row["avg_h"]) == ("2010-08-28", "Sevilla", 4, 1.4)
    assert pd.isna(row["pin_h"]) and row["xg_source"] is None

    new = (
        "﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,HxG,AxG,AvgH,AvgD,AvgA,PSH,PSD,PSA,PSCH,PSCD,PSCA\n"
        "E0,15/08/2026,20:00,Arsenal,Wolves,2,0,1.9,0.4,1.3,5.5,9.0,1.31,5.6,9.4,1.28,5.9,10.0\n"
    ).encode("utf-8")
    row = ingest.parse_football_data(new, "E0", "2627").iloc[0]
    assert (row["xg_home"], row["pin_h"], row["close_h"], row["xg_source"]) == (1.9, 1.31, 1.28, "football-data")


def _fd(rows):
    return pd.DataFrame(rows, columns=["date", "home", "away", "fthg", "ftag"]).assign(
        xg_home=pd.NA, xg_away=pd.NA, xg_source=None)


def test_team_map_is_learned_from_fixtures_and_ignores_coincidences():
    fd = _fd([
        ("2024-08-15", "Ath Bilbao", "Getafe", 1, 1),
        ("2024-08-22", "Getafe", "Ath Bilbao", 0, 2),
        ("2024-08-29", "Ath Bilbao", "Betis", 3, 0),
        ("2024-09-05", "Betis", "Getafe", 1, 1),
        ("2024-09-12", "Getafe", "Betis", 2, 2),
        ("2024-09-19", "Betis", "Ath Bilbao", 0, 1),
        ("2024-09-19", "Sevilla", "Girona", 0, 1),      # same day, same score: a coincidence
    ])
    us = pd.DataFrame([
        ("2024-08-15", "Athletic Club", "Getafe", 1, 1, 0.3, 0.5),
        ("2024-08-22", "Getafe", "Athletic Club", 0, 2, 0.7, 1.8),
        ("2024-08-29", "Athletic Club", "Real Betis", 3, 0, 2.1, 0.2),
        ("2024-09-05", "Real Betis", "Getafe", 1, 1, 1.0, 0.9),
        ("2024-09-12", "Getafe", "Real Betis", 2, 2, 1.4, 1.6),
        ("2024-09-20", "Real Betis", "Athletic Club", 0, 1, 0.8, 1.1),   # one day off (UTC)
    ], columns=["date", "home_us", "away_us", "gh", "ga", "xg_home", "xg_away"])

    mapping = ingest.build_team_map(fd, us, min_votes=3)
    assert mapping == {"Athletic Club": "Ath Bilbao", "Getafe": "Getafe", "Real Betis": "Betis"}

    out, matched = ingest.attach_xg(fd, us, mapping)
    assert matched == 6
    assert out.loc[out["home"] == "Sevilla", "xg_source"].isna().all()
    row = out[(out["home"] == "Betis") & (out["away"] == "Ath Bilbao")].iloc[0]
    assert (row["xg_home"], row["xg_away"], row["xg_source"]) == (0.8, 1.1, "understat")


def test_parse_understat_keeps_only_played_matches():
    body = json.dumps({"dates": [
        {"isResult": True, "h": {"title": "A"}, "a": {"title": "B"}, "goals": {"h": "2", "a": "1"},
         "xG": {"h": "1.5", "a": "0.7"}, "datetime": "2024-08-15 19:00:00"},
        {"isResult": False, "h": {"title": "B"}, "a": {"title": "A"}, "goals": {"h": None, "a": None},
         "xG": {"h": None, "a": None}, "datetime": "2025-01-10 19:00:00"},
    ]}).encode()
    df = ingest.parse_understat(body)
    assert len(df) == 1 and df.iloc[0]["xg_home"] == 1.5


def test_store_replaces_a_season_atomically(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    rows = pd.DataFrame({"league": "SP1", "season": "2425", "date": ["2024-08-15", "2024-08-16"],
                         "home": ["A", "C"], "away": ["B", "D"], "fthg": [1, 0], "ftag": [0, 0]})
    assert store.replace_season(conn, "SP1", "2425", rows) == 2
    assert store.replace_season(conn, "SP1", "2425", rows.iloc[:1]) == 1
    df = store.load_matches(conn, ["SP1"])
    assert len(df) == 1 and df["date"].dtype.kind == "M"
