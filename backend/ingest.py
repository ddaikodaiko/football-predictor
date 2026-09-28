"""
Fill the local store (store.py) from two free sources:

  football-data.co.uk  results, shots, cards, corners and odds (B365, market average,
                       Pinnacle, closing) for 12 leagues since 2005/06. xG only from 2026/27.
  understat.com        per-match xG for the big five leagues since 2014/15.

Usage (from backend/):
    python ingest.py                         # everything, cached
    python ingest.py --leagues SP1,E0 --from 2015
    python ingest.py --refresh               # re-download the current season

Raw downloads are cached in data/raw/. Past seasons never change, so they are fetched
once; the current season is re-fetched when its cache is older than 12 hours.
"""

import argparse
import json
import time
from collections import Counter
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

import store

FD_URL = "https://football-data.co.uk/mmz4281/{season}/{league}.csv"
UNDERSTAT_URL = "https://understat.com/getLeagueData/{league}/{year}"
RAW_DIR = store.DATA_DIR / "raw"
CURRENT_MAX_AGE_S = 12 * 3600
HEADERS = {"User-Agent": "football-predictor (personal research project)"}

LEAGUES = {
    "E0": "Premier League", "E1": "Championship",
    "SP1": "LaLiga", "SP2": "LaLiga Hypermotion",
    "D1": "Bundesliga", "D2": "2. Bundesliga",
    "I1": "Serie A", "I2": "Serie B",
    "F1": "Ligue 1", "F2": "Ligue 2",
    "N1": "Eredivisie", "P1": "Primeira Liga",
}
UNDERSTAT_LEAGUES = {"E0": "EPL", "SP1": "La_liga", "D1": "Bundesliga", "I1": "Serie_A", "F1": "Ligue_1"}
FIRST_UNDERSTAT_YEAR = 2014

# football-data column -> store column. Lists are tried in order: names changed over the years.
FD_COLUMNS = {
    "fthg": ["FTHG", "HG"], "ftag": ["FTAG", "AG"],
    "hthg": ["HTHG"], "htag": ["HTAG"],
    "hs": ["HS"], "as_": ["AS"], "hst": ["HST"], "ast": ["AST"],
    "hc": ["HC"], "ac": ["AC"], "hf": ["HF"], "af": ["AF"],
    "hy": ["HY"], "ay": ["AY"], "hr": ["HR"], "ar": ["AR"],
    "xg_home": ["HxG"], "xg_away": ["AxG"],
    "b365_h": ["B365H"], "b365_d": ["B365D"], "b365_a": ["B365A"],
    "avg_h": ["AvgH", "BbAvH"], "avg_d": ["AvgD", "BbAvD"], "avg_a": ["AvgA", "BbAvA"],
    "pin_h": ["PSH"], "pin_d": ["PSD"], "pin_a": ["PSA"],
    "close_h": ["PSCH", "B365CH", "AvgCH"], "close_d": ["PSCD", "B365CD", "AvgCD"],
    "close_a": ["PSCA", "B365CA", "AvgCA"],
}


# ─── seasons ───────────────────────────────────────────────────────────────────

def season_code(day: date) -> str:
    """2024-08-15 -> '2425'. Seasons roll over in July."""
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def seasons_from(first_year: int, today: date | None = None) -> list[str]:
    last = int(season_code(today or date.today())[:2]) + 2000
    return [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(first_year, last + 1)]


def season_start_year(season: str) -> int:
    return 2000 + int(season[:2])


# ─── download with cache ───────────────────────────────────────────────────────

