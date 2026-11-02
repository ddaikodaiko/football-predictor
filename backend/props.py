"""
Corners and shots on target: how many will each team have?

Four ways to predict them, compared walk-forward (only the past) on the big five:

    base      league average, home and away (last season)
    goals     log-linear on the Dixon-Coles expected goals of each side: a team expected
              to score more attacks more, and so wins more corners and shots
    ratings   Dixon-Coles-style attack/defence ratings fitted on the counts themselves
              (time decay, ridge prior), which picks up style: some teams live off corners
    combined  log-linear on both

Counts are negative binomial (NB2): corners are overdispersed with respect to Poisson.
The dispersion α and the regression weights are fitted on earlier seasons only.

The data has no per-half counts. `split_halves` uses the share of goals scored before
half-time, which is an assumption, not a measurement.

Usage (from backend/, after backtest.py has written the expected goals):
    python props.py                        # big five, 2017/18 onwards
"""

import argparse
import json
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

import store
from backtest import OUT_DIR, PRODUCTION_FILE
from ingest import season_start_year
from ratings import DixonColes

STATS = {"corners": ("hc", "ac"), "sot": ("hst", "ast")}
LAMBDAS_FILE = PRODUCTION_FILE
PRIOR_SD = 0.3              # ridge prior of the count ratings: 0.15-0.3 best, 0.6 and 1.0 a hair worse (≤0.001)
OUT_FILE = "props.csv.gz"
WEIGHTS_FILE = "props_weights.json"


# ─── negative binomial ─────────────────────────────────────────────────────────

def nb_logpmf(y: np.ndarray, mu: np.ndarray, alpha: float) -> np.ndarray:
    """NB2: mean μ, variance μ + αμ²."""
    r = 1.0 / alpha
    return (gammaln(y + r) - gammaln(r) - gammaln(y + 1)
            + r * np.log(r / (r + mu)) + y * np.log(mu / (r + mu)))


def fit_alpha(y: np.ndarray, mu: np.ndarray) -> float:
    res = minimize(lambda a: -nb_logpmf(y, mu, np.exp(a[0])).sum(), [np.log(0.05)], method="Nelder-Mead")
    return float(np.exp(res.x[0]))


