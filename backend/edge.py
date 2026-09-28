"""
Where can the model beat the bookmakers? Segment by segment, three questions:

  1. Accuracy: log loss of the model, of the pre-match market and of the closing line.
  2. Information: does adding the model to the pre-match market improve it? Both are
     fitted together (walk-forward, season by season, only on the past) and compared with
     the market alone passed through the same recalibration. If the combination wins, the
     model knows something the price didn't have yet.
  3. Closing-line value: betting where the model sees value at the pre-match price, is
     that price better than the closing line? Measured as the expected value of each bet
     under the closing line's fair probability (margin removed): the standard way to
     tell skill from luck, because it doesn't depend on who won.

Usage (from backend/):
    python backtest.py --leagues <all> --from 2019 --xg 0.5 --joint --name edge_all_2019
    python edge.py data/backtest/edge_all_2019.csv.gz
"""

import argparse
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from backtest import implied_probs

MARKETS = {
    "1x2": {"model": ["p_home", "p_draw", "p_away"], "pre": ["avg_h", "avg_d", "avg_a"],
            "close": ["close_h", "close_d", "close_a"], "labels": "HDA"},
    "ou25": {"model": ["p_over25"], "pre": ["ou_avg_o", "ou_avg_u"],
             "close": ["ou_close_o", "ou_close_u"], "labels": "OU"},
}


def _outcome(df: pd.DataFrame, market: str) -> np.ndarray:
    if market == "1x2":
        return np.select([df["fthg"] > df["ftag"], df["fthg"] == df["ftag"]], [0, 1], 2)
    return np.where(df["fthg"] + df["ftag"] > 2.5, 0, 1)


def _probs(df: pd.DataFrame, market: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    spec = MARKETS[market]
    model = df[spec["model"]].to_numpy(float)
    if market == "ou25":
        model = np.column_stack([model[:, 0], 1 - model[:, 0]])
    pre = implied_probs(df[spec["pre"]].to_numpy(float))
    close = implied_probs(df[spec["close"]].to_numpy(float))
    return model, pre, close


def _logloss(p: np.ndarray, y: np.ndarray) -> float:
    return float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1)).mean())


def _logit_features(*ps: np.ndarray) -> np.ndarray:
    cols = []
    for p in ps:
        logp = np.log(np.clip(p, 1e-6, 1))
        cols.append(logp[:, 1:] - logp[:, [0]])
    return np.column_stack(cols)


def information_gain(df: pd.DataFrame, market: str) -> tuple[float, float, int]:
    """(log loss market recalibrated, log loss market + model, n), walk-forward by season."""
    model, pre, _ = _probs(df, market)
    y = _outcome(df, market)
    seasons = sorted(df["season"].unique())
    x_market, x_both = _logit_features(pre), _logit_features(pre, model)
    out_m, out_b = np.full(pre.shape, np.nan), np.full(pre.shape, np.nan)
    for i, season in enumerate(seasons[1:], start=1):
        past = df["season"].isin(seasons[:i]).to_numpy()
        now = (df["season"] == season).to_numpy()
        if len(np.unique(y[past])) < pre.shape[1] or now.sum() == 0:
            continue
        out_m[now] = LogisticRegression(C=10, max_iter=2000).fit(x_market[past], y[past]).predict_proba(x_market[now])
        out_b[now] = LogisticRegression(C=10, max_iter=2000).fit(x_both[past], y[past]).predict_proba(x_both[now])
    ok = ~np.isnan(out_b).any(axis=1)
    return _logloss(out_m[ok], y[ok]), _logloss(out_b[ok], y[ok]), int(ok.sum())


def closing_line_value(df: pd.DataFrame, market: str, edge: float) -> dict:
    """Bets where model_p × pre_odds > 1 + edge. EV under the closing fair probability."""
    spec = MARKETS[market]
    model, _, close_fair = _probs(df, market)
    odds = df[spec["pre"]].to_numpy(float)
    y = _outcome(df, market)
    ev_model = model * odds - 1
    take = ev_model > edge
    rows, cols = np.nonzero(take)
    if len(rows) == 0:
        return {"bets": 0}
    ev_close = close_fair[rows, cols] * odds[rows, cols] - 1
    won = (y[rows] == cols)
    profit = np.where(won, odds[rows, cols] - 1, -1.0)
    se = ev_close.std(ddof=1) / np.sqrt(len(ev_close)) if len(ev_close) > 1 else np.nan
    return {"bets": int(len(rows)), "ev_close": float(ev_close.mean()), "t": float(ev_close.mean() / se),
            "roi": float(profit.mean()), "beat_close": float((ev_close > 0).mean())}


# ─── asian handicap ────────────────────────────────────────────────────────────

