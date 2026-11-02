"""
What the market adjusts for that team strengths can't see, learned with gradient boosting.

The filter (statespace.py) predicts each match from the two teams' strengths. The market
prices the same match knowing more: who is rested, who still has something to play for,
how a team has been doing lately. Every past match says how far the market moved from
the strengths (its residual, on the log λ scale), so a model can learn that adjustment:

    target    log λ the market priced − log λ the filter predicted, per side
    features  only what is known before kick-off: days of rest, the table (gaps to the
              top and to the drop, matches left), recent results against their price,
              the residuals of each team's previous matches, the filter's own
              uncertainty and the predicted rates themselves, league and weekday

The target is a price, not a result, so it is far less noisy than goals: effects of a few
hundredths of a goal are learnable from a hundred thousand matches. The model is trained
season by season on the past only (expanding window) and adds its prediction to the
filter's log rates before the score matrix is built.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

FEATURES = [
    "rest_home", "rest_away", "weekday", "progress", "tier",
    "gap_top_home", "gap_top_away", "gap_drop_home", "gap_drop_away", "pos_home", "pos_away", "left",
    "surprise_for_home", "surprise_against_home", "surprise_for_away", "surprise_against_away",
    "res_att_home", "res_def_home", "res_att_away", "res_def_away",
    "last_res_att_home", "last_res_def_home", "last_res_att_away", "last_res_def_away",
    "sd_home", "sd_away", "m_home", "m_away", "league_code",
    "xg_for_home", "xg_against_home", "xg_for_away", "xg_against_away",
    "sot_for_home", "sot_against_home", "sot_for_away", "sot_against_away",
    "surprise_for_long_home", "surprise_against_long_home", "surprise_for_long_away", "surprise_against_long_away",
    "venue_att_home", "venue_def_home", "venue_att_away", "venue_def_away",
    "new_home", "new_away",
]
RELEGATED = 3
COUNTRIES = {"E": 0, "SP": 1, "D": 2, "I": 3, "F": 4, "N": 5, "P": 6}


def team_long(df: pd.DataFrame) -> pd.DataFrame:
    """One row per team and match, in date order, with what the team scored and conceded,
    what the market expected, and the residuals of the market against the filter."""
    cols = {"row": df.index.to_numpy(), "date": df["date"].to_numpy(), "league": df["league"].to_numpy(),
            "season": df["season"].to_numpy()}
    xg = df[["xg_home", "xg_away"]].to_numpy(float) * df["xg_scale"].to_numpy(float)[:, None] \
        if "xg_scale" in df else np.full((len(df), 2), np.nan)
    sot = df[["hst", "ast"]].to_numpy(float)
    sides = []
    for k, (team, us, them) in enumerate((("home", "home", "away"), ("away", "away", "home"))):
        c, o = (0, 1) if k == 0 else (1, 0)
        sides.append(pd.DataFrame({
            **cols, "team": df[team].to_numpy(), "side": k,
            "gf": df[["fthg", "ftag"]].to_numpy(float)[:, c], "ga": df[["fthg", "ftag"]].to_numpy(float)[:, o],
            "mf": df[f"mkt_{us}"].to_numpy(float), "ma": df[f"mkt_{them}"].to_numpy(float),
            "xf": xg[:, c], "xa": xg[:, o], "sf": sot[:, c], "sa": sot[:, o],
            "res_att": df[f"res_{us}"].to_numpy(float), "res_def": df[f"res_{them}"].to_numpy(float)}))
    home, away = sides
    return pd.concat([home, away]).sort_values(["team", "date", "row"], kind="stable").reset_index(drop=True)


def _ewm(s: pd.Series, by: pd.Series, halflife: float) -> pd.Series:
    """Exponentially weighted mean of each group's PREVIOUS values."""
    shifted = s.groupby(by, sort=False).shift(1)
    return shifted.groupby(by, sort=False).transform(lambda v: v.ewm(halflife=halflife, ignore_na=True).mean())


