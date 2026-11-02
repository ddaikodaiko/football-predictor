"""
Team strengths as a state-space model, updated match by match with a Kalman filter.

The Dixon-Coles in ratings.py refits a weighted likelihood every time: each past price
weighs exp(-ξ·days), the same for every team. A club with 300 priced matches and a side
promoted last week decay alike, and nothing knows that squads change in the summer.
Here the strengths are a random walk instead, and the filter carries their uncertainty:

    log λ_home = μ_g + h_g + att[home] + def[away] + δ_home
    log λ_away = μ_g       + att[away] + def[home] + δ_away

    att, def   drift every day (attack and defence correlated) and jump at the start of
               each season (transfers); a team never seen starts below average
    μ_g, h_g   goal rate and home advantage of each division, drifting slowly
    δ          what belongs to one match only (rotation, a suspension, the weather)

What a played match says, each with its own noise:
    price   log λ the market priced (market.py) = log λ + δ + market error   (before)
    goals   Poisson(λ·e^δ), linearised around the price (extended Kalman)      (after)
    xG      xG ≈ λ·e^δ with less noise than goals                               (after)

The three share the match's δ, so they're one joint observation: if the price already
knew the striker was out, the goals that follow don't count that twice. Every number of
the noise model is learned by maximising how well the filter predicts the NEXT price
(the prediction-error decomposition of the likelihood) on seasons the backtest doesn't
score. The forecast of a match integrates over everything the filter doesn't know:
the strengths' uncertainty and the match's own δ.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit
from scipy.stats import poisson

import market
from ratings import MAX_GOALS, _tau

PARAMS_FILE = Path(__file__).resolve().parent.parent / "data" / "statespace.json"
MU0, HOME0 = np.log(1.35), 0.25                  # starting goal rate and home advantage


@dataclass
class Hyper:
    """Noise model. Standard deviations on the log λ scale; walks are per 30 days."""
    match_sd: float = 0.10       # δ: what's particular to one match
    match_corr: float = 0.0      # between home and away δ
    price_sd: float = 0.03       # market error on top of δ
    walk_att: float = 0.03
    walk_def: float = 0.03
    walk_corr: float = -0.3
    season_att: float = 0.07     # jump at each new season
    season_def: float = 0.07
    new_att: float = -0.15       # prior mean of a team seen for the first time
    new_def: float = 0.15
    new_sd: float = 0.20
    walk_level: float = 0.01     # μ and home advantage
    goals: float = 1.0           # weight of the Poisson information of the score (0 = ignore)
    xg_noise: float = 0.5        # variance of xG relative to a Poisson's (0 = ignore xG)

    # Optimiser coordinates: logs for scales, atanh for correlations, raw for means.
    _LOG = ("match_sd", "price_sd", "walk_att", "walk_def", "season_att", "season_def", "new_sd",
            "walk_level", "goals", "xg_noise")
    _CORR = ("match_corr", "walk_corr")

    def to_vector(self, names: list[str]) -> np.ndarray:
        return np.array([np.log(getattr(self, n)) if n in self._LOG else
                         np.arctanh(getattr(self, n)) if n in self._CORR else getattr(self, n) for n in names])

    def with_vector(self, names: list[str], v: np.ndarray) -> "Hyper":
        values = {n: float(np.exp(x)) if n in self._LOG else float(np.tanh(x)) if n in self._CORR else float(x)
                  for n, x in zip(names, v)}
        return Hyper(**{**asdict(self), **values})

    def array(self) -> np.ndarray:
        """In the order the kernel reads them."""
        return np.array([getattr(self, f.name) for f in fields(self)], float)

    @classmethod
    def load(cls, path: Path = PARAMS_FILE) -> "Hyper":
        if not path.exists():
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in json.loads(path.read_text())["hyper"].items() if k in known})


# ─── the filter ────────────────────────────────────────────────────────────────

def prepare(matches: pd.DataFrame) -> pd.DataFrame:
    """Columns the filter reads: market λ (market.py) and xG rescaled to goals with the
    previous year of the same league only (Understat's xG drifts: 1.03 goals per xG in
    2014/15, 0.90 in 2026/27)."""
    df = matches if "mkt_home" in matches else market.add_market_lambdas(matches)
    df = df.sort_values(["date", "league", "home"]).reset_index(drop=True)
    scale = pd.Series(np.nan, index=df.index)
    for _, g in df.groupby("league"):
        has = g["xg_home"].notna() & g["xg_away"].notna() & g["fthg"].notna()
        s = g.loc[has].set_index("date")
        if s.empty:
            continue
        goals = (s["fthg"] + s["ftag"]).rolling("365D", closed="left").sum()
        xg = (s["xg_home"] + s["xg_away"]).rolling("365D", closed="left").sum()
        n = (s["fthg"] * 0 + 1).rolling("365D", closed="left").sum()
        ratio = (goals / xg).where(n >= 100)
        scale.loc[g.index[has.to_numpy()]] = ratio.to_numpy()
    return df.assign(xg_scale=scale.to_numpy())


class StateSpace:
    """Kalman filter over one group of divisions (a first division and its second).
    Same prediction interface as ratings.DixonColes, so the engine and the simulators
    take either."""

    def __init__(self, hyper: Hyper | None = None, rho: float = market.RHO, nu: float = 0.0):
        self.hyper = hyper or Hyper()
        self.rho = rho
        self.nu = nu

    # ── running ────────────────────────────────────────────────────────────────

    def run(self, matches: pd.DataFrame, primary: str | None = None, cuts: np.ndarray | None = None,
            predict: np.ndarray | None = None, until: pd.Timestamp | None = None) -> "StateSpace":
        """Filter `matches` (see prepare()) in date order.

        Every match whose row is True in `predict` gets a forecast made with what the
        filter knew at the latest of `cuts` not after its date (default: the day before).
        That's how the backtest reproduces a weekly refit. `self.loglik` adds up the log
        density of each predicted price; it's what fit() maximises.

        Matches on or after `until` are not used (they can still be predicted)."""
        df = matches
        teams = sorted(set(df["home"]) | set(df["away"]))
        divisions = [primary] if primary is not None else []
        divisions += sorted(set(df["league"]) - set(divisions))
        K, G = len(teams), len(divisions)
        tix = {t: i for i, t in enumerate(teams)}
        goals = df[["fthg", "ftag"]].to_numpy(float, copy=True)
        if "disputed" in df:
            goals[df["disputed"].fillna(0).to_numpy() != 0] = np.nan
        xg = df[["xg_home", "xg_away"]].to_numpy(float) * df["xg_scale"].to_numpy(float)[:, None] \
            if "xg_scale" in df else np.full((len(df), 2), np.nan)
        dates = df["date"].to_numpy("datetime64[D]").astype(np.int64)
        stop = np.iinfo(np.int64).max if until is None else np.datetime64(pd.Timestamp(until).date(), "D").astype(np.int64)
        has_cuts = cuts is not None
        cut_days = np.sort(np.asarray(cuts, "datetime64[D]").astype(np.int64)) if has_cuts else np.zeros(0, np.int64)
        out = _filter(
            dates, pd.factorize(df["season"], sort=True)[0].astype(np.int64),
            df["home"].map(tix).to_numpy(np.int64), df["away"].map(tix).to_numpy(np.int64),
            df["league"].map({g: k for k, g in enumerate(divisions)}).to_numpy(np.int64),
            np.ascontiguousarray(np.log(df[["mkt_home", "mkt_away"]].to_numpy(float))),
            np.ascontiguousarray(goals), np.ascontiguousarray(xg),
            np.zeros(len(df), np.bool_) if predict is None else np.asarray(predict, np.bool_),
            has_cuts, cut_days, np.int64(stop), K, G, self.hyper.array(), float(self.nu))
        x, P, active, self.pred_mean, self.pred_cov, self.loglik, self.n_loglik, last_day = out

        self.teams, self.divisions, self.K = teams, divisions, K
        self.x, self.P, self.active = x, P, active
        self.primary = divisions[0]
        self.as_of = pd.Timestamp(np.datetime64(int(last_day), "D")) + pd.Timedelta(days=1)
        self.n_matches = int((dates < stop).sum())
        self._index = tix
        return self

    # ── prediction (DixonColes interface) ──────────────────────────────────────

    @property
    def mu(self) -> float:
        return float(self.x[2 * self.K])

    @property
    def home_adv(self) -> float:
        return float(self.x[2 * self.K + len(self.divisions)])

    @property
    def attack(self) -> np.ndarray:
        return self.x[:self.K]

    @property
    def defense(self) -> np.ndarray:
        return self.x[self.K:2 * self.K]

    def knows(self, team: str) -> bool:
        return team in self._index and bool(self.active[self._index[team]])

    def log_rates(self, home: str, away: str, neutral: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """Mean and covariance of (log λ home, log λ away), δ included. A team the filter
        hasn't seen gets the prior of a new team."""
        hp, K, G = self.hyper, self.K, len(self.divisions)
        x, P = self.x, self.P
        mean, var = [], []
        for t in (home, away):
            if self.knows(t):
                i = self._index[t]
                mean.append((x[i], x[K + i]))
                var.append(i)
            else:
                mean.append((hp.new_att, hp.new_def))
                var.append(None)
        idx_known = {t: v for t, v in zip((home, away), var)}
        mu_i, home_i = 2 * K, 2 * K + G
        h = 0.0 if neutral else 1.0
        m = np.array([x[mu_i] + h * x[home_i] + mean[0][0] + mean[1][1],
                      x[mu_i] + mean[1][0] + mean[0][1]])
        # Covariance from the state where it exists, the new-team prior where not.
        coef = {}                                         # state index -> (row h, row a)
        def add(k, ch, ca):
            a, b = coef.get(k, (0.0, 0.0))
            coef[k] = (a + ch, b + ca)
        add(mu_i, 1, 1)
        add(home_i, h, 0)
        extra = np.zeros((2, 2))
        for side, t in enumerate((home, away)):
            i = idx_known[t]
            att_row, def_row = (1, 0) if side == 0 else (0, 1)
            if i is None:
                extra += hp.new_sd ** 2 * np.array([[1, 0], [0, 1]])   # att and def of one team
            else:
                add(i, att_row, 1 - att_row)
                add(K + i, def_row, 1 - def_row)
        ks = np.array(list(coef))
        Hm = np.array([coef[k] for k in ks]).T
        C = Hm @ P[np.ix_(ks, ks)] @ Hm.T + extra
        C += hp.match_sd ** 2 * np.array([[1, hp.match_corr], [hp.match_corr, 1]])
        return m, C

    def score_matrix(self, home: str, away: str, neutral: bool = False) -> np.ndarray:
        return mixture_matrix(*self.log_rates(home, away, neutral), self.rho)

    def lambdas(self, home: str, away: str, neutral: bool = False) -> tuple[float, float]:
        """Expected goals: the mean of the forecast, not exp of the mean log rate."""
        m, C = self.log_rates(home, away, neutral)
        return float(np.exp(m[0] + C[0, 0] / 2)), float(np.exp(m[1] + C[1, 1] / 2))

    def ratings(self) -> pd.DataFrame:
        known = [t for t in self.teams if self.knows(t)]
        i = np.array([self._index[t] for t in known])
        base = np.exp(self.mu)
        att, dfn = self.attack[i], self.defense[i]
        sd = np.sqrt(self.P[i, i] + self.P[self.K + i, self.K + i] - 2 * self.P[i, self.K + i])
        return pd.DataFrame({
            "team": known, "attack": att, "defense": dfn, "xgf": base * np.exp(att), "xga": base * np.exp(dfn),
            "net": base * (np.exp(att) - np.exp(dfn)), "sd": sd,
        }).sort_values("net", ascending=False, ignore_index=True)