def ah_expected_value(m: np.ndarray, line: float, odds: float, side: str = "home") -> float:
    """Expected profit of 1 unit on the home (or away) side of an Asian handicap `line`
    (quoted for the home team), from a score matrix. Quarter lines (±0.25, ±0.75) are
    half the stake on each neighbouring line; a whole-number line can push (stake back)."""
    i, j = np.indices(m.shape)
    diff = (i - j) if side == "home" else (j - i)
    line = line if side == "home" else -line
    halves = [line] if (line * 4) % 2 == 0 else [line - 0.25, line + 0.25]
    ev = 0.0
    for part in halves:
        margin = diff + part
        ev += (m[margin > 0].sum() * (odds - 1) - m[margin < 0].sum()) / len(halves)
    return float(ev)


def ah_closing_line_value(df: pd.DataFrame, edge: float) -> dict:
    """Bets on either side when the model's EV at the pre-match price beats `edge`. Only
    matches whose closing line equals the pre-match line (otherwise prices aren't
    comparable). EV under the closing line: fair 2-way probability × pre odds − 1."""
    from ratings import score_matrix

    data = df.dropna(subset=["ah_line", "ah_avg_h", "ah_avg_a", "ah_close_line", "ah_close_h", "ah_close_a"])
    data = data[(data["ah_line"] == data["ah_close_line"]) & (data[["ah_avg_h", "ah_avg_a", "ah_close_h", "ah_close_a"]] > 1).all(axis=1)]
    evs, profits = [], []
    for r in data.itertuples(index=False):
        m = score_matrix(r.lambda_home, r.lambda_away, getattr(r, "rho", 0.0) or 0.0)
        fair = implied_probs(np.array([[r.ah_close_h, r.ah_close_a]]))[0]
        for k, (side, odds) in enumerate((("home", r.ah_avg_h), ("away", r.ah_avg_a))):
            if ah_expected_value(m, r.ah_line, odds, side) > edge:
                evs.append(fair[k] * odds - 1)
                # Settle the bet on the real score (quarter lines: two halves).
                diff = (r.fthg - r.ftag) if side == "home" else (r.ftag - r.fthg)
                line = r.ah_line if side == "home" else -r.ah_line
                halves = [line] if (line * 4) % 2 == 0 else [line - 0.25, line + 0.25]
                profits.append(sum(((odds - 1) if diff + h > 0 else 0.0 if diff + h == 0 else -1.0)
                                   for h in halves) / len(halves))
    if not evs:
        return {"bets": 0, "n": len(data)}
    evs = np.array(evs)
    return {"bets": len(evs), "n": len(data), "ev_close": float(evs.mean()),
            "t": float(evs.mean() / (evs.std(ddof=1) / np.sqrt(len(evs)))),
            "roi": float(np.mean(profits)), "beat_close": float((evs > 0).mean())}


def analyse(pred: pd.DataFrame, edge: float = 0.03) -> pd.DataFrame:
    rows = []
    if "ah_line" in pred:
        for league, df in [("TODAS", pred), *pred.groupby("league")]:
            clv = ah_closing_line_value(df, edge)
            if clv.get("n", 0) >= 500:
                rows.append({"mercado": "ah", "liga": league, "n": clv["n"], "apuestas": clv["bets"],
                             "ev_vs_cierre": clv.get("ev_close"), "t": clv.get("t"), "roi": clv.get("roi"),
                             "baten_cierre": clv.get("beat_close")})
    for market, spec in MARKETS.items():
        need = spec["model"] + spec["pre"] + spec["close"]
        data = pred.dropna(subset=need)
        data = data[(data[spec["pre"] + spec["close"]] > 1).all(axis=1)]
        for league, df in [("TODAS", data), *data.groupby("league")]:
            df = df.reset_index(drop=True)
            if len(df) < 500:
                continue
            model, pre, close = _probs(df, market)
            y = _outcome(df, market)
            ll_mkt_cal, ll_both, n_info = information_gain(df, market)
            clv = closing_line_value(df, market, edge)
            rows.append({
                "mercado": market, "liga": league, "n": len(df),
                "ll_modelo": _logloss(model, y), "ll_previo": _logloss(pre, y), "ll_cierre": _logloss(close, y),
                "ganancia_info": ll_mkt_cal - ll_both,      # > 0: the model adds information
                "apuestas": clv.get("bets", 0), "ev_vs_cierre": clv.get("ev_close"), "t": clv.get("t"),
                "roi": clv.get("roi"), "baten_cierre": clv.get("beat_close"),
            })
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("predictions")
    parser.add_argument("--edge", type=float, default=0.03)
    args = parser.parse_args()
    pred = pd.read_csv(args.predictions, parse_dates=["date"], dtype={"season": str})
    table = analyse(pred, args.edge)
    pd.set_option("display.width", 200)
    print(table.round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
