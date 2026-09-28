"""
Dixon-Coles team ratings, fitted by maximum likelihood.

    log λ_home = μ + home_adv + attack[home] + defense[away]
    log λ_away = μ            + attack[away] + defense[home]

`defense` is defensive weakness: higher means concedes more. Goals are Poisson with the
Dixon-Coles τ correction for 0-0, 1-0, 0-1 and 1-1 (Dixon & Coles, 1997).

What makes this better than averaging goals per team:
  - Opponent strength is accounted for: scoring 3 against the leader counts more.
  - Time decay: each match weighs exp(-ξ·days_ago), so the fit follows form without
    throwing old data away (ξ = 0.0019/day ≈ one-year half-life, the paper's value).
  - xG: the target can mix goals and xG (`xg_weight`). xG is far less noisy than goals
    for estimating how good a team is; the Poisson likelihood accepts non-integer targets.
  - A ridge prior pulls attack/defense towards the league average, so a promoted team
    with five matches doesn't get an absurd rating.
  - Several divisions can be fitted together (`primary` + a `league` column): each
    division gets its own goal rate and home advantage, and the teams that go up and
    down put everyone on one scale. A promoted team then arrives with a real rating
    instead of "average".
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

MAX_GOALS = 10


@dataclass
class DixonColes:
    xi: float = 0.003            # time decay per day (best of 0.001-0.005 in backtest.py)
    xg_weight: float = 0.0       # 0 = goals only, 1 = xG only
    prior_sd: float = 1.0        # ridge prior on attack/defense (log scale; best of 0.5-2)
    max_days: int = 3 * 365      # ignore matches older than this

    teams: list[str] = field(default_factory=list)
    mu: float = 0.0
    home_adv: float = 0.25
    attack: np.ndarray = field(default_factory=lambda: np.zeros(0))
    defense: np.ndarray = field(default_factory=lambda: np.zeros(0))
    rho: float = -0.05
    as_of: pd.Timestamp | None = None
    n_matches: int = 0
    division_offsets: dict[str, tuple[float, float]] = field(default_factory=dict)

    # ── fitting ────────────────────────────────────────────────────────────────

    def fit(self, matches: pd.DataFrame, as_of: pd.Timestamp | None = None,
            primary: str | None = None) -> "DixonColes":
        """`matches`: date, home, away, fthg, ftag and optionally xg_home/xg_away.
        Only matches strictly before `as_of` are used (default: all).

        With `primary` and a `league` column holding more than one division, `mu` and
        `home_adv` are those of `primary`, and the other divisions get offsets."""
        df = matches.dropna(subset=["fthg", "ftag"])
        if "disputed" in df:
            df = df[df["disputed"].fillna(0) == 0]      # results the sources disagree on
        as_of = pd.Timestamp(as_of) if as_of is not None else df["date"].max() + pd.Timedelta(days=1)
        days = (as_of - df["date"]).dt.days.to_numpy()
        keep = (days > 0) & (days <= self.max_days)
        df, days = df[keep], days[keep]
        if len(df) < 20:
            raise ValueError(f"only {len(df)} matches before {as_of.date()}; not enough to fit")

        self.as_of, self.n_matches = as_of, len(df)
        self.teams = sorted(set(df["home"]) | set(df["away"]))
        index = {t: i for i, t in enumerate(self.teams)}
        hi = df["home"].map(index).to_numpy()
        ai = df["away"].map(index).to_numpy()
        gh = df["fthg"].to_numpy(float)
        ga = df["ftag"].to_numpy(float)
        th, ta = gh, ga
        if self.xg_weight > 0 and "xg_home" in df:
            xh = pd.to_numeric(df["xg_home"], errors="coerce").to_numpy(float)
            xa = pd.to_numeric(df["xg_away"], errors="coerce").to_numpy(float)
            has = ~np.isnan(xh) & ~np.isnan(xa)
            w = self.xg_weight
            th = np.where(has, w * xh + (1 - w) * gh, gh)
            ta = np.where(has, w * xa + (1 - w) * ga, ga)
        weight = np.exp(-self.xi * days)
        n = len(self.teams)
        inv_var = 1.0 / self.prior_sd ** 2

        # Division offsets: group 0 is the primary division (offset fixed at 0).
        others: list[str] = []
        gi = np.zeros(len(df), dtype=int)
        if primary is not None and "league" in df and df["league"].nunique() > 1:
            others = sorted(set(df["league"]) - {primary})
            gi = df["league"].map({primary: 0, **{g: k + 1 for k, g in enumerate(others)}}).to_numpy()
        n_off = len(others)
        o = 2 + 2 * n                                   # offsets start here: mu_off, then home_off

        def nll(theta: np.ndarray) -> tuple[float, np.ndarray]:
            mu, home, att, dfn = theta[0], theta[1], theta[2:2 + n], theta[2 + n:o]
            mu_g = np.concatenate([[0.0], theta[o:o + n_off]])[gi]
            home_g = np.concatenate([[0.0], theta[o + n_off:]])[gi]
            lh = np.exp(mu + mu_g + home + home_g + att[hi] + dfn[ai])
            la = np.exp(mu + mu_g + att[ai] + dfn[hi])
            rh, ra = weight * (th - lh), weight * (ta - la)       # d ll / d log λ
            ll = np.sum(weight * (th * np.log(lh) - lh + ta * np.log(la) - la))
            penalty = 0.5 * inv_var * (att @ att + dfn @ dfn)
            grad = np.empty_like(theta)
            grad[0] = rh.sum() + ra.sum()
            grad[1] = rh.sum()
            grad[2:2 + n] = np.bincount(hi, rh, n) + np.bincount(ai, ra, n) - inv_var * att
            grad[2 + n:o] = np.bincount(ai, rh, n) + np.bincount(hi, ra, n) - inv_var * dfn
            if n_off:
                grad[o:o + n_off] = np.bincount(gi, rh + ra, n_off + 1)[1:]
                grad[o + n_off:] = np.bincount(gi, rh, n_off + 1)[1:]
            return -(ll - penalty), -grad

        theta0 = np.zeros(o + 2 * n_off)
        theta0[0] = np.log(max((th.mean() + ta.mean()) / 2, 0.1))
        theta0[1] = 0.25
        result = minimize(nll, theta0, jac=True, method="L-BFGS-B")
        self.mu, self.home_adv = float(result.x[0]), float(result.x[1])
        self.attack, self.defense = result.x[2:2 + n], result.x[2 + n:o]
        self.division_offsets = {g: (float(result.x[o + k]), float(result.x[o + n_off + k]))
                                 for k, g in enumerate(others)}

        # ρ only makes sense on real scorelines, so it's fitted on goals, not on xG.
        mu_g = np.concatenate([[0.0], result.x[o:o + n_off]])[gi]
        home_g = np.concatenate([[0.0], result.x[o + n_off:]])[gi]
        lh = np.exp(self.mu + mu_g + self.home_adv + home_g + self.attack[hi] + self.defense[ai])
        la = np.exp(self.mu + mu_g + self.attack[ai] + self.defense[hi])

        def rho_nll(rho: float) -> float:
            return -np.sum(weight * np.log(np.maximum(_tau(gh, ga, lh, la, rho), 1e-10)))

        self.rho = float(minimize_scalar(rho_nll, bounds=(-0.25, 0.25), method="bounded").x)
        return self

    # ── prediction ─────────────────────────────────────────────────────────────

    def knows(self, team: str) -> bool:
        return team in self.teams

    def lambdas(self, home: str, away: str, neutral: bool = False) -> tuple[float, float]:
        """Expected goals. A team the model hasn't seen gets league-average ratings."""
        index = {t: i for i, t in enumerate(self.teams)}
        att = lambda t: self.attack[index[t]] if t in index else 0.0
        dfn = lambda t: self.defense[index[t]] if t in index else 0.0
        home_adv = 0.0 if neutral else self.home_adv
        lh = np.exp(self.mu + home_adv + att(home) + dfn(away))
        la = np.exp(self.mu + att(away) + dfn(home))
        return float(lh), float(la)

    def score_matrix(self, home: str, away: str, neutral: bool = False) -> np.ndarray:
        """P(home scores i, away scores j) for i, j in 0..MAX_GOALS."""
        return score_matrix(*self.lambdas(home, away, neutral), self.rho)

    def ratings(self) -> pd.DataFrame:
        """One row per team: attack, defense and a net rating (goal difference per match
        against an average team on neutral ground)."""
        base = np.exp(self.mu)
        gf = base * np.exp(self.attack)
        ga = base * np.exp(self.defense)
        return pd.DataFrame({
            "team": self.teams, "attack": self.attack, "defense": self.defense,
            "xgf": gf, "xga": ga, "net": gf - ga,
        }).sort_values("net", ascending=False, ignore_index=True)