# ─── the kernel ────────────────────────────────────────────────────────────────

@njit(cache=True)
def _filter(dates, seasons, hi, ai, gi, y_price, goals, xg, predict, has_cuts, cut_days, stop, K, G, hp, nu):
    """The filter itself (see StateSpace.run). Each match's observations (two prices,
    two scores, two xG) all measure the same two numbers, its log rates plus δ, so they
    are first summarised into one 2-d observation by generalised least squares: the
    update is then rank 2 whatever the match brings. `nu` > 0 scores the predicted
    prices with a Student t of that many degrees of freedom instead of a normal."""
    (match_sd, match_corr, price_sd, walk_att, walk_def, walk_corr, season_att, season_def,
     new_att, new_def, new_sd, walk_level, goals_w, xg_noise) = (hp[0], hp[1], hp[2], hp[3], hp[4], hp[5],
                                                                 hp[6], hp[7], hp[8], hp[9], hp[10], hp[11],
                                                                 hp[12], hp[13])
    D = 2 * K + 2 * G
    n = len(dates)
    x = np.zeros(D)
    P = np.zeros((D, D))
    for g in range(G):
        x[2 * K + g] = MU0
        P[2 * K + g, 2 * K + g] = 0.04
        x[2 * K + G + g] = HOME0
        P[2 * K + G + g, 2 * K + G + g] = 0.01
    active = np.zeros(K, np.bool_)
    seen = np.zeros(K, np.int64)
    current = np.empty(K, np.int64)
    ph = np.empty(D)
    q_att, q_def = walk_att ** 2 / 30, walk_def ** 2 / 30
    q_ad = walk_corr * walk_att * walk_def / 30
    q_lvl = walk_level ** 2 / 30
    r_var, r_cov = match_sd ** 2, match_corr * match_sd ** 2
    p_var = price_sd ** 2
    pred_mean = np.full((n, 2), np.nan)
    pred_cov = np.full((n, 3), np.nan)
    loglik, n_ll = 0.0, 0
    xs, Ps = x.copy(), P.copy()
    sday, have_snap = 0, False
    last_day, last_season, cut_ptr = -(2 ** 62), -1, 0
    idx = np.empty(6, np.int64)
    H = np.array([[1., 1., 1., 0., 0., 1.], [1., 0., 0., 1., 1., 0.]])
    obs, side, var = np.empty(6), np.empty(6, np.int64), np.empty(6)
    PH = np.empty((D, 2))

    s = 0
    while s < n:
        day = dates[s]
        e = s
        while e < n and dates[e] == day:
            e += 1
        # Time: random walk since the last match day, a jump at each new season.
        if last_day > -(2 ** 62) and day > last_day:
            dt = float(day - last_day)
            for t in range(K):
                if active[t]:
                    P[t, t] += q_att * dt
                    P[K + t, K + t] += q_def * dt
                    P[t, K + t] += q_ad * dt
                    P[K + t, t] += q_ad * dt
            for g in range(2 * G):
                P[2 * K + g, 2 * K + g] += q_lvl * dt
        if seasons[s] > last_season:
            if last_season >= 0:
                for t in range(K):
                    if active[t]:
                        P[t, t] += season_att ** 2
                        P[K + t, K + t] += season_def ** 2
            last_season = seasons[s]
        last_day = day
        for r in range(s, e):
            for t in (hi[r], ai[r]):
                if not active[t]:
                    for k, mean in ((t, new_att), (K + t, new_def)):
                        P[k, :] = 0.0
                        P[:, k] = 0.0
                        P[k, k] = new_sd ** 2
                        x[k] = mean
                    active[t] = True

        # Forecasts, from the state at the latest cut.
        want = False
        for r in range(s, e):
            want = want or predict[r]
        if want:
            if has_cuts:
                fresh = False
                while cut_ptr < len(cut_days) and cut_days[cut_ptr] <= day:
                    cut_ptr += 1
                    fresh = True
                if fresh or not have_snap:
                    xs[:] = x
                    Ps[:, :] = P
                    sday, have_snap = day, True
                xu, Pu, gap = xs, Ps, float(day - sday)
            else:
                xu, Pu, gap = x, P, 0.0
            for r in range(s, e):
                if not predict[r]:
                    continue
                _indices(idx, K, G, gi[r], hi[r], ai[r])
                m0, m1 = _rates(xu, idx)
                c00, c11, c01 = _project(Pu, idx, H)
                c00 += gap * (q_att + q_def + 2 * q_lvl)
                c11 += gap * (q_att + q_def + q_lvl)
                c01 += gap * (2 * q_ad + q_lvl)
                pred_mean[r, 0], pred_mean[r, 1] = m0, m1
                pred_cov[r, 0], pred_cov[r, 1], pred_cov[r, 2] = c00, c11, c01
                if not (np.isnan(y_price[r, 0]) or np.isnan(y_price[r, 1])):
                    s00, s11, s01 = c00 + r_var + p_var, c11 + r_var + p_var, c01 + r_cov
                    d0, d1 = y_price[r, 0] - m0, y_price[r, 1] - m1
                    det = s00 * s11 - s01 * s01
                    q = (s11 * d0 * d0 - 2 * s01 * d0 * d1 + s00 * d1 * d1) / det
                    if nu > 0:
                        loglik += (math.lgamma((nu + 2) / 2) - math.lgamma(nu / 2) - np.log(nu * np.pi)
                                   - 0.5 * np.log(det) - (nu + 2) / 2 * np.log1p(q / nu))
                    else:
                        loglik += -0.5 * (q + np.log(det)) - np.log(2 * np.pi)
                    n_ll += 1
        if day >= stop:
            s = e
            continue

        # Measurement update, one match at a time.
        for r in range(s, e):
            seen[hi[r]], seen[ai[r]] = day, day
            _indices(idx, K, G, gi[r], hi[r], ai[r])
            m0, m1 = _rates(x, idx)
            k = 0
            priced = not (np.isnan(y_price[r, 0]) or np.isnan(y_price[r, 1]))
            lam0 = np.exp(y_price[r, 0]) if priced else np.exp(m0)
            lam1 = np.exp(y_price[r, 1]) if priced else np.exp(m1)
            if priced:
                for c in range(2):
                    obs[k], side[k], var[k] = y_price[r, c], c, p_var
                    k += 1
            # Scores and xG, linearised around the market's rate for this match.
            if goals_w > 0 and not (np.isnan(goals[r, 0]) or np.isnan(goals[r, 1])):
                for c, lam in ((0, lam0), (1, lam1)):
                    obs[k], side[k], var[k] = np.log(lam) + (goals[r, c] - lam) / lam, c, 1.0 / (goals_w * lam)
                    k += 1
            if xg_noise > 0 and not (np.isnan(xg[r, 0]) or np.isnan(xg[r, 1])):
                for c, lam in ((0, lam0), (1, lam1)):
                    obs[k], side[k], var[k] = np.log(lam) + (xg[r, c] - lam) / lam, c, xg_noise / lam
                    k += 1
            if k == 0:
                continue
            # GLS summary: two numbers with covariance Rt, everything shares δ.
            S = np.empty((k, k))
            for i in range(k):
                for j in range(k):
                    S[i, j] = (r_var if side[i] == side[j] else r_cov) + (var[i] if i == j else 0.0)
            Si = np.linalg.inv(S)
            I00 = I11 = I01 = v0 = v1 = 0.0
            for i in range(k):
                for j in range(k):
                    w = Si[i, j]
                    if side[i] == 0:
                        v0 += w * obs[j]
                        if side[j] == 0:
                            I00 += w
                        else:
                            I01 += w
                    else:
                        v1 += w * obs[j]
                        if side[j] == 1:
                            I11 += w
            det = I00 * I11 - I01 * I01
            rt00, rt11, rt01 = I11 / det, I00 / det, -I01 / det
            yt0, yt1 = rt00 * v0 + rt01 * v1, rt01 * v0 + rt11 * v1
            # Rank-2 Kalman update.
            for i in range(D):
                a0 = 0.0
                a1 = 0.0
                for j in range(6):
                    a0 += P[i, idx[j]] * H[0, j]
                    a1 += P[i, idx[j]] * H[1, j]
                PH[i, 0], PH[i, 1] = a0, a1
            s00 = s11 = s01 = 0.0
            for j in range(6):
                s00 += H[0, j] * PH[idx[j], 0]
                s11 += H[1, j] * PH[idx[j], 1]
                s01 += H[0, j] * PH[idx[j], 1]
            s00 += rt00
            s11 += rt11
            s01 += rt01
            det = s00 * s11 - s01 * s01
            i00, i11, i01 = s11 / det, s00 / det, -s01 / det
            d0, d1 = yt0 - m0, yt1 - m1
            for i in range(D):
                k0 = PH[i, 0] * i00 + PH[i, 1] * i01
                k1 = PH[i, 0] * i01 + PH[i, 1] * i11
                x[i] += k0 * d0 + k1 * d1
                for j in range(D):
                    P[i, j] -= k0 * PH[j, 0] + k1 * PH[j, 1]
        # Adding c to every attack and taking it from μ predicts exactly the same, so
        # nothing observes the level: pin the mean attack and defence of the teams
        # playing this year at zero (a pseudo-observation). Ratings are then on one
        # scale and a new team's prior is relative to the teams around it.
        n_cur = 0
        for t in range(K):
            if active[t] and day - seen[t] <= 365:
                current[n_cur] = t
                n_cur += 1
        for off in (0, K):
            for i in range(D):
                a0 = 0.0
                for j in range(n_cur):
                    a0 += P[i, off + current[j]]
                ph[i] = a0 / n_cur
            s00, d0 = 1e-4, 0.0
            for j in range(n_cur):
                s00 += ph[off + current[j]] / n_cur
                d0 -= x[off + current[j]] / n_cur
            for i in range(D):
                k0 = ph[i] / s00
                x[i] += k0 * d0
                for j in range(D):
                    P[i, j] -= k0 * ph[j]
        s = e
    return x, P, active, pred_mean, pred_cov, loglik, n_ll, last_day