def fit_loglinear(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Poisson regression (the mean is what matters; NB2 dispersion goes on top)."""
    f = lambda b: (np.exp(X @ b) - y * (X @ b)).sum()
    g = lambda b: X.T @ (np.exp(X @ b) - y)
    b0 = np.zeros(X.shape[1])
    b0[0] = np.log(y.mean())
    return minimize(f, b0, jac=g, method="BFGS").x


def nb_total_pmf(mu_h: float, mu_a: float, alpha_h: float, alpha_a: float, n: int = 40) -> np.ndarray:
    """Distribution of the sum of both teams' counts (independent NBs)."""
    k = np.arange(n)
    ph = np.exp(nb_logpmf(k, np.full(n, mu_h), alpha_h))
    pa = np.exp(nb_logpmf(k, np.full(n, mu_a), alpha_a))
    return np.convolve(ph, pa)[:n]


# ─── team ratings on counts ────────────────────────────────────────────────────

def as_goals(matches: pd.DataFrame, stat: str) -> pd.DataFrame:
    """The count columns renamed so DixonColes fits them as if they were goals."""
    h, a = STATS[stat]
    df = matches.dropna(subset=[h, a]).drop(columns=["fthg", "ftag", "xg_home", "xg_away"], errors="ignore")
    return df.rename(columns={h: "fthg", a: "ftag"})


def count_model(matches: pd.DataFrame, stat: str, as_of=None, **kw) -> DixonColes:
    return DixonColes(prior_sd=kw.pop("prior_sd", PRIOR_SD), **kw).fit(as_goals(matches, stat), as_of=as_of)


def walk_forward(matches: pd.DataFrame, league: str, seasons: list[str], refit_days: int = 7,
                 prior_sd: float = PRIOR_SD) -> pd.DataFrame:
    """Rating-model predictions for every match of `seasons`, each from the past only."""
    lg = matches[matches["league"] == league].sort_values("date")
    target = lg[lg["season"].isin(seasons)]
    rows = []
    cut, end = target["date"].min().normalize(), target["date"].max() + pd.Timedelta(days=1)
    while cut < end:
        nxt = cut + pd.Timedelta(days=refit_days)
        week = target[(target["date"] >= cut) & (target["date"] < nxt)]
        if not week.empty:
            try:
                models = {s: count_model(lg, s, as_of=cut, prior_sd=prior_sd) for s in STATS}
            except ValueError:
                cut = nxt
                continue
            for m in week.itertuples(index=False):
                row = {"league": league, "season": m.season, "date": m.date, "home": m.home, "away": m.away}
                for s, dc in models.items():
                    row[f"{s}_rating_home"], row[f"{s}_rating_away"] = dc.lambdas(m.home, m.away)
                rows.append(row)
        cut = nxt
    return pd.DataFrame(rows)


# ─── the combined model ────────────────────────────────────────────────────────

FEATURES = {
    "base": [],
    "goals": ["log_lam_own", "log_lam_opp"],
    "ratings": ["log_rating"],
    "combined": ["log_lam_own", "log_lam_opp", "log_rating"],
}


def design(df: pd.DataFrame, stat: str, side: str) -> pd.DataFrame:
    """One row per (match, side) with the features and the observed count."""
    own, opp = ("home", "away") if side == "home" else ("away", "home")
    col = STATS[stat][0 if side == "home" else 1]
    return pd.DataFrame({
        "season": df["season"].to_numpy(), "league": df["league"].to_numpy(),
        "y": df[col].to_numpy(float),
        "log_lam_own": np.log(df[f"lambda_{own}"].to_numpy(float)),
        "log_lam_opp": np.log(df[f"lambda_{opp}"].to_numpy(float)),
        "log_rating": np.log(df[f"{stat}_rating_{own}"].to_numpy(float)),
    })


def evaluate(df: pd.DataFrame) -> pd.DataFrame:
    """Each season predicted with weights and α fitted on the seasons before it."""
    seasons = sorted(df["season"].unique(), key=season_start_year)
    rows = []
    for stat in STATS:
        for side in ("home", "away"):
            d = design(df, stat, side)
            for s in seasons[1:]:
                train, test = d[d["season"].map(season_start_year) < season_start_year(s)], d[d["season"] == s]
                for name, feats in FEATURES.items():
                    Xtr = np.column_stack([np.ones(len(train)), *(train[f] for f in feats)])
                    Xte = np.column_stack([np.ones(len(test)), *(test[f] for f in feats)])
                    b = fit_loglinear(Xtr, train["y"].to_numpy())
                    alpha = fit_alpha(train["y"].to_numpy(), np.exp(Xtr @ b))
                    mu = np.exp(Xte @ b)
                    rows.append({"stat": stat, "side": side, "season": s, "model": name, "n": len(test),
                                 "nll": -nb_logpmf(test["y"].to_numpy(), mu, alpha).mean(),
                                 "mae": np.abs(test["y"].to_numpy() - mu).mean(), "alpha": alpha})
    return pd.DataFrame(rows)


def calibration(df: pd.DataFrame, lines: dict[str, list[float]]) -> pd.DataFrame:
    """P(total over line) walk-forward, grouped by what the model said, against how often
    it happened."""
    seasons = sorted(df["season"].unique(), key=season_start_year)
    rows = []
    for stat, ls in lines.items():
        dh, da = design(df, stat, "home"), design(df, stat, "away")
        for s in seasons[1:]:
            past = dh["season"].map(season_start_year) < season_start_year(s)
            now = (dh["season"] == s).to_numpy()
            mus, alphas = [], []
            for d in (dh, da):
                X = np.column_stack([np.ones(len(d)), *(d[f] for f in FEATURES["combined"])])
                b = fit_loglinear(X[past], d["y"].to_numpy()[past])
                alphas.append(fit_alpha(d["y"].to_numpy()[past], np.exp(X[past] @ b)))
                mus.append(np.exp(X[now] @ b))
            total = dh["y"].to_numpy()[now] + da["y"].to_numpy()[now]
            for k in range(now.sum()):
                pt = nb_total_pmf(mus[0][k], mus[1][k], *alphas)
                for L in ls:
                    rows.append({"stat": stat, "line": L, "p": 1 - pt[:int(L) + 1].sum(), "hit": total[k] > L})
    cal = pd.DataFrame(rows)
    cal["bin"] = pd.cut(cal["p"], [0, .3, .4, .5, .6, .7, 1])
    return (cal.groupby(["stat", "line", "bin"], observed=True)
            .agg(n=("hit", "size"), modelo=("p", "mean"), real=("hit", "mean")).reset_index())


# ─── serving ───────────────────────────────────────────────────────────────────

def fit_weights(df: pd.DataFrame) -> dict:
    """The combined model's weights and α, on every evaluated season, for the live app."""
    out = {}
    for stat in STATS:
        for side in ("home", "away"):
            d = design(df, stat, side)
            X = np.column_stack([np.ones(len(d)), *(d[f] for f in FEATURES["combined"])])
            b = fit_loglinear(X, d["y"].to_numpy())
            out[f"{stat}_{side}"] = {"coef": [round(float(x), 5) for x in b],
                                     "alpha": round(fit_alpha(d["y"].to_numpy(), np.exp(X @ b)), 5)}
    return out


def load_weights() -> dict | None:
    path = OUT_DIR / WEIGHTS_FILE
    return json.loads(path.read_text()) if path.exists() else None


def predict(weights: dict, lambdas: tuple[float, float], ratings: dict[str, tuple[float, float]]) -> dict:
    """Expected count per team and its dispersion. `ratings`: stat -> (home, away) from
    the count models. The lines are computed from this by `markets` (and by the same
    code in frontend/src/lib/props.ts)."""
    lh, la = lambdas
    out = {}
    for stat in STATS:
        own = {"home": (lh, la, ratings[stat][0]), "away": (la, lh, ratings[stat][1])}
        out[stat] = {}
        for side, (l_own, l_opp, r) in own.items():
            w = weights[f"{stat}_{side}"]
            out[stat][side] = float(np.exp(np.dot(w["coef"], [1, np.log(l_own), np.log(l_opp), np.log(r)])))
            out[stat][f"alpha_{side}"] = w["alpha"]
    return out


def nb_pmf(mu: float, alpha: float, n: int = 40) -> np.ndarray:
    """NB2 pmf by recurrence (no gamma function, so TypeScript does exactly the same)."""
    r = 1.0 / alpha
    q = mu / (r + mu)
    p = np.empty(n)
    p[0] = (r / (r + mu)) ** r
    for k in range(n - 1):
        p[k + 1] = p[k] * (k + r) / (k + 1) * q
    return p


def markets(params: dict, first_half: float) -> dict:
    """Means and P(over line) per team and in total, for the match and each half.
    A half is NB with the same α and the mean scaled: the match's intensity is shared by
    both halves (a match with many corners has them in both). The split is the goal
    profile's, an assumption: the data has no per-half corners or shots."""
    out = {}
    for stat in STATS:
        p = params[stat]
        out[stat] = {}
        for period, share in (("match", 1.0), ("first", first_half), ("second", 1 - first_half)):
            ph = nb_pmf(p["home"] * share, p["alpha_home"])
            pa = nb_pmf(p["away"] * share, p["alpha_away"])
            pt = np.convolve(ph, pa)[:len(ph)]
            over = lambda pmf: {f"{k + 0.5:g}": round(float(1 - pmf[:k + 1].sum()), 4) for k in range(15)}
            out[stat][period] = {"home": round(p["home"] * share, 3), "away": round(p["away"] * share, 3),
                                 "over_home": over(ph), "over_away": over(pa), "over_total": over(pt)}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--leagues", default="E0,SP1,D1,I1,F1")
    parser.add_argument("--from", dest="first", type=int, default=2016)
    parser.add_argument("--to", dest="last", type=int, default=2025)
    parser.add_argument("--prior", type=float, default=PRIOR_SD, help="ridge prior sd of the count ratings")
    args = parser.parse_args()

    t0 = time.time()
    leagues = args.leagues.split(",")
    matches = store.load_matches(store.connect(), leagues)
    seasons = sorted({s for s in matches["season"] if args.first <= season_start_year(s) <= args.last})
    rat = pd.concat([walk_forward(matches, lg, seasons, prior_sd=args.prior) for lg in leagues], ignore_index=True)
    lam = pd.read_csv(OUT_DIR / LAMBDAS_FILE, parse_dates=["date"],
                      usecols=["league", "date", "home", "away", "lambda_home", "lambda_away"])
    counts = matches[["league", "date", "home", "away", "hc", "ac", "hst", "ast"]]
    df = rat.merge(lam, on=["league", "date", "home", "away"]).merge(counts, on=["league", "date", "home", "away"])
    df = df.dropna(subset=["hc", "ac", "hst", "ast", "lambda_home", "lambda_away"])
    df.to_csv(OUT_DIR / OUT_FILE, index=False)

    weights = fit_weights(df)
    (OUT_DIR / WEIGHTS_FILE).write_text(json.dumps(weights, indent=1))
    res = evaluate(df)
    summary = (res.assign(w=res["nll"] * res["n"], wm=res["mae"] * res["n"])
               .groupby(["stat", "model"])[["w", "wm", "n"]].sum())
    summary["nll"], summary["mae"] = summary["w"] / summary["n"], summary["wm"] / summary["n"]
    print(f"{len(df)} partidos, {seasons[1]}-{seasons[-1]} evaluadas, {time.time() - t0:.0f} s")
    for stat in STATS:
        t = summary.loc[stat, ["nll", "mae", "n"]]
        t["mejora_vs_base"] = t.loc["base", "nll"] - t["nll"]
        print(f"\n{stat} (por equipo y partido; log loss NB, menos es mejor)")
        print(t.round(4).to_string())

    cal = calibration(df, {"corners": [8.5, 9.5, 10.5], "sot": [7.5, 8.5, 9.5]})
    print("\nCalibración del total (más de la línea), modelo combinado:")
    print(cal.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
