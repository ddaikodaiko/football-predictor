"""
Do missing players explain the gap between the model and the market?

The market knows who is injured; the model doesn't. This measures whether telling the
model would close part of the gap, before paying for a data plan that has it live.

  1. Missing players per match: API-Football /injuries (free plan: seasons 2022-2024 only,
     one request per league and season, cached in data/raw/api-football/).
  2. How much each one matters: Understat stats of the PREVIOUS season (no peeking at the
     season being predicted): attacking weight = xG + xA, defensive weight = share of
     minutes for defenders and goalkeepers.
  3. The Dixon-Coles expected goals are shifted by what's missing:
        log λ_team += −α · attack_missing(team) + β · defence_missing(opponent)
     α and β are fitted by maximum likelihood on 2022/23-2023/24 and tested on 2024/25,
     then compared with the market with edge.py's information test.

Usage (from backend/):  python injuries.py
"""

import json
import os
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from scipy.optimize import linear_sum_assignment, minimize

import store
from backtest import OUT_DIR, outcome_index, scores
from odds_live import _similar
from ratings import outcome_probs, score_matrix

load_dotenv(Path(__file__).with_name(".env"))
API = "https://v3.football.api-sports.io/injuries"
RAW = store.DATA_DIR / "raw" / "api-football"
LEAGUE_IDS = {"E0": 39, "SP1": 140, "D1": 78, "I1": 135, "F1": 61}
SEASONS = [2022, 2023, 2024]            # all the free plan allows
UNDERSTAT_RAW = store.DATA_DIR / "raw" / "understat"