def fetch_cached(url: str, path: Path, current: bool, refresh: bool = False,
                 headers: dict | None = None) -> bytes | None:
    """Return the body of `url`, from `path` if cached. None on 404 (league-season not published)."""
    fresh = path.exists() and (
        not current or time.time() - path.stat().st_mtime < CURRENT_MAX_AGE_S
    )
    if fresh and not refresh:
        return path.read_bytes()
    resp = requests.get(url, headers={**HEADERS, **(headers or {})}, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    time.sleep(0.5)  # be polite with free sources
    return resp.content


# ─── football-data.co.uk ───────────────────────────────────────────────────────

def parse_football_data(body: bytes, league: str, season: str) -> pd.DataFrame:
    """One football-data CSV -> store rows (played matches only)."""
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = body.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    raw = pd.read_csv(StringIO(text), on_bad_lines="skip")
    raw = raw.dropna(how="all")
    if raw.empty or "HomeTeam" not in raw.columns:
        return pd.DataFrame(columns=list(store.MATCH_COLUMNS))

    out = pd.DataFrame({
        "league": league,
        "season": season,
        "date": pd.to_datetime(raw["Date"], dayfirst=True, format="mixed", errors="coerce"),
        "home": raw["HomeTeam"].astype(str).str.strip(),
        "away": raw["AwayTeam"].astype(str).str.strip(),
    })
    for column, candidates in FD_COLUMNS.items():
        source = next((c for c in candidates if c in raw.columns), None)
        out[column] = pd.to_numeric(raw[source], errors="coerce") if source else pd.NA
    out = out.dropna(subset=["date", "fthg", "ftag"])
    out = out[(out["home"] != "nan") & (out["away"] != "nan")]
    out["xg_source"] = pd.Series(
        ["football-data" if pd.notna(x) else None for x in out["xg_home"]], index=out.index, dtype=object)
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.drop_duplicates(subset=["date", "home", "away"]).reset_index(drop=True)


# ─── understat ─────────────────────────────────────────────────────────────────

def parse_understat_fixtures(body: bytes) -> pd.DataFrame:
    """understat getLeagueData JSON -> matches NOT played yet, understat team names."""
    rows = [{"date": m["datetime"][:10], "home_us": m["h"]["title"], "away_us": m["a"]["title"]}
            for m in json.loads(body)["dates"] if not m.get("isResult")]
    return pd.DataFrame(rows, columns=["date", "home_us", "away_us"])


def parse_understat(body: bytes) -> pd.DataFrame:
    """understat getLeagueData JSON -> played matches with xG, understat team names."""
    data = json.loads(body)
    rows = [
        {
            "date": m["datetime"][:10],
            "home_us": m["h"]["title"], "away_us": m["a"]["title"],
            "gh": int(m["goals"]["h"]), "ga": int(m["goals"]["a"]),
            "xg_home": float(m["xG"]["h"]), "xg_away": float(m["xG"]["a"]),
        }
        for m in data["dates"] if m.get("isResult")
    ]
    return pd.DataFrame(rows, columns=["date", "home_us", "away_us", "gh", "ga", "xg_home", "xg_away"])


def _candidates(fd: pd.DataFrame, us: pd.DataFrame, max_days: int = 1) -> pd.DataFrame:
    """Pairs (understat match, football-data match) with the same score within ±max_days."""
    a = us.assign(_d=pd.to_datetime(us["date"]))
    b = fd[["date", "home", "away", "fthg", "ftag"]].assign(_d=pd.to_datetime(fd["date"]))
    pairs = a.merge(b, left_on=["gh", "ga"], right_on=["fthg", "ftag"], suffixes=("_us", "_fd"))
    return pairs[(pairs["_d_us"] - pairs["_d_fd"]).abs() <= pd.Timedelta(days=max_days)]


def build_team_map(fd: pd.DataFrame, us: pd.DataFrame, min_votes: int = 3) -> dict[str, str]:
    """understat name -> football-data name, learned from the fixtures themselves.

    Two sources spell teams differently ("Athletic Club" / "Ath Bilbao"). Every pair of
    matches with the same score on the same day votes for (home_us -> home_fd) and
    (away_us -> away_fd); the true pairing wins by a landslide because a team plays ~38
    times a season, while coincidences are scattered. Ties or weak winners are dropped.
    """
    pairs = _candidates(fd, us)
    votes: dict[str, Counter] = {}
    for _, p in pairs.iterrows():
        votes.setdefault(p["home_us"], Counter())[p["home"]] += 1
        votes.setdefault(p["away_us"], Counter())[p["away"]] += 1
    mapping: dict[str, str] = {}
    for us_name, counter in votes.items():
        (best, n), *rest = counter.most_common(2) + [(None, 0)]
        runner_up = rest[0][1] if rest else 0
        if n >= min_votes and n >= 2 * runner_up:
            mapping[us_name] = best
    # One-to-one: if two understat names claim the same football-data team, drop both.
    claimed = Counter(mapping.values())
    return {k: v for k, v in mapping.items() if claimed[v] == 1}


def attach_xg(fd: pd.DataFrame, us: pd.DataFrame, mapping: dict[str, str]) -> tuple[pd.DataFrame, int]:
    """Fill xg_home/xg_away from understat where the match is found. Returns (df, n_matched)."""
    us = us.assign(home=us["home_us"].map(mapping), away=us["away_us"].map(mapping)).dropna(subset=["home", "away"])
    fd = fd.copy()
    key = fd.set_index(["home", "away"]).index
    by_teams = {(h, a): (d, xh, xa) for d, h, a, xh, xa in
                us[["date", "home", "away", "xg_home", "xg_away"]].itertuples(index=False)}
    matched = 0
    for i, (h, a) in enumerate(key):
        hit = by_teams.get((h, a))
        # Same pairing appears once per season at a given venue; the date check guards
        # against a season file that mixes in a replayed or rescheduled fixture.
        if hit and abs((pd.Timestamp(hit[0]) - pd.Timestamp(fd.iat[i, fd.columns.get_loc("date")])).days) <= 3:
            fd.iat[i, fd.columns.get_loc("xg_home")] = hit[1]
            fd.iat[i, fd.columns.get_loc("xg_away")] = hit[2]
            fd.iat[i, fd.columns.get_loc("xg_source")] = "understat"
            matched += 1
    return fd, matched


# ─── orchestration ─────────────────────────────────────────────────────────────

def ingest_season(conn, league: str, season: str, current: bool, refresh: bool,
                  use_understat: bool = True) -> dict:
    body = fetch_cached(FD_URL.format(season=season, league=league),
                        RAW_DIR / "football-data" / season / f"{league}.csv", current, refresh)
    if body is None:
        return {"league": league, "season": season, "matches": 0, "xg": 0, "note": "no publicado"}
    fd = parse_football_data(body, league, season)
    note = ""
    year = season_start_year(season)
    if use_understat and league in UNDERSTAT_LEAGUES and year >= FIRST_UNDERSTAT_YEAR and not fd.empty:
        us_body = fetch_cached(
            UNDERSTAT_URL.format(league=UNDERSTAT_LEAGUES[league], year=year),
            RAW_DIR / "understat" / str(year) / f"{league}.json", current, refresh,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        if us_body:
            us = parse_understat(us_body)
            # Early in a season a team may have too few matches to vote; names learned in
            # earlier seasons fill the gap (the fresh vote wins where both exist).
            mapping = {**store.team_map(conn, league), **build_team_map(fd, us)}
            fd, matched = attach_xg(fd, us, mapping)
            unmapped = sorted(set(us["home_us"]) - set(mapping))
            if unmapped:
                note = f"sin mapear: {', '.join(unmapped)}"
            pending = parse_understat_fixtures(us_body)
            pending = pending.assign(home=pending["home_us"].map(mapping),
                                     away=pending["away_us"].map(mapping)).dropna(subset=["home", "away"])
            with conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO team_map VALUES (?, 'understat', ?, ?)",
                    [(league, k, v) for k, v in mapping.items()],
                )
                conn.execute("DELETE FROM fixtures WHERE league = ? AND season = ?", (league, season))
                conn.executemany(
                    "INSERT OR REPLACE INTO fixtures VALUES (?, ?, ?, ?, ?)",
                    [(league, season, d, h, a) for d, h, a in pending[["date", "home", "away"]].itertuples(index=False)],
                )
    n = store.replace_season(conn, league, season, fd)
    with conn:
        conn.execute("INSERT OR REPLACE INTO ingest_log VALUES (?, ?, 'football-data', ?, ?)",
                     (league, season, datetime.now(timezone.utc).isoformat(timespec="seconds"), n))
    return {"league": league, "season": season, "matches": n,
            "xg": int(fd["xg_home"].notna().sum()) if n else 0, "note": note}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--leagues", default=",".join(LEAGUES))
    parser.add_argument("--from", dest="first", type=int, default=2005, help="first season start year")
    parser.add_argument("--refresh", action="store_true", help="re-download the current season")
    parser.add_argument("--no-understat", action="store_true")
    args = parser.parse_args()

    conn = store.connect()
    current = season_code(date.today())
    for league in args.leagues.split(","):
        for season in seasons_from(args.first):
            r = ingest_season(conn, league, season, season == current, args.refresh, not args.no_understat)
            if r["matches"]:
                xg = f"  xG {r['xg']}/{r['matches']}" if r["xg"] else ""
                print(f"{league:4s} {season}  {r['matches']:4d} partidos{xg}  {r['note']}", flush=True)
    print()
    print(store.summary(conn).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
