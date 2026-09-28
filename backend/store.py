"""
Local SQLite store. Everything the model and the simulators read comes from here,
so the API starts in seconds instead of re-downloading six seasons on every boot.

Filled by `ingest.py`. Default path: <repo>/data/football.db (override with FP_DB).
"""

import os
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.environ.get("FP_DB", DATA_DIR / "football.db"))

# One row per played match. Odds are decimal; NULL when the source doesn't have them
# for that season (Pinnacle starts in 2012/13, closing odds in 2019/20 for most books).
MATCH_COLUMNS = {
    "league": "TEXT NOT NULL",
    "season": "TEXT NOT NULL",        # football-data code: "2425" = 2024/25
    "date": "TEXT NOT NULL",          # ISO yyyy-mm-dd
    "home": "TEXT NOT NULL",          # football-data team names are canonical
    "away": "TEXT NOT NULL",
    "fthg": "INTEGER", "ftag": "INTEGER",
    "hthg": "INTEGER", "htag": "INTEGER",
    "hs": "INTEGER", "as_": "INTEGER", "hst": "INTEGER", "ast": "INTEGER",
    "hc": "INTEGER", "ac": "INTEGER", "hf": "INTEGER", "af": "INTEGER",
    "hy": "INTEGER", "ay": "INTEGER", "hr": "INTEGER", "ar": "INTEGER",
    "xg_home": "REAL", "xg_away": "REAL",
    "xg_source": "TEXT",              # 'understat' | 'football-data' | NULL
    "b365_h": "REAL", "b365_d": "REAL", "b365_a": "REAL",
    "avg_h": "REAL", "avg_d": "REAL", "avg_a": "REAL",
    "pin_h": "REAL", "pin_d": "REAL", "pin_a": "REAL",
    "close_h": "REAL", "close_d": "REAL", "close_a": "REAL",
}

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS matches (
    {", ".join(f"{name} {kind}" for name, kind in MATCH_COLUMNS.items())},
    PRIMARY KEY (league, date, home, away)
);
CREATE INDEX IF NOT EXISTS matches_league_season ON matches (league, season);

CREATE TABLE IF NOT EXISTS team_map (
    league TEXT NOT NULL,
    source TEXT NOT NULL,             -- 'understat'
    source_name TEXT NOT NULL,
    name TEXT NOT NULL,               -- football-data name
    PRIMARY KEY (league, source, source_name)
);

-- Every prediction the model makes before kick-off, so it can be scored later
-- against what actually happened and against the bookmakers.
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    league TEXT NOT NULL,
    date TEXT NOT NULL,
    home TEXT NOT NULL,
    away TEXT NOT NULL,
    p_home REAL NOT NULL, p_draw REAL NOT NULL, p_away REAL NOT NULL,
    lambda_home REAL, lambda_away REAL,
    odds_h REAL, odds_d REAL, odds_a REAL,
    UNIQUE (model_version, league, date, home, away)
);

-- Fixtures not played yet (for the season simulator). Only where a source lists them.
CREATE TABLE IF NOT EXISTS fixtures (
    league TEXT NOT NULL,
    season TEXT NOT NULL,
    date TEXT NOT NULL,
    home TEXT NOT NULL,
    away TEXT NOT NULL,
    PRIMARY KEY (league, season, home, away)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    league TEXT NOT NULL,
    season TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    rows INTEGER NOT NULL,
    PRIMARY KEY (league, season, source)
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def replace_season(conn: sqlite3.Connection, league: str, season: str, df: pd.DataFrame) -> int:
    """Atomically swap all rows of one league-season for `df`."""
    cols = [c for c in MATCH_COLUMNS if c in df.columns]
    rows = df[cols].astype(object).where(df[cols].notna(), None).itertuples(index=False)
    with conn:
        conn.execute("DELETE FROM matches WHERE league = ? AND season = ?", (league, season))
        conn.executemany(
            f"INSERT OR REPLACE INTO matches ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            list(rows),
        )
    return len(df)


def load_matches(
    conn: sqlite3.Connection,
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """Matches as a DataFrame sorted by date, with `date` parsed."""
    query, params = "SELECT * FROM matches WHERE 1=1", []
    if leagues:
        query += f" AND league IN ({', '.join('?' * len(leagues))})"
        params += leagues
    if seasons:
        query += f" AND season IN ({', '.join('?' * len(seasons))})"
        params += seasons
    df = pd.read_sql_query(query + " ORDER BY date, league, home", conn, params=params)
    df["date"] = pd.to_datetime(df["date"])
    return df


def summary(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT league, COUNT(DISTINCT season) AS seasons, MIN(season) AS first,
                  MAX(season) AS last, COUNT(*) AS matches,
                  SUM(xg_home IS NOT NULL) AS with_xg, SUM(pin_h IS NOT NULL) AS with_pinnacle
           FROM matches GROUP BY league ORDER BY league""",
        conn,
    )


def load_fixtures(conn: sqlite3.Connection, league: str, season: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT * FROM fixtures WHERE league = ? AND season = ? ORDER BY date", conn, params=[league, season])
    df["date"] = pd.to_datetime(df["date"])
    return df


def team_map(conn: sqlite3.Connection, league: str, source: str = "understat") -> dict[str, str]:
    rows = conn.execute("SELECT source_name, name FROM team_map WHERE league = ? AND source = ?",
                        (league, source)).fetchall()
    return dict(rows)
