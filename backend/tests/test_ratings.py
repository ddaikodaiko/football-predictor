import numpy as np
import pandas as pd
import pytest

from ratings import DixonColes, markets, outcome_probs, score_matrix


def synthetic_league(n_teams=12, rounds=6, seed=0, rho=-0.08):
    """Double round-robin repeated `rounds` times, goals drawn from a known model."""
    rng = np.random.default_rng(seed)
    teams = [f"T{i:02d}" for i in range(n_teams)]
    attack = rng.normal(0, 0.3, n_teams)
    defense = rng.normal(0, 0.3, n_teams)
    attack -= attack.mean(); defense -= defense.mean()
    mu, home = 0.1, 0.3
    rows, day = [], pd.Timestamp("2023-08-01")
    for _ in range(rounds):
        for h in range(n_teams):
            for a in range(n_teams):
                if h == a:
                    continue
                lh = np.exp(mu + home + attack[h] + defense[a])
                la = np.exp(mu + attack[a] + defense[h])
                m = score_matrix(lh, la, rho)
                k = rng.choice(m.size, p=m.ravel())
                rows.append((day, teams[h], teams[a], *np.unravel_index(k, m.shape)))
                day += pd.Timedelta(hours=6)
    df = pd.DataFrame(rows, columns=["date", "home", "away", "fthg", "ftag"])
    return df, dict(zip(teams, attack)), dict(zip(teams, defense)), home


def test_score_matrix_is_a_distribution_and_tau_moves_draws():
    m0 = score_matrix(1.4, 1.1, 0.0)
    m1 = score_matrix(1.4, 1.1, -0.1)
    assert m0.sum() == pytest.approx(1) and m1.sum() == pytest.approx(1)
    assert m1[0, 0] > m0[0, 0] and m1[1, 1] > m0[1, 1]      # ρ < 0: more low draws
    assert sum(outcome_probs(m1)) == pytest.approx(1)
    mk = markets(m1)
    assert 0 < mk["over25"] < 1 and mk["top_scores"][0]["prob"] == pytest.approx(m1.max())


def test_fit_recovers_the_strengths_that_generated_the_league():
    df, attack, defense, home = synthetic_league(rounds=12)
    dc = DixonColes(xi=0.0, prior_sd=10.0, max_days=10_000).fit(df)
    fitted = dc.ratings().set_index("team")
    # Ratings are identified up to a constant shared with μ: compare centred values.
    true_att = pd.Series(attack); fit_att = fitted["attack"] - fitted["attack"].mean()
    true_def = pd.Series(defense); fit_def = fitted["defense"] - fitted["defense"].mean()
    assert np.corrcoef(true_att, fit_att[true_att.index])[0, 1] > 0.85
    assert np.corrcoef(true_def, fit_def[true_def.index])[0, 1] > 0.85
    assert dc.home_adv == pytest.approx(home, abs=0.1)


def test_only_past_matches_are_used():
    df, *_ = synthetic_league(rounds=2)
    cut = df["date"].iloc[len(df) // 2]
    a = DixonColes().fit(df, as_of=cut)
    b = DixonColes().fit(df[df["date"] < cut], as_of=cut)
    assert a.n_matches == b.n_matches
    np.testing.assert_allclose(a.attack, b.attack)


def test_xg_target_is_used_when_asked():
    df, *_ = synthetic_league(rounds=2)
    df["xg_home"], df["xg_away"] = 3.0, 0.2       # absurd xG: must move the fit if used
    goals = DixonColes(max_days=10_000).fit(df)
    xg = DixonColes(max_days=10_000, xg_weight=1.0).fit(df)
    assert xg.lambdas("T00", "T01")[0] > goals.lambdas("T00", "T01")[0] + 1


def test_unknown_team_gets_average_ratings():
    df, *_ = synthetic_league(rounds=1)
    dc = DixonColes(max_days=10_000).fit(df)
    lh, la = dc.lambdas("Promoted FC", "Also New")
    assert lh == pytest.approx(np.exp(dc.mu + dc.home_adv)) and la == pytest.approx(np.exp(dc.mu))
