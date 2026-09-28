"""
Live odds from The Odds API (needs ODDS_API_KEY; free tier = 500 credits a month).

  python odds_live.py snapshot --leagues SP1,E0      # store the current odds (3 credits per league)
  python odds_live.py value --min-ev 0.02            # prices above the sharp fair probability
  python odds_live.py clv                            # how the recorded picks did against the close

Every snapshot is stored, so over time the table holds the whole path of each price from
the first quote to kick-off. The last snapshot before kick-off is the closing line.

**How value is measured.** Pinnacle (or, without it, the Betfair exchange) with its margin
removed is taken as the fair probability, the same reference the professionals use. A price
at another bookmaker is value when fair_p × price − 1 exceeds the threshold. Every value
price is recorded the first time it's seen, and `clv` scores it later against the fair
closing probability: the honest test of whether the edge was real.
"""

import argparse
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

import store

load_dotenv(Path(__file__).with_name(".env"))
API = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
SPORTS = {
    "E0": "soccer_epl", "E1": "soccer_efl_champ", "SP1": "soccer_spain_la_liga",
    "SP2": "soccer_spain_segunda_division", "D1": "soccer_germany_bundesliga",
    "D2": "soccer_germany_bundesliga2", "I1": "soccer_italy_serie_a", "I2": "soccer_italy_serie_b",
    "F1": "soccer_france_ligue_one", "F2": "soccer_france_ligue_two",
    "N1": "soccer_netherlands_eredivisie", "P1": "soccer_portugal_primeira_liga",
}
MARKETS = "h2h,totals,spreads"          # 1 credit each per region
SHARP = ("pinnacle", "betfair_ex_eu")   # reference, in order of preference
RESERVE = 30                            # never spend the last credits of the month

SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshots (
    fetched_at TEXT NOT NULL, league TEXT NOT NULL, event_id TEXT NOT NULL,
    kickoff TEXT NOT NULL, home TEXT, away TEXT, home_src TEXT NOT NULL, away_src TEXT NOT NULL,
    bookmaker TEXT NOT NULL, market TEXT NOT NULL, outcome TEXT NOT NULL,
    point REAL, price REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS odds_event ON odds_snapshots (event_id, market, point);

-- Value prices, recorded the first time they are seen; scored later against the close.
CREATE TABLE IF NOT EXISTS value_picks (
    event_id TEXT NOT NULL, league TEXT NOT NULL, kickoff TEXT NOT NULL,
    home TEXT, away TEXT, market TEXT NOT NULL, outcome TEXT NOT NULL, point REAL,
    bookmaker TEXT NOT NULL, price REAL NOT NULL, fair_p REAL NOT NULL, ev REAL NOT NULL,
    reference TEXT NOT NULL, seen_at TEXT NOT NULL,
    PRIMARY KEY (event_id, market, outcome, point, bookmaker)
);

CREATE TABLE IF NOT EXISTS odds_api_usage (at TEXT NOT NULL, used INTEGER, remaining INTEGER);
"""


def connect() -> sqlite3.Connection:
    conn = store.connect()
    conn.executescript(SCHEMA)
    return conn


# ─── team names ────────────────────────────────────────────────────────────────

def _norm(name: str) -> str:
    """'Málaga CF' -> 'malaga'. Accents, case and club suffixes out."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    for token in (" fc", "fc ", " cf", "cf ", " sc", " ac", "ac ", " afc", "ssc ", "as ", " calcio", "real club "):
        s = s.replace(token, " ")
    return " ".join(s.replace(".", " ").replace("-", " ").split())


def _similar(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def match_events(events: list[dict], fixtures: pd.DataFrame, known: dict[str, str]) -> dict[str, tuple[str, str]]:
    """event id -> (home, away) in football-data spelling.

    Each event is matched to a pending fixture of the same league within ±2 days whose
    two names look most alike; names learned before (`known`) count as exact. A match
    needs both sides reasonably similar, so a wrong pairing can't slip through on one
    good name.
    """
    out = {}
    for e in events:
        day = pd.Timestamp(e["commence_time"][:10])
        near = fixtures[(fixtures["date"] - day).abs() <= pd.Timedelta(days=2)]
        best, score = None, 0.0
        for f in near.itertuples(index=False):
            sh = 1.0 if known.get(e["home_team"]) == f.home else _similar(e["home_team"], f.home)
            sa = 1.0 if known.get(e["away_team"]) == f.away else _similar(e["away_team"], f.away)
            if min(sh, sa) >= 0.5 and sh + sa > score:
                best, score = (f.home, f.away), sh + sa
        if best:
            out[e["id"]] = best
    return out


# ─── snapshots ─────────────────────────────────────────────────────────────────

def snapshot(conn, league: str, key: str | None = None) -> dict:
    key = key or os.environ.get("ODDS_API_KEY", "")
    if not key:
        raise SystemExit("falta ODDS_API_KEY en backend/.env")
    last = conn.execute("SELECT remaining FROM odds_api_usage ORDER BY at DESC LIMIT 1").fetchone()
    if last and last[0] is not None and last[0] < RESERVE:
        raise SystemExit(f"quedan {last[0]} créditos: por debajo de la reserva ({RESERVE}), no gasto")
    resp = requests.get(API.format(sport=SPORTS[league]), timeout=30, params={
        "apiKey": key, "regions": "eu", "markets": MARKETS, "oddsFormat": "decimal"})
    resp.raise_for_status()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        conn.execute("INSERT INTO odds_api_usage VALUES (?, ?, ?)",
                     (now, _int(resp.headers.get("x-requests-used")), _int(resp.headers.get("x-requests-remaining"))))
    events = resp.json()

    fixtures = store.load_fixtures(conn, league)
    known = store.team_map(conn, league, "oddsapi")
    mapping = match_events(events, fixtures, known)
    learned = {}
    rows = []
    for e in events:
        home, away = mapping.get(e["id"], (None, None))
        if home:
            learned[e["home_team"]], learned[e["away_team"]] = home, away
        for b in e.get("bookmakers", []):
            for m in b.get("markets", []):
                for o in m.get("outcomes", []):
                    outcome = ("home" if o["name"] == e["home_team"] else "away" if o["name"] == e["away_team"]
                               else o["name"].lower())
                    point = o.get("point")
                    # Handicaps come per side (home -0.5 / away +0.5): store the home line
                    # for both, so the two sides of one line group together.
                    if m["key"] == "spreads" and outcome == "away" and point is not None:
                        point = -point
                    rows.append((now, league, e["id"], e["commence_time"], home, away, e["home_team"],
                                 e["away_team"], b["key"], m["key"], outcome, point, o["price"]))
    with conn:
        conn.executemany(f"INSERT INTO odds_snapshots VALUES ({', '.join('?' * 13)})", rows)
        conn.executemany("INSERT OR REPLACE INTO team_map VALUES (?, 'oddsapi', ?, ?)",
                         [(league, src, ours) for src, ours in learned.items()])
    return {"league": league, "events": len(events), "matched": len(mapping), "rows": len(rows),
            "remaining": _int(resp.headers.get("x-requests-remaining")),
            "unmatched": [f"{e['home_team']} - {e['away_team']}" for e in events if e["id"] not in mapping]}


def _int(x) -> int | None:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


# ─── value ─────────────────────────────────────────────────────────────────────

def latest(conn, before: str | None = None) -> pd.DataFrame:
    """The most recent snapshot of every event still to be played (or, with `before`,
    the last snapshot taken before that time)."""
    df = pd.read_sql_query("SELECT * FROM odds_snapshots", conn)
    if df.empty:
        return df
    df["point"] = df["point"].fillna(0.0)
    last = df.groupby("event_id")["fetched_at"].transform("max")
    return df[df["fetched_at"] == last]


def remove_margin(prices: np.ndarray) -> np.ndarray:
    """Fair probabilities from decimal odds, power method: p_i = (1/o_i)^k with k such that
    they sum to 1. Bookmakers load more margin on long shots; dividing it proportionally
    over-rates them and invents value where there is none. Measured on Pinnacle closes of
    the big five: outcomes priced under 20 % win 13.05 % of the time; proportional says
    13.74 %, power says 13.46 %."""
    from scipy.optimize import brentq

    inv = 1 / prices
    if inv.sum() <= 1:          # no margin (or an arb): nothing to remove
        return inv / inv.sum()
    k = brentq(lambda k: (inv ** k).sum() - 1, 1.0, 5.0)
    return inv ** k


def fair_probabilities(group: pd.DataFrame) -> tuple[dict[str, float], str] | None:
    """Fair probability of each outcome of one market line, from the sharpest book there."""
    for ref in SHARP:
        g = group[group["bookmaker"] == ref]
        if len(g) >= 2 and (g["price"] > 1).all() and g["outcome"].is_unique:
            return dict(zip(g["outcome"], remove_margin(g["price"].to_numpy(float)))), ref
    return None


def find_value(snap: pd.DataFrame, min_ev: float = 0.02, max_price: float = 10.0) -> pd.DataFrame:
    """Every (event, market line, outcome, bookmaker) whose price beats the fair
    probability by `min_ev`. Long shots above `max_price` are left out: there the fair
    probability itself is least reliable."""
    now = datetime.now(timezone.utc).isoformat()
    snap = snap[snap["kickoff"] > now]
    picks = []
    for (event, market, point), g in snap.groupby(["event_id", "market", "point"]):
        fair = fair_probabilities(g)
        if fair is None:
            continue
        probs, ref = fair
        soft = g[~g["bookmaker"].isin(SHARP) & g["outcome"].isin(probs)]
        for r in soft.itertuples(index=False):
            ev = probs[r.outcome] * r.price - 1
            if ev > min_ev and r.price <= max_price:
                picks.append({"event_id": event, "league": r.league, "kickoff": r.kickoff,
                              "home": r.home or r.home_src, "away": r.away or r.away_src,
                              "market": market, "outcome": r.outcome, "point": point,
                              "bookmaker": r.bookmaker, "price": r.price, "fair_p": probs[r.outcome],
                              "ev": ev, "reference": ref})
    return pd.DataFrame(picks).sort_values("ev", ascending=False) if picks else pd.DataFrame()


def record_picks(conn, picks: pd.DataFrame) -> int:
    if picks.empty:
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cols = ["event_id", "league", "kickoff", "home", "away", "market", "outcome", "point",
            "bookmaker", "price", "fair_p", "ev", "reference"]
    before = conn.total_changes
    with conn:
        conn.executemany(f"INSERT OR IGNORE INTO value_picks VALUES ({', '.join('?' * 14)})",
                         [(*r, now) for r in picks[cols].itertuples(index=False)])
    return conn.total_changes - before


# ─── closing-line value ────────────────────────────────────────────────────────

def score_picks(conn) -> pd.DataFrame:
    """Each recorded pick against the fair probability of the last snapshot taken before
    kick-off (the close we have). EV at close = fair_close × price − 1."""
    picks = pd.read_sql_query("SELECT * FROM value_picks", conn)
    snaps = pd.read_sql_query("SELECT * FROM odds_snapshots", conn)
    if picks.empty or snaps.empty:
        return pd.DataFrame()
    snaps["point"] = snaps["point"].fillna(0.0)
    snaps = snaps[snaps["fetched_at"] < snaps["kickoff"]]
    rows = []
    for p in picks.itertuples(index=False):
        g = snaps[(snaps["event_id"] == p.event_id) & (snaps["market"] == p.market) & (snaps["point"] == (p.point or 0.0))]
        if g.empty:
            continue
        last = g[g["fetched_at"] == g["fetched_at"].max()]
        fair = fair_probabilities(last)
        if fair is None or p.outcome not in fair[0]:
            continue
        rows.append({**p._asdict(), "closed_at": last["fetched_at"].iat[0],
                     "fair_close": fair[0][p.outcome], "ev_close": fair[0][p.outcome] * p.price - 1,
                     "final": last["fetched_at"].iat[0] >= (pd.Timestamp(p.kickoff) - pd.Timedelta(hours=3)).isoformat()})
    return pd.DataFrame(rows)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--leagues", default="E0,SP1,D1,I1,F1")
    v = sub.add_parser("value")
    v.add_argument("--min-ev", type=float, default=0.02)
    sub.add_parser("clv")
    args = parser.parse_args()
    conn = connect()
    pd.set_option("display.width", 200)

    if args.cmd == "snapshot":
        for league in args.leagues.split(","):
            r = snapshot(conn, league)
            print(f"{league:4s} {r['events']:3d} partidos, {r['matched']} cruzados, {r['rows']} cuotas"
                  f"  · quedan {r['remaining']} créditos")
            if r["unmatched"]:
                print("     sin cruzar:", "; ".join(r["unmatched"][:5]))
        picks = find_value(latest(conn))
        print(f"\n{record_picks(conn, picks)} precios con valor nuevos registrados")
    elif args.cmd == "value":
        picks = find_value(latest(conn), args.min_ev)
        if picks.empty:
            print("nada por encima del umbral")
        else:
            cols = ["kickoff", "home", "away", "market", "point", "outcome", "bookmaker", "price", "fair_p", "ev", "reference"]
            print(picks[cols].head(40).round(3).to_string(index=False))
    else:
        scored = score_picks(conn)
        if scored.empty:
            print("todavía no hay picks con cierre")
            return 0
        final = scored[scored["final"]]
        print(f"{len(scored)} picks puntuados ({len(final)} con cierre a menos de 3 h del partido)")
        for name, df in (("todos", scored), ("cierre final", final)):
            if len(df) > 1:
                ev = df["ev_close"]
                print(f"  {name:13s} EV vs cierre {ev.mean():+.2%}  (t={ev.mean() / (ev.std(ddof=1) / np.sqrt(len(ev))):+.1f},"
                      f" n={len(ev)})  baten el cierre {np.mean(ev > 0):.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