@njit(cache=True)
def _indices(idx, K, G, g, h, a):
    idx[0], idx[1], idx[2], idx[3], idx[4], idx[5] = 2 * K + g, 2 * K + G + g, h, K + h, a, K + a


@njit(cache=True)
def _rates(x, idx):
    return x[idx[0]] + x[idx[1]] + x[idx[2]] + x[idx[5]], x[idx[0]] + x[idx[4]] + x[idx[3]]


@njit(cache=True)
def _project(P, idx, H):
    c00 = c11 = c01 = 0.0
    for i in range(6):
        for j in range(6):
            p = P[idx[i], idx[j]]
            c00 += H[0, i] * p * H[0, j]
            c11 += H[1, i] * p * H[1, j]
            c01 += H[0, i] * p * H[1, j]
    return c00, c11, c01


# ─── forecasts: integrate over what the filter doesn't know ──────────────────────

_GH_X, _GH_W = np.polynomial.hermite_e.hermegauss(7)     # nodes/weights for N(0, 1)
_GH_W = _GH_W / _GH_W.sum()


def mixture_matrices(mean: np.ndarray, cov: np.ndarray, rho: float = market.RHO) -> np.ndarray:
    """Score matrices (n, 11, 11) averaged over log λ ~ N(mean, cov), with 7×7
    Gauss-Hermite nodes. `mean` (n, 2), `cov` (n, 2, 2)."""
    mean, cov = np.atleast_2d(mean), np.asarray(cov).reshape(-1, 2, 2)
    L = np.linalg.cholesky(cov + 1e-12 * np.eye(2))
    zx, zy = np.meshgrid(_GH_X, _GH_X, indexing="ij")
    z = np.stack([zx.ravel(), zy.ravel()])                # (2, 49)
    w = np.outer(_GH_W, _GH_W).ravel()
    u = mean[:, :, None] + L @ z                          # (n, 2, 49)
    lam = np.exp(u)
    g = np.arange(MAX_GOALS + 1)
    ph = poisson.pmf(g[None, None, :], lam[:, 0, :, None])      # (n, 49, 11)
    pa = poisson.pmf(g[None, None, :], lam[:, 1, :, None])
    m = ph[:, :, :, None] * pa[:, :, None, :]                   # (n, 49, 11, 11)
    lh, la = lam[:, 0, :], lam[:, 1, :]
    m[:, :, 0, 0] *= 1 - lh * la * rho
    m[:, :, 0, 1] *= 1 + lh * rho
    m[:, :, 1, 0] *= 1 + la * rho
    m[:, :, 1, 1] *= 1 - rho
    m /= m.sum(axis=(2, 3), keepdims=True)
    return np.einsum("k,nkij->nij", w, m)


