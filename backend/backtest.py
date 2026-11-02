"""
Walk-forward backtest: how good are the model's probabilities, honestly?

For each league and season, the model is refitted every week using ONLY matches played
before that week, predicts the week's matches, and is scored against what happened.
The same matches are scored with the bookmakers' probabilities (odds with the margin
removed). The market is the benchmark: beating a naive baseline is easy, getting close
to Pinnacle's closing line is hard.

Usage (from backend/):
    python backtest.py                                   # big five, 2016/17 onwards
    python backtest.py --leagues SP1 --from 2019 --xg 0,0.5,1

Writes every prediction to data/backtest/<config>.csv.gz (the betting simulator
replays these) and prints log loss / Brier / RPS per league.
"""

import argparse
import os
import time
from pathlib import Path

# Before numpy: BLAS threads barely help on vectors of a few thousand matches, and they
# make parallel runs fight over the cores. With one thread each, six configurations run
# side by side in ~100 s.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "FLEXIBLAS_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402
import pandas as pd

import market
import store
from ingest import season_start_year
from ratings import DixonColes, outcome_probs

OUT_DIR = store.DATA_DIR / "backtest"
# The run the app shows on "El modelo" and props.py reads expected goals from:
#   python backtest.py --joint --xg 0 --market 1 --market-xi 0.03 --prior 10 --name dc_market
PRODUCTION_FILE = "dc_market.csv.gz"
# The goals + xG model it replaced, shown next to it as the reference without the market:
#   python backtest.py --joint --xg 0.5 --name dc_joint_rescaled
REFERENCE_FILE = "dc_joint_rescaled.csv.gz"
OUTCOMES = ["H", "D", "A"]


# ─── bookmaker probabilities ───────────────────────────────────────────────────

def implied_probs(odds: np.ndarray) -> np.ndarray:
    """Decimal odds (n, 3) -> probabilities with the bookmaker margin removed
    proportionally. NaN rows stay NaN."""
    inv = 1.0 / odds
    return inv / inv.sum(axis=1, keepdims=True)