def _lagged(long: pd.DataFrame) -> pd.DataFrame:
    """Per team, everything up to (not including) each match."""
    team = long["team"]
    prev_date = long.groupby("team", sort=False)["date"].shift(1)
    out = pd.DataFrame({"row": long["row"], "side": long["side"]})
    out["rest"] = ((long["date"] - prev_date).dt.days).clip(upper=30).fillna(30)
    surprise_for, surprise_against = long["gf"] - long["mf"], long["ga"] - long["ma"]
    out["surprise_for"], out["surprise_against"] = _ewm(surprise_for, team, 3), _ewm(surprise_against, team, 3)
    out["surprise_for_long"] = _ewm(surprise_for, team, 12)
    out["surprise_against_long"] = _ewm(surprise_against, team, 12)
    out["xg_for"], out["xg_against"] = _ewm(long["xf"] - long["mf"], team, 4), _ewm(long["xa"] - long["ma"], team, 4)
    # Shots on target, relative to the rates the market expected (λ ≈ a third of them).
    out["sot_for"] = _ewm(long["sf"] / long["mf"], team, 4)
    out["sot_against"] = _ewm(long["sa"] / long["ma"], team, 4)
    for name in ("res_att", "res_def"):
        out[name] = _ewm(long[name], team, 3)
        out[f"last_{name}"] = long[name].groupby(team, sort=False).shift(1)
        # The same residual, only at this venue: some home advantages aren't the league's.
        venue = team + "|" + long["side"].astype(str)
        out[f"venue_{name.split('_')[1]}"] = _ewm(long[name], venue, 10)
    return out


def _table(df: pd.DataFrame) -> pd.DataFrame:
    """Gaps to the top and to the relegation line before each match, from the points of
    that league and season so far."""
    cols = ["gap_top_home", "gap_top_away", "gap_drop_home", "gap_drop_away", "pos_home", "pos_away", "left", "progress"]
    out = np.full((len(df), len(cols)), np.nan)
    for _, g in df.groupby(["league", "season"], sort=False):
        g = g.sort_values("date", kind="stable")
        teams, codes = np.unique(np.concatenate([g["home"], g["away"]]), return_inverse=True)
        n = len(g)
        out[df.index.get_indexer(g.index)] = _table_kernel(
            codes[:n].astype(np.int64), codes[n:].astype(np.int64), len(teams),
            g["date"].to_numpy("datetime64[D]").astype(np.int64),
            g["fthg"].to_numpy(float), g["ftag"].to_numpy(float))
    return pd.DataFrame(out, columns=cols, index=df.index)


@njit(cache=True)
def _table_kernel(hi, ai, n_teams, days, gh, ga):
    out = np.empty((len(hi), 8))
    pts, played, gd = np.zeros(n_teams), np.zeros(n_teams), np.zeros(n_teams)
    total = 2 * (n_teams - 1)
    s = 0
    while s < len(hi):
        e = s
        while e < len(hi) and days[e] == days[s]:
            e += 1
        order = np.argsort(-(pts * 1000 + gd), kind="mergesort")
        rank = np.empty(n_teams)
        for k in range(n_teams):
            rank[order[k]] = k
        top = pts.max()
        drop_line = np.sort(pts)[::-1][n_teams - RELEGATED] if n_teams > RELEGATED else 0.0
        for r in range(s, e):
            h, a = hi[r], ai[r]
            out[r, 0], out[r, 1] = top - pts[h], top - pts[a]
            out[r, 2], out[r, 3] = pts[h] - drop_line, pts[a] - drop_line
            out[r, 4], out[r, 5] = rank[h] / (n_teams - 1), rank[a] / (n_teams - 1)
            out[r, 6] = total - (played[h] + played[a]) / 2
            out[r, 7] = (played[h] + played[a]) / (2 * total)
        for r in range(s, e):
            if np.isnan(gh[r]) or np.isnan(ga[r]):
                continue
            h, a = hi[r], ai[r]
            pts[h] += 3 if gh[r] > ga[r] else 1 if gh[r] == ga[r] else 0
            pts[a] += 3 if ga[r] > gh[r] else 1 if gh[r] == ga[r] else 0
            gd[h] += gh[r] - ga[r]
            gd[a] += ga[r] - gh[r]
            played[h] += 1
            played[a] += 1
        s = e
    return out


