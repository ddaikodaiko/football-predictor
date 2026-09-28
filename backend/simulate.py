"""
Simulators built on the Dixon-Coles ratings.

  simulate_season   the rest of a league season, thousands of times: final table,
                    title / Champions / relegation odds.
  simulate_timeline one match minute by minute (goal times), for the live view.
  betting_backtest  replay past seasons betting on the model's edges (data from backtest.py).

Usage (from backend/):
    python simulate.py season SP1
    python simulate.py betting data/backtest/dc_xg0.5_xi0.0019.csv.gz --edge 0.05
"""

import argparse
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

import store
from ingest import season_code
from ratings import DixonColes, score_matrix

# Places that matter per league: (title, champions league, relegation from the bottom).
ZONES = {"E0": (1, 4, 3), "SP1": (1, 4, 3), "D1": (1, 4, 2), "I1": (1, 4, 3), "F1": (1, 3, 2),
         "N1": (1, 2, 2), "P1": (1, 2, 2)}
DEFAULT_ZONES = (1, 4, 3)


# ─── standings ─────────────────────────────────────────────────────────────────

def standings(played: pd.DataFrame) -> pd.DataFrame:
    """League table from played matches: pts, gd, gf, played. Sorted like a real table."""
    home = pd.DataFrame({"team": played["home"], "gf": played["fthg"], "ga": played["ftag"]})
    away = pd.DataFrame({"team": played["away"], "gf": played["ftag"], "ga": played["fthg"]})
    rows = pd.concat([home, away], ignore_index=True)
    rows["pts"] = np.select([rows["gf"] > rows["ga"], rows["gf"] == rows["ga"]], [3, 1], 0)
    table = rows.groupby("team").agg(pj=("pts", "size"), pts=("pts", "sum"), gf=("gf", "sum"), ga=("ga", "sum"))
    table["gd"] = table["gf"] - table["ga"]
    return table.sort_values(["pts", "gd", "gf"], ascending=False).reset_index()


# ─── season ────────────────────────────────────────────────────────────────────

@dataclass
class SeasonForecast:
    table: pd.DataFrame          # one row per team, expected values and zone odds
    positions: pd.DataFrame      # P(team finishes in position k), teams x positions
    n_sims: int
    remaining: int