def fetch(league: str, season: int) -> list[dict]:
    path = RAW / str(season) / f"{league}.json"
    if path.exists():
        return json.loads(path.read_text())
    resp = requests.get(API, headers={"x-apisports-key": os.environ["API_FOOTBALL_KEY"]},
                        params={"league": LEAGUE_IDS[league], "season": season}, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise SystemExit(f"API-Football: {body['errors']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body["response"]))
    time.sleep(7)                        # free plan: 10 requests a minute
    return body["response"]


# ─── player importance from understat ──────────────────────────────────────────

def _plain(name: str) -> str:
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().replace("-", " ")


def understat_players(league: str, year: int) -> pd.DataFrame:
    path = UNDERSTAT_RAW / str(year) / f"{league}.json"
    if not path.exists():
        return pd.DataFrame()
    p = pd.DataFrame(json.loads(path.read_text())["players"])
    for c in ("time", "games", "xG", "xA"):
        p[c] = pd.to_numeric(p[c], errors="coerce").fillna(0)
    p["attack"] = p["xG"] + p["xA"]
    p["defender"] = p["position"].str.contains("D|GK")
    p["plain"] = p["player_name"].map(_plain)
    p["surname"] = p["plain"].str.split().str[-1]
    return p


def match_player(name: str, pool: pd.DataFrame) -> pd.Series | None:
    """'J. Agirrezabala' -> the understat row. Surname must match exactly; the initial
    decides between namesakes; an ambiguous name is dropped rather than guessed."""
    plain = _plain(name).replace(".", " ").split()
    if not plain:
        return None
    cand = pool[pool["surname"] == plain[-1]]
    if len(plain) > 1 and len(cand) > 1:
        cand = cand[cand["plain"].str[0] == plain[0][0]]
    return cand.iloc[0] if len(cand) == 1 else None


# ─── features per match ────────────────────────────────────────────────────────

def missing_features(league: str, season: int, matches: pd.DataFrame, conn) -> pd.DataFrame:
    """One row per (date, team, fd name): attacking and defensive weight missing."""
    rows = fetch(league, season)
    inj = pd.DataFrame([{"date": r["fixture"]["date"][:10], "team": r["team"]["name"],
                         "player": r["player"]["name"], "type": r["player"]["type"]} for r in rows])
    inj = inj[inj["type"] == "Missing Fixture"]
    prev = understat_players(league, season - 1)
    cur = understat_players(league, season)
    if inj.empty or prev.empty or cur.empty:
        return pd.DataFrame()

    # API-Football team -> understat title (Hungarian assignment on name similarity),
    # then understat -> football-data with the mapping ingest.py learned.
    af_teams, us_teams = sorted(inj["team"].unique()), sorted(cur["team_title"].unique())
    sim = np.array([[_similar(a, u) for u in us_teams] for a in af_teams])
    r, c = linear_sum_assignment(-sim)
    us_of = {af_teams[i]: us_teams[j] for i, j in zip(r, c) if sim[i, j] >= 0.5}
    fd_of = store.team_map(conn, league, "understat")
    inj["fd"] = inj["team"].map(us_of).map(fd_of)

    # Scale: a typical team's attacking total and a full defensive line of minutes.
    team_attack = prev.groupby("team_title")["attack"].sum().mean()
    season_minutes = prev["games"].max() * 90
    out = []
    for (date, fd), g in inj.dropna(subset=["fd"]).groupby(["date", "fd"]):
        att = dfn = 0.0
        for name in g["player"].unique():
            p = match_player(name, prev)
            if p is None:
                continue
            att += p["attack"] / team_attack
            if p["defender"]:
                dfn += (p["time"] / season_minutes) / 5          # ~5 defenders + keeper play
        out.append({"date": date, "team": fd, "att_missing": att, "def_missing": dfn,
                    "players": len(g["player"].unique())})
    return pd.DataFrame(out)


def adjusted_probs(pred: pd.DataFrame, alpha: float, beta: float) -> np.ndarray:
    lh = pred["lambda_home"] * np.exp(-alpha * pred["att_h"] + beta * pred["def_a"])
    la = pred["lambda_away"] * np.exp(-alpha * pred["att_a"] + beta * pred["def_h"])
    rho = pred["rho"].fillna(-0.05) if "rho" in pred else pd.Series(-0.05, index=pred.index)
    return np.array([outcome_probs(score_matrix(h, a, r)) for h, a, r in zip(lh, la, rho)])


def main() -> int:
    conn = store.connect()
    matches = store.load_matches(conn, list(LEAGUE_IDS))
    feats = []
    for league in LEAGUE_IDS:
        for season in SEASONS:
            f = missing_features(league, season, matches, conn)
            print(f"{league:4s} {season}: {len(f)} (partido, equipo) con bajas", flush=True)
            feats.append(f.assign(league=league))
    feats = pd.concat(feats, ignore_index=True)

    pred = pd.read_csv(OUT_DIR / "dc_xg0.5_xi0.003_joint.csv.gz", dtype={"season": str})
    pred = pred[pred["season"].isin(["2223", "2324", "2425"])].copy()
    pred["date"] = pred["date"].str[:10]
    key = feats.set_index(["league", "date", "team"])
    for side, col in (("h", "home"), ("a", "away")):
        j = pred.join(key, on=["league", "date", col])
        pred[f"att_{side}"] = j["att_missing"].fillna(0).to_numpy()
        pred[f"def_{side}"] = j["def_missing"].fillna(0).to_numpy()
    covered = ((pred[["att_h", "att_a", "def_h", "def_a"]] > 0).any(axis=1)).mean()
    print(f"\n{len(pred)} partidos, {covered:.0%} con alguna baja conocida")

    y = outcome_index(pred)
    train = pred["season"].isin(["2223", "2324"]).to_numpy()
    test = ~train

    def nll(params):
        p = adjusted_probs(pred[train], *params)
        return -np.log(np.clip(p[np.arange(train.sum()), y[train]], 1e-12, 1)).mean()

    fit = minimize(nll, x0=[0.3, 0.3], method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-6})
    alpha, beta = fit.x
    print(f"α (ataque que falta) = {alpha:.3f}   β (defensa que falta) = {beta:.3f}")

    base = pred[["p_home", "p_draw", "p_away"]].to_numpy()[test]
    adj = adjusted_probs(pred[test], alpha, beta)
    print(f"2024/25 log loss: modelo {scores(base, y[test])['log_loss']:.4f} -> con bajas {scores(adj, y[test])['log_loss']:.4f}")

    # Against the market: does the injury-aware model add information the price lacks?
    from edge import information_gain
    test_df = pred[test].copy()
    for label, probs in (("sin bajas", base), ("con bajas", adj)):
        test_df[["p_home", "p_draw", "p_away"]] = probs
        both = test_df.dropna(subset=["avg_h", "avg_d", "avg_a"])
        both = both.assign(season=np.where(both["date"] < "2025-01-01", "a", "b"))   # two halves: fit on the first
        mkt, combined, n = information_gain(both.reset_index(drop=True), "1x2")
        print(f"  {label}: mercado {mkt:.4f} vs mercado+modelo {combined:.4f}  (ganancia {mkt - combined:+.4f}, n={n})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
