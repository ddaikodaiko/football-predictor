"""
What the market thought of each match already played, in expected goals.

A price is the best public estimate of a match: it already knows the injuries, the
line-ups, the transfers and the manager who just got sacked, which is exactly what the
Dixon-Coles fit on goals and xG is missing (see the backtest in ROADMAP.md). Turning
each past price into the two expected-goal numbers that reproduce it (λ home, λ away)
lets the fit learn from prices the same way it learns from goals and xG.

No look-ahead: a match is only ever predicted from the prices of matches played before
it. Its own price never enters its prediction (the fit only sees matches before `as_of`).

Inversion: the 1X2 price gives P(home) and P(away), the over/under 2.5 price gives
P(over); the λ pair whose Dixon-Coles matrix is closest to those three numbers (least
squares, on a log-spaced grid) is the market's opinion. Without an over/under price the
two 1X2 numbers alone still pin down both λ.
"""

from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import poisson

# ρ used to invert prices: the median of the fitted models (backtest, 17.937 matches).
RHO = -0.06
GRID = np.exp(np.linspace(np.log(0.05), np.log(5.0), 700))
MAX_GOALS = 10

# Sharpest first. Closing prices know the line-ups; pre-match averages are a day or two
# older but exist for every season since 2005.
SOURCES_1X2 = [("close_h", "close_d", "close_a"), ("pin_h", "pin_d", "pin_a"), ("avg_h", "avg_d", "avg_a"),
               ("b365_h", "b365_d", "b365_a")]
SOURCES_OU = [("ou_close_o", "ou_close_u"), ("ou_pin_o", "ou_pin_u"), ("ou_avg_o", "ou_avg_u"),
              ("ou_b365_o", "ou_b365_u")]


def remove_margin(odds: np.ndarray) -> np.ndarray:
    """Fair probabilities from decimal odds (n, k), power method, vectorised: p = (1/o)^c
    with c per row such that each row adds up to 1. Same method as odds_live.remove_margin
    (proportional over-rates long shots). Rows with any odds <= 1 or NaN come back NaN."""
    odds = np.asarray(odds, float)
    ok = np.all(odds > 1.0, axis=1)
    log_inv = -np.log(np.where(ok[:, None], odds, 2.0))     # placeholder 2.0 on bad rows
    c = np.ones(len(odds))
    for _ in range(50):                                      # Newton on Σ inv^c = 1
        powered = np.exp(c[:, None] * log_inv)
        step = (powered.sum(axis=1) - 1.0) / (powered * log_inv).sum(axis=1)
        c -= step
        if np.all(np.abs(step) < 1e-12):
            break
    p = np.exp(c[:, None] * log_inv)
    p /= p.sum(axis=1, keepdims=True)
    return np.where(ok[:, None], p, np.nan)


@lru_cache(maxsize=4)
def _grid(ou_weight: float = 1.0) -> tuple[np.ndarray, np.ndarray, cKDTree, cKDTree]:
    """P(home), P(away), P(over 2.5) for every (λh, λa) on the grid, with the same
    Dixon-Coles τ as ratings.score_matrix. Done as matrix products: 700² pairs in ~1 s."""
    g = np.arange(MAX_GOALS + 1)
    A = poisson.pmf(g[None, :], GRID[:, None])          # (n, 11): home goals
    B = A                                                # same grid for away goals
    i, j = np.indices((MAX_GOALS + 1, MAX_GOALS + 1))
    lh, la = GRID[:, None], GRID[None, :]
    a0, a1, b0, b1 = A[:, :1], A[:, 1:2], B[:, :1].T, B[:, 1:2].T
    d00 = a0 * b0 * (-lh * la * RHO)               # (τ - 1) × P on the four low scores
    d01 = a0 * b1 * (lh * RHO)                     # 0-1, an away win
    d10 = a1 * b0 * (la * RHO)                     # 1-0, a home win
    d11 = a1 * b1 * (-RHO)
    total = A @ np.ones((MAX_GOALS + 1, MAX_GOALS + 1)) @ B.T + d00 + d01 + d10 + d11
    ph = (A @ (i > j).astype(float) @ B.T + d10) / total
    pa = (A @ (i < j).astype(float) @ B.T + d01) / total
    po = A @ (i + j > 2.5).astype(float) @ B.T / total  # the four corrected cells are all under
    lam = np.stack(np.meshgrid(GRID, GRID, indexing="ij"), axis=-1).reshape(-1, 2)
    feats3 = np.stack([ph.ravel(), pa.ravel(), ou_weight * po.ravel()], axis=1)
    return lam, feats3, cKDTree(feats3), cKDTree(feats3[:, :2])


def _first_available(df: pd.DataFrame, sources: list[tuple[str, ...]]) -> np.ndarray:
    """Fair probabilities from the sharpest source each row has."""
    k = len(sources[0])
    out = np.full((len(df), k), np.nan)
    for cols in reversed(sources):                 # sharpest last, so it wins
        if not set(cols) <= set(df.columns):
            continue
        p = remove_margin(df[list(cols)].apply(pd.to_numeric, errors="coerce").to_numpy(float))
        has = ~np.isnan(p).any(axis=1)
        out[has] = p[has]
    return out


def implied_lambdas(df: pd.DataFrame, ou_weight: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """(λ home, λ away) the market priced for each row; NaN where there is no 1X2 price.
    `ou_weight` scales P(over) against the 1X2 numbers in the least squares (0 = ignore it)."""
    lam, _, tree3, tree2 = _grid(ou_weight)
    p1x2 = _first_available(df, SOURCES_1X2)
    pou = _first_available(df, SOURCES_OU)
    lh, la = np.full(len(df), np.nan), np.full(len(df), np.nan)
    with3 = ~np.isnan(p1x2).any(axis=1) & ~np.isnan(pou).any(axis=1) & (ou_weight > 0)
    with2 = ~np.isnan(p1x2).any(axis=1) & ~with3
    if with3.any():
        _, idx = tree3.query(np.column_stack([p1x2[with3][:, [0, 2]], ou_weight * pou[with3][:, 0]]))
        lh[with3], la[with3] = lam[idx, 0], lam[idx, 1]
    if with2.any():
        _, idx = tree2.query(p1x2[with2][:, [0, 2]])
        lh[with2], la[with2] = lam[idx, 0], lam[idx, 1]
    return lh, la


def add_market_lambdas(matches: pd.DataFrame, ou_weight: float = 1.0) -> pd.DataFrame:
    """`matches` with two more columns, mkt_home and mkt_away."""
    lh, la = implied_lambdas(matches, ou_weight)
    return matches.assign(mkt_home=lh, mkt_away=la)
