import numpy as np
import pandas as pd
import pytest

import market
from backtest import walk_forward
from odds_live import remove_margin as remove_margin_brentq
from ratings import DixonColes, outcome_probs, score_matrix
from test_ratings import synthetic_league


def fair_odds(lh: float, la: float) -> dict:
    """Odds with no margin for a match the market prices at (lh, la)."""
    m = score_matrix(lh, la, market.RHO)
    ph, pd_, pa = outcome_probs(m)
    i, j = np.indices(m.shape)
    po = m[i + j > 2.5].sum()
    return {"close_h": 1 / ph, "close_d": 1 / pd_, "close_a": 1 / pa, "ou_close_o": 1 / po, "ou_close_u": 1 / (1 - po)}


def test_prices_give_back_the_expected_goals():
    true = [(1.6, 0.9), (0.7, 2.4), (2.9, 0.5), (1.2, 1.2)]
    lh, la = market.implied_lambdas(pd.DataFrame([fair_odds(*t) for t in true]))
    np.testing.assert_allclose(np.column_stack([lh, la]), true, rtol=0.01)


def test_1x2_alone_is_enough():
    true = [(1.6, 0.9), (0.7, 2.4)]
    df = pd.DataFrame([fair_odds(*t) for t in true]).drop(columns=["ou_close_o", "ou_close_u"])
    lh, la = market.implied_lambdas(df)
    np.testing.assert_allclose(np.column_stack([lh, la]), true, rtol=0.03)


def test_sharpest_price_wins_and_missing_stays_nan():
    df = pd.DataFrame([{**fair_odds(2.0, 0.8), "avg_h": 3.0, "avg_d": 3.3, "avg_a": 2.4},
                       {"avg_h": np.nan, "avg_d": 3.3, "avg_a": 2.4}])
    lh, la = market.implied_lambdas(df)
    assert lh[0] == pytest.approx(2.0, rel=0.01)       # closing price, not the average
    assert np.isnan(lh[1]) and np.isnan(la[1])


def test_power_method_matches_odds_live():
    odds = np.array([[1.8, 3.6, 4.9], [1.25, 6.5, 12.0], [2.9, 3.2, 2.6], [1.91, 1.95, np.nan]])
    p = market.remove_margin(odds)
    for row, expected in zip(p[:3], odds[:3]):
        np.testing.assert_allclose(row, remove_margin_brentq(expected), atol=1e-10)
    assert np.isnan(p[3]).all()


def test_market_weight_pulls_ratings_towards_the_prices():
    df, attack, *_ = synthetic_league(rounds=2)
    best = max(attack, key=attack.get)
    # A market that rates the best team as average at home: its rating must drop.
    lh, la = np.full(len(df), 1.4), np.full(len(df), 1.1)
    df = df.assign(mkt_home=lh, mkt_away=la)
    plain = DixonColes().fit(df)
    priced = DixonColes(market_weight=0.9).fit(df)
    i = plain.teams.index(best)
    assert priced.attack[i] < plain.attack[i]
    # Weight 0 ignores the columns entirely.
    np.testing.assert_allclose(DixonColes(market_weight=0).fit(df).attack, plain.attack)


def test_a_match_price_never_reaches_its_own_prediction():
    df, *_ = synthetic_league(rounds=3)
    df = df.assign(league="X", season=np.where(df.index < len(df) * 2 // 3, "2223", "2324"),
                   mkt_home=1.4, mkt_away=1.1)
    a = walk_forward(df, "X", ["2324"], xg_weight=0, market_weight=0.8)
    # Rewrite the price of the LAST match: no prediction may change, not even its own.
    tampered = df.copy()
    tampered.loc[tampered.index[-1], ["mkt_home", "mkt_away"]] = [4.5, 0.2]
    b = walk_forward(tampered, "X", ["2324"], xg_weight=0, market_weight=0.8)
    np.testing.assert_allclose(a["p_home"], b["p_home"])


def test_market_decay_defaults_to_the_model_decay():
    df, *_ = synthetic_league(rounds=2)
    rng = np.random.default_rng(1)
    df = df.assign(mkt_home=rng.uniform(0.8, 2.2, len(df)), mkt_away=rng.uniform(0.6, 1.8, len(df)))
    a = DixonColes(market_weight=0.5).fit(df)
    b = DixonColes(market_weight=0.5, market_xi=a.xi).fit(df)
    np.testing.assert_allclose(a.attack, b.attack)
    # A faster decay for prices changes the fit (the old prices count less).
    c = DixonColes(market_weight=0.5, market_xi=0.05).fit(df)
    assert np.abs(c.attack - a.attack).max() > 1e-3