def market_probs(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Best available market per match: Pinnacle closing > Pinnacle > average > Bet365.
    Returns (probs (n, 3), source label per row)."""
    probs = np.full((len(df), 3), np.nan)
    source = np.full(len(df), None, dtype=object)
    for label, cols in [("b365", ["b365_h", "b365_d", "b365_a"]), ("media", ["avg_h", "avg_d", "avg_a"]),
                        ("pinnacle", ["pin_h", "pin_d", "pin_a"]), ("cierre", ["close_h", "close_d", "close_a"])]:
        if not set(cols) <= set(df.columns):
            continue
        odds = df[cols].apply(pd.to_numeric, errors="coerce").to_numpy(float)
        ok = np.all(odds > 1.0, axis=1)
        probs[ok] = implied_probs(odds[ok])
        source[ok] = label
    return probs, source


# ─── scoring ───────────────────────────────────────────────────────────────────

def outcome_index(df: pd.DataFrame) -> np.ndarray:
    return np.select([df["fthg"] > df["ftag"], df["fthg"] == df["ftag"]], [0, 1], 2)


def scores(p: np.ndarray, y: np.ndarray) -> dict:
    """Mean log loss, Brier and ranked probability score. Lower is better for all three."""
    onehot = np.eye(3)[y]
    logloss = -np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1))
    brier = ((p - onehot) ** 2).sum(axis=1)
    rps = (((np.cumsum(p, axis=1) - np.cumsum(onehot, axis=1))[:, :2]) ** 2).sum(axis=1) / 2
    return {"n": len(y), "log_loss": logloss.mean(), "brier": brier.mean(), "rps": rps.mean(),
            "accuracy": (p.argmax(axis=1) == y).mean()}


# ─── walk-forward ──────────────────────────────────────────────────────────────

# Second division fitted together with each first division (see ratings.DixonColes).
COMPANION = {"E0": "E1", "SP1": "SP2", "D1": "D2", "I1": "I2", "F1": "F2"}


def walk_forward(matches: pd.DataFrame, league: str, seasons: list[str], xg_weight: float,
                 refit_days: int = 7, joint: bool = False, long_prior: bool = False, **dc_kwargs) -> pd.DataFrame:
    """Predict every match of `seasons` with a model fitted on the past only."""
    lg = matches[matches["league"] == league].sort_values("date")
    fit_on = lg
    if joint and league in COMPANION:
        fit_on = matches[matches["league"].isin([league, COMPANION[league]])].sort_values("date")
    target = lg[lg["season"].isin(seasons)]
    if target.empty:
        return pd.DataFrame()
    rows = []
    start = target["date"].min().normalize()
    end = target["date"].max() + pd.Timedelta(days=1)
    cut = start
    while cut < end:
        nxt = cut + pd.Timedelta(days=refit_days)
        week = target[(target["date"] >= cut) & (target["date"] < nxt)]
        if not week.empty:
            try:
                prior = None
                if long_prior:
                    # Long-run club strength: 8 years, slow decay, goals only (xG starts in 2014).
                    prior = DixonColes(xi=0.0005, max_days=8 * 365, prior_sd=1.0).fit(fit_on, as_of=cut, primary=league)
                dc = DixonColes(xg_weight=xg_weight, **dc_kwargs).fit(fit_on, as_of=cut, primary=league, prior=prior)
            except ValueError:
                cut = nxt
                continue
            for m in week.itertuples(index=False):
                lh, la = dc.lambdas(m.home, m.away)
                sm = dc.score_matrix(m.home, m.away)
                ph, pd_, pa = outcome_probs(sm)
                i, j = np.indices(sm.shape)
                rows.append({"p_over25": float(sm[i + j > 2.5].sum()),"league": league, "season": m.season, "date": m.date,
                             "home": m.home, "away": m.away, "fthg": m.fthg, "ftag": m.ftag,
                             "p_home": ph, "p_draw": pd_, "p_away": pa,
                             "lambda_home": lh, "lambda_away": la, "rho": dc.rho,
                             "known": dc.knows(m.home) and dc.knows(m.away)})
        cut = nxt
    out = pd.DataFrame(rows)
    # Carry the odds along so the betting simulator can replay the season.
    odds_cols = [c for c in store.MATCH_COLUMNS
                 if c.split("_")[0] in {"b365", "avg", "pin", "close", "ou", "ah"} and c in target.columns]
    return out.merge(target[["date", "home", "away", *odds_cols]], on=["date", "home", "away"], how="left")


def report(pred: pd.DataFrame) -> pd.DataFrame:
    """Model vs market on the matches where the market is available."""
    y = outcome_index(pred)
    model = pred[["p_home", "p_draw", "p_away"]].to_numpy()
    market, source = market_probs(pred)
    ok = ~np.isnan(market).any(axis=1)
    rows = []
    for league, idx in pred.groupby("league").indices.items():
        idx = idx[ok[idx]]
        if len(idx) == 0:
            continue
        m, b = scores(model[idx], y[idx]), scores(market[idx], y[idx])
        base = np.tile(np.bincount(y[idx], minlength=3) / len(idx), (len(idx), 1))
        rows.append({"league": league, "partidos": m["n"],
                     "logloss_modelo": m["log_loss"], "logloss_mercado": b["log_loss"],
                     "logloss_base": scores(base, y[idx])["log_loss"],
                     "rps_modelo": m["rps"], "rps_mercado": b["rps"],
                     "acierto_modelo": m["accuracy"], "acierto_mercado": b["accuracy"],
                     "mercado": pd.Series(source[idx]).mode().iat[0]})
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--leagues", default="E0,SP1,D1,I1,F1")
    parser.add_argument("--from", dest="first", type=int, default=2016)
    parser.add_argument("--to", dest="last", type=int, default=2025, help="last season start year")
    parser.add_argument("--xg", default="0,0.5", help="xg_weight values to compare")
    parser.add_argument("--market", default="0", help="market_weight values to compare (prices of past matches)")
    parser.add_argument("--market-xi", default="", help="time decay of the prices, values to compare (default: --xi)")
    parser.add_argument("--market-ou", type=float, default=1.0, help="weight of over/under prices when inverting them")
    parser.add_argument("--xi", type=float, default=0.003)
    parser.add_argument("--prior", type=float, default=1.0)
    parser.add_argument("--max-days", type=int, default=3 * 365)
    parser.add_argument("--joint", action="store_true", help="fit each first division with its second")
    parser.add_argument("--name", default=None, help="output file name (default: from the parameters)")
    parser.add_argument("--home-recent", type=int, default=0, help="days of extra recent home advantage")
    parser.add_argument("--long-prior", action="store_true", help="shrink towards each club's long-run rating")
    args = parser.parse_args()

    conn = store.connect()
    leagues = args.leagues.split(",")
    extra = [COMPANION[l] for l in leagues if args.joint and l in COMPANION]
    matches = market.add_market_lambdas(store.load_matches(conn, leagues + extra), args.market_ou)
    seasons = sorted({s for s in matches["season"] if args.first <= season_start_year(s) <= args.last})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    market_xis = [float(v) for v in args.market_xi.split(",")] if args.market_xi else [None]
    configs = [(float(x), float(m), mx) for x in args.xg.split(",") for m in args.market.split(",") for mx in market_xis]
    for w, mw, mx in configs:
        name = f"dc_xg{w:g}_xi{args.xi:g}"
        if mw:
            name += f"_mkt{mw:g}" + (f"_mxi{mx:g}" if mx is not None else "")
        if args.prior != 1.0:
            name += f"_sd{args.prior:g}"
        if args.max_days != 3 * 365:
            name += f"_d{args.max_days}"
        if args.joint:
            name += "_joint"
        name = args.name if args.name and len(configs) == 1 else (f"{args.name}_{name}" if args.name else name)
        t0 = time.time()
        pred = pd.concat([walk_forward(matches, lg, seasons, w, joint=args.joint, long_prior=args.long_prior, xi=args.xi,
                                       prior_sd=args.prior, max_days=args.max_days,
                                       home_recent_days=args.home_recent, market_weight=mw, market_xi=mx)
                          for lg in leagues], ignore_index=True)
        pred.to_csv(OUT_DIR / f"{name}.csv.gz", index=False)
        table = report(pred)
        total = table["partidos"].sum()
        weighted = lambda c: (table[c] * table["partidos"]).sum() / total
        print(f"\n== {name}  ({seasons[0]}-{seasons[-1]}, {total} partidos, {time.time() - t0:.0f} s)")
        print(table.round(4).to_string(index=False))
        print(f"TOTAL  logloss modelo {weighted('logloss_modelo'):.4f}  mercado {weighted('logloss_mercado'):.4f}"
              f"  base {weighted('logloss_base'):.4f}   rps modelo {weighted('rps_modelo'):.4f}"
              f"  mercado {weighted('rps_mercado'):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