def features(df: pd.DataFrame, pred_mean: np.ndarray, pred_cov: np.ndarray, primary: str) -> pd.DataFrame:
    """Feature table (one row per match of `df`, same order) plus the targets res_home and
    res_away. `pred_mean`/`pred_cov` are the filter's forecasts for every row."""
    df = df.assign(res_home=np.log(df["mkt_home"]) - pred_mean[:, 0],
                   res_away=np.log(df["mkt_away"]) - pred_mean[:, 1])
    lag = _lagged(team_long(df))
    h = lag[lag["side"] == 0].set_index("row").add_suffix("_home")
    a = lag[lag["side"] == 1].set_index("row").add_suffix("_away")
    out = pd.concat([h, a], axis=1).reindex(df.index).drop(columns=["side_home", "side_away"])
    out = out.join(_table(df.reset_index(drop=True)).set_axis(df.index))
    out["weekday"] = df["date"].dt.dayofweek
    out["tier"] = (df["league"] != primary).astype(int)
    out["league_code"] = df["league"].str.rstrip("0123456789").map(COUNTRIES)
    out["sd_home"], out["sd_away"] = np.sqrt(pred_cov[:, 0]), np.sqrt(pred_cov[:, 1])
    out["m_home"], out["m_away"] = pred_mean[:, 0], pred_mean[:, 1]
    # First season in this division (promoted, or relegated into it).
    seen = set(zip(df["home"], df["league"], df["season"]))
    prev = {s: f"{int(s[:2]) - 1:02d}{int(s[2:]) - 1:02d}" for s in df["season"].unique()}
    for side in ("home", "away"):
        out[f"new_{side}"] = [int((t, lg, prev[s]) not in seen) for t, lg, s in zip(df[side], df["league"], df["season"])]
    out["res_home"], out["res_away"] = df["res_home"], df["res_away"]
    return out


# ─── training and backtest ─────────────────────────────────────────────────────

PARAMS = {"n_estimators": 600, "learning_rate": 0.03, "max_depth": 4, "min_child_weight": 50,
          "subsample": 0.8, "colsample_bytree": 0.8, "reg_lambda": 5.0, "tree_method": "hist"}


def train(table: pd.DataFrame, side: str, seed: int = 0):
    """XGBoost regressor of one side's residual, on rows that have a price."""
    from xgboost import XGBRegressor
    ok = table[f"res_{side}"].notna()
    model = XGBRegressor(**PARAMS, random_state=seed, n_jobs=4)
    model.fit(table.loc[ok, FEATURES], table.loc[ok, f"res_{side}"])
    return model


def build(matches: pd.DataFrame, leagues: list[str], hyper, first: str = "2006-07-01") -> pd.DataFrame:
    """Filter forecasts (weekly, as the backtest) and features for every match of each
    group from `first` on, both divisions."""
    import statespace as ss
    parts = []
    for lg in leagues:
        df = ss.group(matches, lg)
        mask = (df["date"] >= pd.Timestamp(first)).to_numpy()
        cuts = pd.date_range(pd.Timestamp(first), df["date"].max() + pd.Timedelta(days=1), freq="7D")
        model = ss.StateSpace(hyper).run(df, lg, cuts=cuts, predict=mask)
        f = features(df, model.pred_mean, model.pred_cov, lg)
        keep = ["league", "season", "date", "home", "away", "fthg", "ftag", "mkt_home", "mkt_away"]
        odds = [c for c in df.columns if c.split("_")[0] in {"b365", "avg", "pin", "close", "ou"}]
        part = pd.concat([df[keep + odds], f], axis=1)
        part["primary"] = df["league"] == lg
        part["cov01"] = model.pred_cov[:, 2]
        parts.append(part[mask])
    return pd.concat(parts, ignore_index=True)


