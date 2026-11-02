import numpy as np
import pandas as pd
import pytest
from scipy.stats import nbinom

import props
from test_ratings import synthetic_league


def test_nb_pmf_matches_scipy():
    mu, alpha = 5.3, 0.08
    r = 1 / alpha
    expected = nbinom.pmf(np.arange(40), r, r / (r + mu))
    assert props.nb_pmf(mu, alpha) == pytest.approx(expected, abs=1e-12)
    assert props.nb_logpmf(np.arange(40), np.full(40, mu), alpha) == pytest.approx(np.log(expected))


def test_markets_halves_add_up_and_lines_are_monotone():
    params = {s: {"home": 6.0, "away": 4.0, "alpha_home": 0.08, "alpha_away": 0.09} for s in props.STATS}
    mk = props.markets(params, first_half=0.45)
    c = mk["corners"]
    assert c["first"]["home"] + c["second"]["home"] == pytest.approx(c["match"]["home"])
    over = list(c["match"]["over_total"].values())
    assert all(a >= b for a, b in zip(over, over[1:]))
    assert c["first"]["over_home"]["1.5"] < c["second"]["over_home"]["1.5"]


def test_count_ratings_never_see_the_future():
    df, *_ = synthetic_league(rounds=3)
    rng = np.random.default_rng(0)
    df = df.assign(league="X", season=np.where(df.index < len(df) * 2 // 3, "2223", "2324"),
                   hc=rng.poisson(5, len(df)), ac=rng.poisson(4, len(df)),
                   hst=rng.poisson(4, len(df)), ast=rng.poisson(3, len(df)))
    a = props.walk_forward(df, "X", ["2324"])
    tampered = df.copy()
    tampered.loc[tampered.index[-1], ["hc", "hst"]] = [30, 20]
    b = props.walk_forward(tampered, "X", ["2324"])
    before = a["date"] < df["date"].iloc[-1].normalize() - pd.Timedelta(days=7)
    assert before.sum() > 50
    cols = [c for c in a.columns if "rating" in c]
    pd.testing.assert_frame_equal(a.loc[before, cols], b.loc[before, cols])


def test_predict_uses_both_goals_and_ratings():
    w = {f"{s}_{side}": {"coef": [1.0, 0.2, -0.1, 0.5], "alpha": 0.08}
         for s in props.STATS for side in ("home", "away")}
    ratings = {s: (5.0, 4.0) for s in props.STATS}
    strong = props.predict(w, (2.5, 0.8), ratings)["corners"]["home"]
    weak = props.predict(w, (0.8, 2.5), ratings)["corners"]["home"]
    assert strong > weak
    assert props.predict(w, (1.5, 1.5), {s: (7.0, 4.0) for s in props.STATS})["corners"]["home"] > \
        props.predict(w, (1.5, 1.5), ratings)["corners"]["home"]
