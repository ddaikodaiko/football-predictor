import numpy as np
import pandas as pd

from edge import closing_line_value, information_gain


def synthetic_market(model_knows: bool, n: int = 6000, seed: int = 0) -> pd.DataFrame:
    """Over/under 2.5 only. The pre-match price is unbiased; news then moves the true p
    (which the close sees exactly). The model either knows that news or is noise.
    Drawing p first and adding noise to get the pre-match price would make the pre price
    biased (regression to the mean) and hand free CLV to anyone betting long odds."""
    rng = np.random.default_rng(seed)
    pre = rng.uniform(0.35, 0.65, n)
    p = np.clip(pre + rng.normal(0, 0.08, n), 0.05, 0.95)
    over = rng.random(n) < p
    model = p if model_knows else rng.uniform(0.35, 0.65, n)
    margin = 1.05
    return pd.DataFrame({
        "season": np.repeat(["a", "b", "c"], n // 3),
        "fthg": np.where(over, 2, 0), "ftag": np.where(over, 1, 0),
        "p_over25": model,
        "ou_avg_o": 1 / (pre * margin), "ou_avg_u": 1 / ((1 - pre) * margin),
        "ou_close_o": 1 / (p * margin), "ou_close_u": 1 / ((1 - p) * margin),
    })


def test_an_informed_model_adds_information_and_beats_the_close():
    df = synthetic_market(model_knows=True)
    market_only, both, n = information_gain(df, "ou25")
    assert both < market_only - 0.005 and n == 4000
    clv = closing_line_value(df, "ou25", edge=0.03)
    assert clv["bets"] > 500 and clv["ev_close"] > 0.03 and clv["t"] > 5


def test_a_noise_model_adds_nothing():
    df = synthetic_market(model_knows=False)
    market_only, both, _ = information_gain(df, "ou25")
    assert both >= market_only - 0.001
    clv = closing_line_value(df, "ou25", edge=0.03)
    assert clv["ev_close"] < 0


def test_asian_handicap_expected_value():
    from edge import ah_expected_value
    from ratings import score_matrix

    m = score_matrix(1.5, 1.0)
    # Home -0.5 is "home wins"; at fair odds the EV is zero.
    p_home = float(np.tril(m, -1).sum())
    assert abs(ah_expected_value(m, -0.5, 1 / p_home)) < 1e-9
    # Line 0 (draw no bet): a draw returns the stake, so EV = p_win*(o-1) - p_lose.
    p_away = float(np.triu(m, 1).sum())
    assert abs(ah_expected_value(m, 0.0, 2.0) - (p_home - p_away)) < 1e-9
    # -0.25 is half on 0 and half on -0.5.
    ev = ah_expected_value(m, -0.25, 1.9)
    assert abs(ev - 0.5 * (ah_expected_value(m, 0.0, 1.9) + ah_expected_value(m, -0.5, 1.9))) < 1e-9
    # The away side of +0.5 for home is away -0.5.
    assert abs(ah_expected_value(m, 0.5, 3.0, "away") - (p_away * 2.0 - (1 - p_away))) < 1e-9