# ─── scoreline maths ───────────────────────────────────────────────────────────

def _tau(x, y, lh, la, rho):
    x, y = np.asarray(x), np.asarray(y)
    tau = np.ones(np.broadcast(x, y, lh, la).shape)
    tau = np.where((x == 0) & (y == 0), 1 - lh * la * rho, tau)
    tau = np.where((x == 0) & (y == 1), 1 + lh * rho, tau)
    tau = np.where((x == 1) & (y == 0), 1 + la * rho, tau)
    tau = np.where((x == 1) & (y == 1), 1 - rho, tau)
    return tau


def score_matrix(lh: float, la: float, rho: float = 0.0, max_goals: int = MAX_GOALS) -> np.ndarray:
    goals = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(goals, lh), poisson.pmf(goals, la))
    m[:2, :2] *= _tau(goals[:2, None], goals[None, :2], lh, la, rho)
    return m / m.sum()


def outcome_probs(m: np.ndarray) -> tuple[float, float, float]:
    """(home win, draw, away win) from a score matrix."""
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def markets(m: np.ndarray) -> dict:
    """Common betting markets from a score matrix."""
    i, j = np.indices(m.shape)
    total = i + j
    p_home, p_draw, p_away = outcome_probs(m)
    top = np.dstack(np.unravel_index(np.argsort(-m, axis=None)[:6], m.shape))[0]
    return {
        "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
        "over15": float(m[total > 1.5].sum()), "over25": float(m[total > 2.5].sum()),
        "over35": float(m[total > 3.5].sum()),
        "btts": float(m[(i > 0) & (j > 0)].sum()),
        "cs_home": float(m[:, 0].sum()), "cs_away": float(m[0, :].sum()),
        "top_scores": [{"score": f"{a}-{b}", "prob": float(m[a, b])} for a, b in top],
    }
