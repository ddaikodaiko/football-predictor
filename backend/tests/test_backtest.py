import numpy as np
import pandas as pd
import pytest

from backtest import implied_probs, market_probs, scores, walk_forward
from test_ratings import synthetic_league


def test_implied_probs_remove_the_margin():
    p = implied_probs(np.array([[2.0, 3.4, 4.0]]))
    assert p.sum() == pytest.approx(1)
    assert p[0, 0] < 1 / 2.0                   # margin removed from every outcome


def test_market_prefers_closing_line():
    df = pd.DataFrame({"b365_h": [2.0], "b365_d": [3.0], "b365_a": [4.0],
                       "close_h": [1.5], "close_d": [4.0], "close_a": [7.0]})
    probs, source = market_probs(df)
    assert source[0] == "cierre" and probs[0, 0] > 0.6


def test_scores_perfect_and_uniform():
    y = np.array([0, 1, 2])
    perfect = scores(np.eye(3), y)
    uniform = scores(np.full((3, 3), 1 / 3), y)
    assert perfect["log_loss"] == pytest.approx(0, abs=1e-9) and perfect["rps"] == 0
    assert uniform["log_loss"] == pytest.approx(np.log(3))


def test_walk_forward_never_sees_the_future():
    df, *_ = synthetic_league(rounds=3)
    df = df.assign(league="X", season=np.where(df.index < len(df) * 2 // 3, "2223", "2324"))
    a = walk_forward(df, "X", ["2324"], xg_weight=0)
    # Rewrite the result of the LAST match: no earlier prediction may change.
    tampered = df.copy()
    tampered.loc[tampered.index[-1], ["fthg", "ftag"]] = [9, 0]
    b = walk_forward(tampered, "X", ["2324"], xg_weight=0)
    last_day = df["date"].iloc[-1].normalize()
    before = a["date"] < last_day - pd.Timedelta(days=7)
    assert before.sum() > 50
    np.testing.assert_allclose(a.loc[before, "p_home"], b.loc[before, "p_home"])