def mixture_matrix(mean: np.ndarray, cov: np.ndarray, rho: float = market.RHO) -> np.ndarray:
    return mixture_matrices(mean[None], cov[None], rho)[0]


def plugin_matrices(mean: np.ndarray, rho: float = market.RHO) -> np.ndarray:
    """Score matrices at exp(mean), no integration (for comparison)."""
    lam = np.exp(np.atleast_2d(mean))
    g = np.arange(MAX_GOALS + 1)
    m = poisson.pmf(g[None, :, None], lam[:, 0, None, None]) * poisson.pmf(g[None, None, :], lam[:, 1, None, None])
    m[:, :2, :2] *= _tau(g[:2, None], g[None, :2], lam[:, 0, None, None], lam[:, 1, None, None], rho)
    return m / m.sum(axis=(1, 2), keepdims=True)


def forecast_cov(model: StateSpace, with_match: bool = True) -> np.ndarray:
    """(n, 2, 2) covariance of each predicted match's log rates."""
    c = model.pred_cov
    cov = np.stack([np.stack([c[:, 0], c[:, 2]], -1), np.stack([c[:, 2], c[:, 1]], -1)], -2)
    if with_match:
        hp = model.hyper
        cov = cov + hp.match_sd ** 2 * np.array([[1, hp.match_corr], [hp.match_corr, 1]])
    return cov