def _sample_scores(m: np.ndarray, n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    k = np.searchsorted(np.cumsum(m.ravel()), rng.random(n), side="right")
    k = np.minimum(k, m.size - 1)
    return np.divmod(k, m.shape[1])


def simulate_season(dc: DixonColes, played: pd.DataFrame, remaining: pd.DataFrame,
                    n_sims: int = 10_000, seed: int | None = None,
                    zones: tuple[int, int, int] = DEFAULT_ZONES) -> SeasonForecast:
    """Play every remaining fixture `n_sims` times from the current table.

    Ties on points break by goal difference, then goals for, then at random (real
    tie-breakers like head-to-head vary by league and change little in practice).
    """
    rng = np.random.default_rng(seed)
    base = standings(played).set_index("team")
    teams = sorted(set(base.index) | set(remaining["home"]) | set(remaining["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    pts = np.tile(base.reindex(teams)["pts"].fillna(0).to_numpy(float), (n_sims, 1))
    gd = np.tile(base.reindex(teams)["gd"].fillna(0).to_numpy(float), (n_sims, 1))
    gf = np.tile(base.reindex(teams)["gf"].fillna(0).to_numpy(float), (n_sims, 1))

    for m in remaining.itertuples(index=False):
        hg, ag = _sample_scores(dc.score_matrix(m.home, m.away), n_sims, rng)
        h, a = idx[m.home], idx[m.away]
        pts[:, h] += np.where(hg > ag, 3, np.where(hg == ag, 1, 0))
        pts[:, a] += np.where(ag > hg, 3, np.where(hg == ag, 1, 0))
        gd[:, h] += hg - ag
        gd[:, a] += ag - hg
        gf[:, h] += hg
        gf[:, a] += ag

    # Rank: points, then goal difference, then goals, then a random tie-break.
    key = pts * 1e6 + (gd + 500) * 1e3 + gf + rng.random(pts.shape) * 0.1
    order = np.argsort(-key, axis=1)
    position = np.empty_like(order)
    position[np.arange(n_sims)[:, None], order] = np.arange(n)[None, :]

    pos_probs = np.stack([(position == k).mean(axis=0) for k in range(n)], axis=1)
    title, europe, relegated = zones
    table = pd.DataFrame({
        "team": teams,
        "pts_actual": base.reindex(teams)["pts"].fillna(0).astype(int).to_numpy(),
        "pts_esperados": pts.mean(axis=0),
        "gd_esperada": gd.mean(axis=0),
        "posicion_media": position.mean(axis=0) + 1,
        "p_campeon": (position < title).mean(axis=0),
        "p_champions": (position < europe).mean(axis=0),
        "p_descenso": (position >= n - relegated).mean(axis=0),
    }).sort_values(["pts_esperados", "gd_esperada"], ascending=False, ignore_index=True)
    positions = pd.DataFrame(pos_probs, index=teams, columns=range(1, n + 1)).loc[table["team"]]
    return SeasonForecast(table, positions, n_sims, len(remaining))


def forecast_league(conn, league: str, season: str | None = None, n_sims: int = 10_000,
                    xg_weight: float = 0.5, seed: int | None = None) -> SeasonForecast:
    season = season or season_code(pd.Timestamp.today().date())
    matches = store.load_matches(conn, [league])
    played = matches[matches["season"] == season]
    remaining = store.load_fixtures(conn, league, season)
    if remaining.empty:
        raise ValueError(f"no hay calendario pendiente de {league} {season} (solo para las 5 grandes)")
    dc = DixonColes(xg_weight=xg_weight).fit(matches)
    return simulate_season(dc, played, remaining, n_sims, seed, ZONES.get(league, DEFAULT_ZONES))


# ─── one match, minute by minute ───────────────────────────────────────────────

# Goals are not uniform over 90': fewer in the first minutes, more near the end of
# each half (fatigue, stoppage time). Relative intensity per 15-minute block, from
# published minute-of-goal distributions of the big leagues (roughly).
GOAL_INTENSITY = np.array([0.80, 0.95, 1.00, 1.00, 1.05, 1.20])


def simulate_timeline(lh: float, la: float, rho: float = 0.0, seed: int | None = None) -> dict:
    """One plausible match: final score drawn from the Dixon-Coles matrix, goal minutes
    drawn from the in-game intensity profile. Deterministic with `seed`."""
    rng = np.random.default_rng(seed)
    hg, ag = (int(x[0]) for x in _sample_scores(score_matrix(lh, la, rho), 1, rng))
    minute_weights = np.repeat(GOAL_INTENSITY, 15)
    minute_weights = minute_weights / minute_weights.sum()
    goals = [("home", int(m)) for m in rng.choice(90, hg, p=minute_weights) + 1] + \
            [("away", int(m)) for m in rng.choice(90, ag, p=minute_weights) + 1]
    goals.sort(key=lambda g: g[1])
    return {"score": [hg, ag], "goals": [{"side": s, "minute": m} for s, m in goals]}


# ─── betting ───────────────────────────────────────────────────────────────────

def betting_backtest(pred: pd.DataFrame, edge: float = 0.05, stake: str = "flat",
                     kelly_fraction: float = 0.25, odds_prefix: str = "avg") -> dict:
    """Bet on every outcome where model_p × odds > 1 + edge, in date order.

    Uses pre-match odds (`avg` = market average, `b365`), never the closing line: you
    can't bet at a price you only learn at kick-off. `stake`: "flat" (1 unit) or
    "kelly" (fraction of the Kelly stake on a bankroll starting at 100 units).
    Also reports closing-line value: whether the odds taken beat the closing odds,
    which is the standard way to tell skill from luck on a few hundred bets.
    """
    cols = [f"{odds_prefix}_{s}" for s in "hda"]
    close = ["close_h", "close_d", "close_a"]
    df = pred.dropna(subset=cols).sort_values("date").reset_index(drop=True)
    p = df[["p_home", "p_draw", "p_away"]].to_numpy()
    odds = df[cols].to_numpy(float)
    closing = df[close].to_numpy(float) if set(close) <= set(df.columns) else np.full_like(odds, np.nan)
    result = np.select([df["fthg"] > df["ftag"], df["fthg"] == df["ftag"]], [0, 1], 2)

    bankroll, peak, max_dd = 100.0, 100.0, 0.0
    bets = []
    for i in range(len(df)):
        for k in range(3):
            value = p[i, k] * odds[i, k] - 1
            if value <= edge:
                continue
            if stake == "kelly":
                amount = bankroll * kelly_fraction * value / (odds[i, k] - 1)
            else:
                amount = 1.0
            won = result[i] == k
            profit = amount * (odds[i, k] - 1) if won else -amount
            bankroll += profit
            peak = max(peak, bankroll)
            max_dd = max(max_dd, (peak - bankroll) / peak)
            clv = odds[i, k] / closing[i, k] - 1 if closing[i, k] > 1 else np.nan
            bets.append({"date": df.at[i, "date"], "match": f"{df.at[i, 'home']} - {df.at[i, 'away']}",
                         "pick": "HDA"[k], "odds": odds[i, k], "p_model": p[i, k], "stake": amount,
                         "profit": profit, "bankroll": bankroll, "clv": clv})
    log = pd.DataFrame(bets)
    if log.empty:
        return {"bets": 0, "log": log}
    staked = log["stake"].sum()
    return {
        "bets": len(log), "staked": staked, "profit": log["profit"].sum(),
        "roi": log["profit"].sum() / staked, "hit_rate": (log["profit"] > 0).mean(),
        "avg_odds": log["odds"].mean(), "final_bankroll": bankroll, "max_drawdown": max_dd,
        "clv_mean": log["clv"].mean(), "clv_positive": (log["clv"] > 0).mean(), "log": log,
    }


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("season")
    s.add_argument("league")
    s.add_argument("--sims", type=int, default=10_000)
    s.add_argument("--seed", type=int, default=0)
    b = sub.add_parser("betting")
    b.add_argument("predictions")
    b.add_argument("--edge", type=float, default=0.05)
    b.add_argument("--stake", choices=["flat", "kelly"], default="flat")
    b.add_argument("--odds", default="avg", choices=["avg", "b365"])
    args = parser.parse_args()

    if args.cmd == "season":
        f = forecast_league(store.connect(), args.league, n_sims=args.sims, seed=args.seed)
        print(f"{args.league}: {f.remaining} partidos por jugar, {f.n_sims} simulaciones\n")
        cols = ["team", "pts_actual", "pts_esperados", "p_campeon", "p_champions", "p_descenso"]
        print(f.table[cols].round(3).to_string(index=False))
    else:
        pred = pd.read_csv(args.predictions, parse_dates=["date"], dtype={"season": str})
        r = betting_backtest(pred, args.edge, args.stake, odds_prefix=args.odds)
        if not r["bets"]:
            print("ninguna apuesta con ese margen")
            return 0
        print(f"{r['bets']} apuestas  ROI {r['roi']:+.2%}  beneficio {r['profit']:+.1f} u"
              f"  acierto {r['hit_rate']:.1%}  cuota media {r['avg_odds']:.2f}"
              f"  banca final {r['final_bankroll']:.1f}  max drawdown {r['max_drawdown']:.1%}"
              f"\nCLV medio {r['clv_mean']:+.2%}  ({r['clv_positive']:.0%} de apuestas mejor que el cierre)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