def walk_forward(table: pd.DataFrame, seasons: list[str], seed: int = 0) -> np.ndarray:
    """(n, 2) predicted residuals for the rows of `table` in `seasons`, each season from
    a model trained on the seasons before it only (NaN elsewhere)."""
    out = np.full((len(table), 2), np.nan)
    for season in seasons:
        test = (table["season"] == season).to_numpy()
        past = table[table["season"] < season]
        if not test.any() or past.empty:
            continue
        for k, side in enumerate(("home", "away")):
            out[test, k] = train(past, side, seed).predict(table.loc[test, FEATURES])
    return out


def main() -> int:
    import argparse
    import time

    import statespace as ss
    import store
    from backtest import COMPANION, OUT_DIR, report
    from ingest import season_start_year
    from market import remove_margin

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--leagues", default="E0,SP1,D1,I1,F1")
    parser.add_argument("--from", dest="first", type=int, default=2016)
    parser.add_argument("--to", dest="last", type=int, default=2025)
    parser.add_argument("--hyper", default=str(ss.PARAMS_FILE), help="noise model of the filter ('default': none)")
    parser.add_argument("--name", default="ss_context")
    args = parser.parse_args()

    leagues = args.leagues.split(",")
    matches = store.load_matches(store.connect(), leagues + [COMPANION[l] for l in leagues if l in COMPANION])
    hyper = ss.Hyper() if args.hyper == "default" else ss.Hyper.load(Path(args.hyper))
    t0 = time.time()
    table = build(matches, leagues, hyper)
    seasons = sorted({s for s in table["season"] if args.first <= season_start_year(s) <= args.last})
    adj = walk_forward(table, seasons)
    scored = (table["primary"] & table["season"].isin(seasons)).to_numpy()
    t = table[scored].reset_index(drop=True)
    mean = t[["m_home", "m_away"]].to_numpy()
    cov = np.stack([np.stack([t["sd_home"] ** 2, t["cov01"]], -1), np.stack([t["cov01"], t["sd_away"] ** 2], -1)], -2)
    cov = cov + hyper.match_sd ** 2 * np.array([[1, hyper.match_corr], [hyper.match_corr, 1]])
    y_over = (t["fthg"] + t["ftag"] > 2.5).to_numpy()
    p_ou = remove_margin(t[["ou_close_o", "ou_close_u"]].to_numpy(float))[:, 0] if "ou_close_o" in t else None
    print(f"\n== {args.name}  ({seasons[0]}-{seasons[-1]}, {time.time() - t0:.0f} s)")
    for label, m in (("filtro", mean), ("filtro + contexto", mean + adj[scored])):
        mat = ss.mixture_matrices(m, cov)
        i, j = np.indices(mat.shape[1:])
        pred = t.assign(p_home=np.tril(mat, -1).sum(axis=(1, 2)), p_draw=np.trace(mat, axis1=1, axis2=2),
                        p_away=np.triu(mat, 1).sum(axis=(1, 2)), p_over25=mat[:, i + j > 2.5].sum(axis=1))
        table_ = report(pred)
        n = table_["partidos"].sum()
        w = lambda c: (table_[c] * table_["partidos"]).sum() / n
        po = np.clip(pred["p_over25"].to_numpy(), 1e-9, 1 - 1e-9)
        ok = ~np.isnan(p_ou) if p_ou is not None else np.zeros(len(po), bool)
        ll_ou = lambda p: float(-np.mean(np.where(y_over[ok], np.log(p[ok]), np.log(1 - p[ok]))))
        print(f"{label:<18} {n} partidos  logloss {w('logloss_modelo'):.4f} (mercado {w('logloss_mercado'):.4f})"
              f"  rps {w('rps_modelo'):.4f}  más/menos 2,5 {ll_ou(po):.4f} (cierre {ll_ou(p_ou):.4f}, {ok.sum()})")
        print(table_[["league", "partidos", "logloss_modelo", "logloss_mercado"]].round(4).to_string(index=False))
        if label != "filtro":
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            pred.to_csv(OUT_DIR / f"{args.name}.csv.gz", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