# ─── backtest and fitting ──────────────────────────────────────────────────────

def group(matches: pd.DataFrame, league: str) -> pd.DataFrame:
    """A first division with its second (backtest.COMPANION), ready for the filter."""
    from backtest import COMPANION
    leagues = [league] + ([COMPANION[league]] if league in COMPANION else [])
    return prepare(matches[matches["league"].isin(leagues)])


def walk_forward(df: pd.DataFrame, league: str, seasons: list[str], hyper: Hyper,
                 refit_days: int | None = 7, integrate: bool = True) -> pd.DataFrame:
    """Same output as backtest.walk_forward. With `refit_days` the forecasts of a week use
    only what was known at its start, like the weekly refit of the Dixon-Coles; None
    updates daily (each match sees everything before its day)."""
    target = ((df["league"] == league) & df["season"].isin(seasons)).to_numpy()
    if not target.any():
        return pd.DataFrame()
    cuts = None
    if refit_days:
        dates = df.loc[target, "date"]
        cuts = pd.date_range(dates.min().normalize(), dates.max() + pd.Timedelta(days=1), freq=f"{refit_days}D")
    model = StateSpace(hyper).run(df, league, cuts=cuts, predict=target)
    mean = model.pred_mean[target]
    m = mixture_matrices(mean, forecast_cov(model)[target]) if integrate else plugin_matrices(mean)
    i, j = np.indices(m.shape[1:])
    rows = df.loc[target].reset_index(drop=True)
    out = pd.DataFrame({
        "p_over25": m[:, i + j > 2.5].sum(axis=1), "league": league, "season": rows["season"], "date": rows["date"],
        "home": rows["home"], "away": rows["away"], "fthg": rows["fthg"], "ftag": rows["ftag"],
        "p_home": np.tril(m, -1).sum(axis=(1, 2)), "p_draw": np.trace(m, axis1=1, axis2=2),
        "p_away": np.triu(m, 1).sum(axis=(1, 2)),
        "lambda_home": (m.sum(axis=2) * np.arange(m.shape[1])).sum(axis=1),
        "lambda_away": (m.sum(axis=1) * np.arange(m.shape[2])).sum(axis=1),
        "rho": model.rho, "known": True,
        "sd_home": np.sqrt(model.pred_cov[target, 0]), "sd_away": np.sqrt(model.pred_cov[target, 1]),
    })
    import store
    odds_cols = [c for c in store.MATCH_COLUMNS
                 if c.split("_")[0] in {"b365", "avg", "pin", "close", "ou", "ah"} and c in rows.columns]
    return pd.concat([out, rows[odds_cols]], axis=1)


_GROUPS: list[tuple[str, pd.DataFrame, np.ndarray]] = []


def _group_loglik(args) -> tuple[float, int]:
    k, hyper, nu = args
    league, df, mask = _GROUPS[k]
    m = StateSpace(hyper, nu=nu).run(df, league, predict=mask)
    return m.loglik, m.n_loglik


def fit(matches: pd.DataFrame, leagues: list[str], train_from: str, train_to: str,
        names: list[str] | None = None, start: Hyper | None = None, workers: int = 5,
        nu: float = 0.0, maxfev: int = 4000) -> tuple[Hyper, dict]:
    """Maximum likelihood of the next price, one step ahead, on matches between the two
    dates (the filter runs from the beginning of the data to warm up). `nu` > 0 uses a
    Student t, so a few prices far off what the filter expected don't decide the noise
    model. Returns the hyperparameters and a log of the fit."""
    import multiprocessing as mp
    from scipy.optimize import minimize

    names = names or [f.name for f in fields(Hyper)]
    start = start or Hyper()
    _GROUPS.clear()
    for lg in leagues:
        df = group(matches, lg)
        df = df[df["date"] < pd.Timestamp(train_to)].reset_index(drop=True)
        _GROUPS.append((lg, df, (df["date"] >= pd.Timestamp(train_from)).to_numpy()))
    history = []
    with mp.get_context("fork").Pool(min(workers, len(_GROUPS))) as pool:
        def objective(v: np.ndarray) -> float:
            hp = start.with_vector(names, v)
            res = pool.map(_group_loglik, [(k, hp, nu) for k in range(len(_GROUPS))])
            ll, n = sum(r[0] for r in res), sum(r[1] for r in res)
            history.append(-ll / n)
            return -ll / n
        result = minimize(objective, start.to_vector(names), method="Powell",
                          options={"xtol": 1e-3, "ftol": 1e-7, "maxfev": maxfev})
    best = start.with_vector(names, result.x)
    return best, {"loglik_per_match": -float(result.fun), "evaluations": len(history),
                  "converged": bool(result.success), "start_loglik": -history[0], "nu": nu,
                  "train": [train_from, train_to], "leagues": leagues}


def main() -> int:
    import argparse
    import os
    import time

    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "FLEXIBLAS_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    import store
    from backtest import OUT_DIR, report
    from ingest import season_start_year

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit", help="learn the noise model on past seasons")
    f.add_argument("--leagues", default="E0,SP1,D1,I1,F1")
    f.add_argument("--train-from", default="2006-07-01")
    f.add_argument("--train-to", default="2016-07-01")
    f.add_argument("--fix", default="", help="hyperparameters to keep at their default")
    f.add_argument("--nu", type=float, default=0.0, help="Student t degrees of freedom (0: normal)")
    f.add_argument("--start", default="", help="name=value,... to start from instead of the default")
    f.add_argument("--maxfev", type=int, default=4000)
    f.add_argument("--out", default=str(PARAMS_FILE))
    b = sub.add_parser("backtest", help="walk-forward with the fitted noise model")
    b.add_argument("--leagues", default="E0,SP1,D1,I1,F1")
    b.add_argument("--from", dest="first", type=int, default=2016)
    b.add_argument("--to", dest="last", type=int, default=2025)
    b.add_argument("--daily", action="store_true", help="update every day instead of weekly")
    b.add_argument("--plugin", action="store_true", help="no integration over uncertainty")
    b.add_argument("--set", default="", help="override hyperparameters: name=value,...")
    b.add_argument("--hyper", default=str(PARAMS_FILE), help="fitted noise model to use ('default': none)")
    b.add_argument("--name", default="ss_market")
    args = parser.parse_args()

    conn = store.connect()
    leagues = args.leagues.split(",")
    from backtest import COMPANION
    matches = store.load_matches(conn, leagues + [COMPANION[l] for l in leagues if l in COMPANION])
    if args.cmd == "fit":
        fixed = set(filter(None, args.fix.split(",")))
        names = [f.name for f in fields(Hyper) if f.name not in fixed]
        t0 = time.time()
        start = Hyper(**{k: float(v) for k, v in (kv.split("=") for kv in filter(None, args.start.split(",")))})
        hyper, log = fit(matches, leagues, args.train_from, args.train_to, names, start, nu=args.nu,
                         maxfev=args.maxfev)
        log["seconds"] = round(time.time() - t0)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"hyper": asdict(hyper), "fit": log}, indent=2))
        print(json.dumps({"hyper": asdict(hyper), "fit": log}, indent=2))
        return 0

    hyper = Hyper() if args.hyper == "default" else Hyper.load(Path(args.hyper))
    for kv in filter(None, args.set.split(",")):
        k, v = kv.split("=")
        hyper = Hyper(**{**asdict(hyper), k: float(v)})
    seasons = sorted({s for s in matches["season"] if args.first <= season_start_year(s) <= args.last})
    t0 = time.time()
    pred = pd.concat([walk_forward(group(matches, lg), lg, seasons, hyper, None if args.daily else 7,
                                   not args.plugin) for lg in leagues], ignore_index=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pred.to_csv(OUT_DIR / f"{args.name}.csv.gz", index=False)
    table = report(pred)
    total = table["partidos"].sum()
    weighted = lambda c: (table[c] * table["partidos"]).sum() / total
    print(f"\n== {args.name}  ({seasons[0]}-{seasons[-1]}, {total} partidos, {time.time() - t0:.0f} s)")
    print(table.round(4).to_string(index=False))
    print(f"TOTAL  logloss modelo {weighted('logloss_modelo'):.4f}  mercado {weighted('logloss_mercado'):.4f}"
          f"  rps modelo {weighted('rps_modelo'):.4f}  mercado {weighted('rps_mercado'):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
