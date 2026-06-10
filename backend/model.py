"""
Football prediction model — data pipeline + training + inference.
All I/O stays in api.py; this module is pure ML.
"""

import json
import time
import warnings
from collections import Counter
from io import StringIO

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")

BASE_URL = "https://www.football-data.co.uk/mmz4281"
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"

SEASONS = ["2526", "2425", "2324", "2223", "2122", "2021"]
COLUMNS = [
    "Date", "HomeTeam", "AwayTeam",
    "FTHG", "FTAG", "FTR",
    "HS", "AS", "HST", "AST",
    "HC", "AC", "HF", "AF",
    "B365H", "B365D", "B365A",
]
FEAT_COLS = [
    # All-game EWM rolling stats
    "home_avg_GF", "away_avg_GF", "diff_avg_GF",
    "home_avg_GA", "away_avg_GA", "diff_avg_GA",
    "home_avg_SoT", "away_avg_SoT", "diff_avg_SoT",
    "home_avg_Pts", "away_avg_Pts", "diff_avg_Pts",
    "home_avg_GD", "away_avg_GD", "diff_avg_GD",
    # Home/away context split
    "home_avg_GF_h", "home_avg_GA_h",
    "away_avg_GF_a", "away_avg_GA_a",
    # ELO
    "elo_home", "elo_away", "elo_diff", "elo_exp_home",
    # Bookmaker odds
    "norm_pH", "norm_pD", "norm_pA", "odds_spread",
    # Rest/fatigue
    "rest_home", "rest_away", "rest_diff",
    # H2H
    "h2h_home_win_pct", "h2h_draw_pct", "h2h_away_win_pct",
    "h2h_avg_goals_home", "h2h_avg_goals_away",
    # New features
    "home_avg_shots", "away_avg_shots", "diff_avg_shots",
    "home_avg_corners", "away_avg_corners", "diff_avg_corners",
    "home_shot_eff", "away_shot_eff",
    "home_streak", "away_streak",
    "home_win_rate_5", "away_win_rate_5",
    # xG proxy
    "home_avg_xG_proxy", "away_avg_xG_proxy", "diff_avg_xG_proxy",
    "home_avg_xG_overperf", "away_avg_xG_overperf",
]

EWM_SPAN = 6  # exponential span ≈ "last 6 matches weighted"

_HTFT_LABEL = {
    "HH": "1/1", "HD": "1/X", "HA": "1/2",
    "DH": "X/1", "DD": "X/X", "DA": "X/2",
    "AH": "2/1", "AD": "2/X", "AA": "2/2",
}


# ─── DATA ──────────────────────────────────────────────────────────────────────

def _load_league(league: str, seasons: list[str]) -> pd.DataFrame:
    frames = []
    for season in seasons:
        url = f"{BASE_URL}/{season}/{league}.csv"
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            df = pd.read_csv(StringIO(resp.text), on_bad_lines="skip")
            available = [c for c in COLUMNS if c in df.columns]
            df = df[available].copy()
            df["League"] = league
            df["Season"] = season
            frames.append(df)
        except Exception:
            pass
        time.sleep(0.3)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    for c in ["FTHG", "FTAG", "HS", "AS", "HST", "AST", "HC", "AC",
              "HF", "AF", "B365H", "B365D", "B365A"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Result"] = df["FTR"].map({"H": 2, "D": 1, "A": 0})
    return df


# ─── ELO ───────────────────────────────────────────────────────────────────────

class ELO:
    def __init__(self, k: int = 32, home_adv: int = 65):
        self.k = k
        self.home_adv = home_adv
        self.ratings: dict[str, float] = {}

    def get(self, team: str) -> float:
        return self.ratings.setdefault(team, 1500.0)

    def _expected(self, r_a: float, r_b: float) -> float:
        return 1.0 / (1.0 + 10 ** ((r_b - r_a) / 400.0))

    def update(self, home: str, away: str, hg: int, ag: int):
        r_h = self.get(home) + self.home_adv
        r_a = self.get(away)
        e_h = self._expected(r_h, r_a)
        s_h = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        m = np.log(abs(hg - ag) + 1) + 1.0
        self.ratings[home] += self.k * m * (s_h - e_h)
        self.ratings[away] += self.k * m * ((1 - s_h) - (1 - e_h))

    def fit(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("Date").copy()
        rows = []
        for _, r in df.iterrows():
            h, a = r["HomeTeam"], r["AwayTeam"]
            rh, ra = self.get(h), self.get(a)
            rows.append({
                "elo_home": rh, "elo_away": ra,
                "elo_diff": rh - ra,
                "elo_exp_home": self._expected(rh + self.home_adv, ra),
            })
            if pd.notna(r.get("FTHG")) and pd.notna(r.get("FTAG")):
                self.update(h, a, int(r["FTHG"]), int(r["FTAG"]))
        return pd.concat([df.reset_index(drop=True), pd.DataFrame(rows)], axis=1)

    def top(self, n: int = 10) -> list[dict]:
        return [
            {"team": t, "elo": round(r)}
            for t, r in sorted(self.ratings.items(), key=lambda x: -x[1])[:n]
        ]


# ─── FEATURES ──────────────────────────────────────────────────────────────────

def _ewm(series: pd.Series, span: int = EWM_SPAN) -> pd.Series:
    """Exponential weighted mean — shift by 1 to avoid leakage."""
    return series.shift(1).ewm(span=span, min_periods=2).mean()


def _rolling(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("Date").copy()

    has_shots   = "HS" in df.columns and "AS" in df.columns
    has_corners = "HC" in df.columns and "AC" in df.columns

    # Build home records
    home_base = {"Date": "Date", "HomeTeam": "Team", "FTHG": "GF", "FTAG": "GA", "HST": "SoT"}
    away_base = {"Date": "Date", "AwayTeam": "Team", "FTAG": "GF", "FTHG": "GA", "AST": "SoT"}
    if has_shots:
        home_base["HS"] = "Shots"
        away_base["AS"] = "Shots"
    if has_corners:
        home_base["HC"] = "Corners"
        away_base["AC"] = "Corners"

    home_r = df[[c for c in home_base]].rename(columns=home_base).copy()
    home_r["IsHome"] = 1
    away_r = df[[c for c in away_base]].rename(columns=away_base).copy()
    away_r["IsHome"] = 0

    all_r = pd.concat([home_r, away_r]).sort_values("Date")

    per_team: dict = {}
    per_team_home: dict = {}
    per_team_away: dict = {}

    extra_ewm = ["SoT"]
    if has_shots:   extra_ewm.append("Shots")
    if has_corners: extra_ewm.append("Corners")

    for team in all_r["Team"].unique():
        td = all_r[all_r["Team"] == team].copy()
        td["Pts"] = td.apply(lambda r: 3 if r.GF > r.GA else (1 if r.GF == r.GA else 0), axis=1)
        td["GD"]  = td["GF"] - td["GA"]
        for col in ["GF", "GA", "Pts", "GD"] + extra_ewm:
            if col in td.columns:
                td[f"avg_{col}"] = _ewm(td[col])
        if has_shots and "Shots" in td.columns and "SoT" in td.columns:
            td["shot_eff"] = (td["SoT"] / td["Shots"].replace(0, np.nan)).fillna(0.33)
            td["avg_shot_eff"] = _ewm(td["shot_eff"])
            td["xG_proxy"] = td["SoT"] * 0.30 + (td["Shots"] - td["SoT"]).clip(lower=0) * 0.03
            td["xG_overperf"] = td["GF"] - td["xG_proxy"]
            td["avg_xG_proxy"] = _ewm(td["xG_proxy"])
            td["avg_xG_overperf"] = _ewm(td["xG_overperf"])
        per_team[team] = td

        th = td[td["IsHome"] == 1].copy()
        for col in ["GF", "GA"]:
            th[f"avg_{col}_h"] = _ewm(th[col], span=4)
        per_team_home[team] = th

        ta = td[td["IsHome"] == 0].copy()
        for col in ["GF", "GA"]:
            ta[f"avg_{col}_a"] = _ewm(ta[col], span=4)
        per_team_away[team] = ta

    all_stats = pd.concat(per_team.values())
    home_ctx  = pd.concat(v for v in per_team_home.values() if not v.empty)
    away_ctx  = pd.concat(v for v in per_team_away.values() if not v.empty)

    feat_list = []
    for idx, row in df.iterrows():
        h, a, dt = row["HomeTeam"], row["AwayTeam"], row["Date"]

        hs  = all_stats[(all_stats["Team"] == h) & (all_stats["Date"] == dt) & (all_stats["IsHome"] == 1)]
        as_ = all_stats[(all_stats["Team"] == a) & (all_stats["Date"] == dt) & (all_stats["IsHome"] == 0)]
        if hs.empty or as_.empty:
            continue

        feat: dict = {"match_idx": idx}

        def _val(df_row, col, fallback=0.0):
            return float(df_row[col].values[0]) if col in df_row.columns and not df_row.empty else fallback

        for col in ["GF", "GA", "SoT", "Pts", "GD"]:
            hv = _val(hs, f"avg_{col}")
            av = _val(as_, f"avg_{col}")
            feat[f"home_avg_{col}"] = hv
            feat[f"away_avg_{col}"] = av
            feat[f"diff_avg_{col}"] = hv - av

        if has_shots:
            hv = _val(hs, "avg_Shots")
            av = _val(as_, "avg_Shots")
            feat["home_avg_shots"] = hv
            feat["away_avg_shots"] = av
            feat["diff_avg_shots"] = hv - av
            feat["home_shot_eff"] = _val(hs, "avg_shot_eff", 0.33)
            feat["away_shot_eff"] = _val(as_, "avg_shot_eff", 0.33)
            hxg = _val(hs, "avg_xG_proxy")
            axg = _val(as_, "avg_xG_proxy")
            feat["home_avg_xG_proxy"] = hxg
            feat["away_avg_xG_proxy"] = axg
            feat["diff_avg_xG_proxy"] = hxg - axg
            feat["home_avg_xG_overperf"] = _val(hs, "avg_xG_overperf")
            feat["away_avg_xG_overperf"] = _val(as_, "avg_xG_overperf")

        if has_corners:
            hv = _val(hs, "avg_Corners")
            av = _val(as_, "avg_Corners")
            feat["home_avg_corners"] = hv
            feat["away_avg_corners"] = av
            feat["diff_avg_corners"] = hv - av

        # Home/away context
        hh = home_ctx[(home_ctx["Team"] == h) & (home_ctx["Date"] == dt)]
        aa = away_ctx[(away_ctx["Team"] == a) & (away_ctx["Date"] == dt)]
        feat["home_avg_GF_h"] = _val(hh, "avg_GF_h") if not hh.empty else feat["home_avg_GF"]
        feat["home_avg_GA_h"] = _val(hh, "avg_GA_h") if not hh.empty else feat["home_avg_GA"]
        feat["away_avg_GF_a"] = _val(aa, "avg_GF_a") if not aa.empty else feat["away_avg_GF"]
        feat["away_avg_GA_a"] = _val(aa, "avg_GA_a") if not aa.empty else feat["away_avg_GA"]

        feat_list.append(feat)

    feat_df = pd.DataFrame(feat_list).set_index("match_idx")
    return df.join(feat_df, how="inner")


def _h2h(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Add head-to-head historical features — no leakage (updated after each row)."""
    df = df.sort_values("Date").copy()
    history: dict = {}  # canonical key (t1, t2) -> [(match_home, hg, ag)]

    feat_list = []
    for idx, row in df.iterrows():
        h, a = row["HomeTeam"], row["AwayTeam"]
        key = tuple(sorted([h, a]))
        past = history.get(key, [])[-window:]

        if len(past) >= 2:
            h_goals = [hg if mh == h else ag for mh, hg, ag in past]
            a_goals = [ag if mh == h else hg for mh, hg, ag in past]
            n = len(past)
            h_wins = sum(1 for hg, ag in zip(h_goals, a_goals) if hg > ag)
            draws = sum(1 for hg, ag in zip(h_goals, a_goals) if hg == ag)
            feat = {
                "match_idx": idx,
                "h2h_home_win_pct": h_wins / n,
                "h2h_draw_pct": draws / n,
                "h2h_away_win_pct": (n - h_wins - draws) / n,
                "h2h_avg_goals_home": float(np.mean(h_goals)),
                "h2h_avg_goals_away": float(np.mean(a_goals)),
            }
        else:
            feat = {
                "match_idx": idx,
                "h2h_home_win_pct": 0.40, "h2h_draw_pct": 0.25, "h2h_away_win_pct": 0.35,
                "h2h_avg_goals_home": 1.3, "h2h_avg_goals_away": 1.0,
            }
        feat_list.append(feat)

        if pd.notna(row.get("FTHG")) and pd.notna(row.get("FTAG")):
            history.setdefault(key, []).append((h, int(row["FTHG"]), int(row["FTAG"])))

    feat_df = pd.DataFrame(feat_list).set_index("match_idx")
    return df.join(feat_df, how="inner")


def _odds(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if {"B365H", "B365D", "B365A"}.issubset(df.columns):
        df["odds_pH"] = 1 / df["B365H"]
        df["odds_pD"] = 1 / df["B365D"]
        df["odds_pA"] = 1 / df["B365A"]
        total = df["odds_pH"] + df["odds_pD"] + df["odds_pA"]
        df["norm_pH"] = df["odds_pH"] / total
        df["norm_pD"] = df["odds_pD"] / total
        df["norm_pA"] = df["odds_pA"] / total
        df["odds_spread"] = df["norm_pH"] - df["norm_pA"]
    return df


def _fatigue(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("Date").copy()
    rh, ra, last = [], [], {}
    for _, row in df.iterrows():
        h, a, d = row["HomeTeam"], row["AwayTeam"], row["Date"]
        rh.append(min((d - last.get(h, d - pd.Timedelta(14))).days, 30))
        ra.append(min((d - last.get(a, d - pd.Timedelta(14))).days, 30))
        last[h] = d
        last[a] = d
    df["rest_home"] = rh
    df["rest_away"] = ra
    df["rest_diff"] = df["rest_home"] - df["rest_away"]
    return df


# ─── MODEL ─────────────────────────────────────────────────────────────────────

def _ewm_mean(arr: list[float], span: int = EWM_SPAN) -> float:
    """EWM for inference — most recent item has highest weight."""
    if not arr:
        return 0.0
    a = np.array(arr, dtype=float)
    alpha = 2.0 / (span + 1)
    weights = (1 - alpha) ** np.arange(len(a) - 1, -1, -1)
    return float(np.sum(a * weights) / np.sum(weights))


def _compute_streak(results: list[str]) -> int:
    """Positive = winning streak, negative = losing streak, 0 = no streak."""
    if not results:
        return 0
    streak = 0
    last = results[-1]
    if last == 'D':
        return 0
    sign = 1 if last == 'W' else -1
    for r in reversed(results):
        if r == last:
            streak += sign
        else:
            break
    return streak


class FootballPredictor:
    def __init__(self):
        self.model: XGBClassifier | None = None
        self.scaler: StandardScaler | None = None
        self.elo: ELO | None = None
        self.df: pd.DataFrame | None = None
        self.used_cols: list[str] = []
        self.meta: dict = {}
        self.league_mean_goals: float = 1.2
        self._h2h_history: dict = {}
        self._team_strengths: dict = {}

    def train(self, leagues: list[str] = ("SP1", "F1")) -> dict:
        frames = [_load_league(lg, SEASONS) for lg in leagues]
        raw = pd.concat(frames, ignore_index=True)
        df = _clean(raw)
        df = _odds(df)
        df = _fatigue(df)
        self.elo = ELO()
        df = self.elo.fit(df)
        df = _rolling(df)
        df = _h2h(df)
        self.df = df

        finished = df.dropna(subset=["FTHG", "FTAG"])
        if len(finished) > 0:
            self.league_mean_goals = float((finished["FTHG"].mean() + finished["FTAG"].mean()) / 2)

        self._h2h_history = {}
        for _, row in df.sort_values("Date").iterrows():
            if pd.notna(row.get("FTHG")) and pd.notna(row.get("FTAG")):
                h, a = row["HomeTeam"], row["AwayTeam"]
                key = tuple(sorted([h, a]))
                self._h2h_history.setdefault(key, []).append(
                    (h, int(row["FTHG"]), int(row["FTAG"]))
                )

        df_train = df.dropna(subset=["Result"])
        cols = [c for c in FEAT_COLS if c in df_train.columns]
        self.used_cols = cols
        X = df_train[cols].fillna(df_train[cols].median())
        y = df_train["Result"].astype(int)

        split = int(len(X) * 0.8)
        X_tr, X_te = X.iloc[:split], X.iloc[split:]
        y_tr, y_te = y.iloc[:split], y.iloc[split:]

        self.scaler = StandardScaler()
        self.model = VotingClassifier(
            estimators=[
                ("lr", LogisticRegression(
                    max_iter=1000, C=0.5, random_state=42,
                )),
                ("rf", RandomForestClassifier(
                    n_estimators=150, max_depth=8,
                    min_samples_leaf=10, random_state=42,
                )),
                ("xgb", XGBClassifier(
                    n_estimators=400, max_depth=5,
                    learning_rate=0.04, subsample=0.8,
                    colsample_bytree=0.75, min_child_weight=3,
                    gamma=0.1, reg_alpha=0.1, reg_lambda=1.0,
                    random_state=42, eval_metric="mlogloss", verbosity=0,
                )),
            ],
            voting="soft",
            weights=[1, 1, 2],
        )
        self.model.fit(self.scaler.fit_transform(X_tr.values), y_tr)

        preds = self.model.predict(self.scaler.transform(X_te.values))
        proba = self.model.predict_proba(self.scaler.transform(X_te.values))

        self._team_strengths = self._compute_team_strengths()

        self.meta = {
            "total_matches": len(df_train),
            "train_matches": len(X_tr),
            "test_matches": len(X_te),
            "accuracy": round(accuracy_score(y_te, preds), 4),
            "log_loss": round(log_loss(y_te, proba), 4),
            "leagues": list(leagues),
            "seasons": SEASONS,
            "features": len(cols),
        }
        return self.meta

    # ── inference helpers ──────────────────────────────────────────────────────

    def _team_recent(self, team: str, is_home: bool, league: str) -> dict:
        df_lg = self.df[self.df["League"] == league]
        matches = df_lg[
            (df_lg["HomeTeam"] == team) | (df_lg["AwayTeam"] == team)
        ].dropna(subset=["FTR"]).sort_values("Date").tail(10)

        if matches.empty:
            return {}

        gf, ga, sot, pts, gd = [], [], [], [], []
        shots, corners = [], []
        home_gf, home_ga, away_gf, away_ga = [], [], [], []
        results: list[str] = []

        has_shots   = "HS" in self.df.columns and "AS" in self.df.columns
        has_corners = "HC" in self.df.columns and "AC" in self.df.columns

        for _, m in matches.iterrows():
            if m["HomeTeam"] == team:
                g, gc = m.get("FTHG", 0) or 0, m.get("FTAG", 0) or 0
                gf.append(g); ga.append(gc); sot.append(m.get("HST", 0) or 0)
                pts.append(3 if m["FTR"] == "H" else (1 if m["FTR"] == "D" else 0))
                gd.append(g - gc)
                home_gf.append(g); home_ga.append(gc)
                results.append("W" if m["FTR"] == "H" else ("D" if m["FTR"] == "D" else "L"))
                if has_shots:   shots.append(m.get("HS", 0) or 0)
                if has_corners: corners.append(m.get("HC", 0) or 0)
            else:
                g, gc = m.get("FTAG", 0) or 0, m.get("FTHG", 0) or 0
                gf.append(g); ga.append(gc); sot.append(m.get("AST", 0) or 0)
                pts.append(3 if m["FTR"] == "A" else (1 if m["FTR"] == "D" else 0))
                gd.append(g - gc)
                away_gf.append(g); away_ga.append(gc)
                results.append("W" if m["FTR"] == "A" else ("D" if m["FTR"] == "D" else "L"))
                if has_shots:   shots.append(m.get("AS", 0) or 0)
                if has_corners: corners.append(m.get("AC", 0) or 0)

        p = "home" if is_home else "away"

        # Form metrics
        form5      = results[-5:]
        streak     = _compute_streak(results)
        win_rate_5 = sum(1 for r in form5 if r == "W") / max(len(form5), 1)

        result: dict = {
            f"{p}_avg_GF":       round(_ewm_mean(gf), 2),
            f"{p}_avg_GA":       round(_ewm_mean(ga), 2),
            f"{p}_avg_SoT":      round(_ewm_mean(sot), 2),
            f"{p}_avg_Pts":      round(_ewm_mean(pts), 2),
            f"{p}_avg_GD":       round(_ewm_mean(gd), 2),
            f"elo_{p}":          self.elo.get(team),
            # Private fields for stats_ret passthrough
            f"_{p}_last5_gf":    gf[-5:],
            f"_{p}_last5_ga":    ga[-5:],
            f"_{p}_last5_pts":   pts[-5:],
            f"_{p}_form":        form5,
            f"_{p}_streak":      streak,
            f"_{p}_win_rate_5":  win_rate_5,
            # ML features
            f"{p}_streak":       streak,
            f"{p}_win_rate_5":   win_rate_5,
        }

        if has_shots and shots:
            avg_shots = round(_ewm_mean(shots), 2)
            result[f"{p}_avg_shots"] = avg_shots
            avg_sot = round(_ewm_mean(sot), 2)
            result[f"{p}_shot_eff"] = round(avg_sot / avg_shots, 3) if avg_shots > 0 else 0.33
            xg_list = [s * 0.30 + max(sh - s, 0) * 0.03 for sh, s in zip(shots, sot)]
            xg_overperf_list = [g - xg for g, xg in zip(gf, xg_list)]
            result[f"{p}_avg_xG_proxy"] = round(_ewm_mean(xg_list), 3)
            result[f"{p}_avg_xG_overperf"] = round(_ewm_mean(xg_overperf_list), 3)

        if has_corners and corners:
            result[f"{p}_avg_corners"] = round(_ewm_mean(corners), 2)

        if is_home and home_gf:
            result[f"{p}_avg_GF_h"] = round(_ewm_mean(home_gf, span=4), 2)
            result[f"{p}_avg_GA_h"] = round(_ewm_mean(home_ga, span=4), 2)
        elif not is_home and away_gf:
            result[f"{p}_avg_GF_a"] = round(_ewm_mean(away_gf, span=4), 2)
            result[f"{p}_avg_GA_a"] = round(_ewm_mean(away_ga, span=4), 2)

        return result

    def _h2h_stats(self, home: str, away: str) -> dict:
        key = tuple(sorted([home, away]))
        past = self._h2h_history.get(key, [])[-5:]

        if len(past) < 2:
            return {
                "h2h_home_win_pct": 0.40, "h2h_draw_pct": 0.25, "h2h_away_win_pct": 0.35,
                "h2h_avg_goals_home": 1.3, "h2h_avg_goals_away": 1.0,
            }

        h_goals = [hg if mh == home else ag for mh, hg, ag in past]
        a_goals = [ag if mh == home else hg for mh, hg, ag in past]
        n = len(past)
        h_wins = sum(1 for hg, ag in zip(h_goals, a_goals) if hg > ag)
        draws = sum(1 for hg, ag in zip(h_goals, a_goals) if hg == ag)
        return {
            "h2h_home_win_pct": round(h_wins / n, 3),
            "h2h_draw_pct": round(draws / n, 3),
            "h2h_away_win_pct": round((n - h_wins - draws) / n, 3),
            "h2h_avg_goals_home": round(float(np.mean(h_goals)), 2),
            "h2h_avg_goals_away": round(float(np.mean(a_goals)), 2),
        }

    # ── Dixon-Coles team strengths ─────────────────────────────────────────────

    def _compute_team_strengths(self) -> dict:
        """
        Pre-compute normalized attack/defense strength per team using xG proxy.

        Dixon-Coles model:
          λ_home = home_mean × att[home] × def[away]
          λ_away = away_mean × att[away] × def[home]

        att[team] = team's avg xG scored / league μ
        def[team] = team's avg goals conceded / league μ
        """
        df = self.df.dropna(subset=["FTHG", "FTAG"]).copy()

        # Use xG proxy as attack base (more stable than raw goals)
        has_shots = {"HS", "HST", "AS", "AST"}.issubset(df.columns)
        if has_shots:
            df["_xGH"] = df["HST"] * 0.30 + (df["HS"] - df["HST"]).clip(lower=0) * 0.03
            df["_xGA"] = df["AST"] * 0.30 + (df["AS"] - df["AST"]).clip(lower=0) * 0.03
            att_h_col, att_a_col = "_xGH", "_xGA"
        else:
            att_h_col, att_a_col = "FTHG", "FTAG"

        home_mean = float(df[att_h_col].mean())
        away_mean = float(df[att_a_col].mean())
        mu = (home_mean + away_mean) / 2

        attack: dict[str, float] = {}
        defense: dict[str, float] = {}
        all_teams = set(df["HomeTeam"].unique()) | set(df["AwayTeam"].unique())

        for team in all_teams:
            hm = df[df["HomeTeam"] == team]
            am = df[df["AwayTeam"] == team]

            scored = pd.concat([hm[att_h_col], am[att_a_col]]).dropna()
            conceded = pd.concat([hm["FTAG"], am["FTHG"]]).dropna()

            attack[team] = float(scored.mean() / mu) if len(scored) >= 3 else 1.0
            defense[team] = float(conceded.mean() / mu) if len(conceded) >= 3 else 1.0

        return {
            "attack": attack,
            "defense": defense,
            "home_mean": home_mean,
            "away_mean": away_mean,
            "mu": mu,
        }

    # ── Poisson + Dixon-Coles simulation ──────────────────────────────────────

    def simulate_match(
        self,
        home_stats: dict,
        away_stats: dict,
        n_sim: int = 50_000,
        home_team: str | None = None,
        away_team: str | None = None,
        rho: float = -0.10,
    ) -> dict:
        """
        Monte Carlo Poisson simulation with Dixon-Coles corrections:
          1. Dixon-Coles attack/defense strength model for λ estimation
          2. xG proxy as base rate (lower variance than raw goals)
          3. τ correction for low-score correlation (0-0, 1-0, 0-1, 1-1)
        """
        ts = self._team_strengths

        # ── Lambda estimation ──────────────────────────────────────────────────
        if (ts and home_team and away_team
                and home_team in ts["attack"] and away_team in ts["attack"]):
            # Dixon-Coles: λ = baseline × att[team] × def[opponent]
            lambda_home = max(
                ts["home_mean"] * ts["attack"][home_team] * ts["defense"][away_team], 0.2
            )
            lambda_away = max(
                ts["away_mean"] * ts["attack"][away_team] * ts["defense"][home_team], 0.2
            )
        else:
            # Fallback to rolling-average method
            lh_att = home_stats.get("avg_GF_h") or home_stats.get("avg_GF", 1.3)
            la_def = away_stats.get("avg_GA_a") or away_stats.get("avg_GA", 1.2)
            la_att = away_stats.get("avg_GF_a") or away_stats.get("avg_GF", 1.1)
            lh_def = home_stats.get("avg_GA_h") or home_stats.get("avg_GA", 1.1)
            lambda_home = max((lh_att + la_def) / 2, 0.2)
            lambda_away = max((la_att + lh_def) / 2, 0.2)

        # ── Monte Carlo ────────────────────────────────────────────────────────
        rng = np.random.default_rng()
        hg = rng.poisson(lambda_home, n_sim)
        ag = rng.poisson(lambda_away, n_sim)

        # ── Dixon-Coles τ correction ───────────────────────────────────────────
        # Poisson underestimates correlation in low-scoring events.
        # ρ < 0 → increases weight of 0-0 and 1-1 (symmetric outcomes).
        tau = np.ones(n_sim)
        tau[(hg == 0) & (ag == 0)] = 1.0 - lambda_home * lambda_away * rho
        tau[(hg == 1) & (ag == 0)] = 1.0 + lambda_away * rho
        tau[(hg == 0) & (ag == 1)] = 1.0 + lambda_home * rho
        tau[(hg == 1) & (ag == 1)] = 1.0 - rho
        tau = np.maximum(tau, 1e-9)
        weights = tau / tau.sum()

        # ── Weighted statistics ────────────────────────────────────────────────
        total = hg + ag

        # Vectorized top-score computation
        pairs = np.stack([hg, ag], axis=1)
        unique_pairs, inverse = np.unique(pairs, axis=0, return_inverse=True)
        score_w = np.zeros(len(unique_pairs))
        np.add.at(score_w, inverse, weights)
        top_idx = np.argsort(-score_w)[:6]
        top_scores = [
            {"score": f"{unique_pairs[i][0]}-{unique_pairs[i][1]}", "prob": round(float(score_w[i]), 4)}
            for i in top_idx
        ]

        # ── HT/FT simulation ──────────────────────────────────────────────────
        # 47% of goals occur in the first half on average (empirical)
        HT_SPLIT = 0.47
        hg_ht = rng.poisson(lambda_home * HT_SPLIT, n_sim)
        ag_ht = rng.poisson(lambda_away * HT_SPLIT, n_sim)
        ht_h = hg_ht > ag_ht
        ht_d = hg_ht == ag_ht
        ht_a = hg_ht < ag_ht
        ft_h = hg > ag
        ft_d = hg == ag
        ft_a = hg < ag
        htft = {}
        for ht_m, ft_m, code in [
            (ht_h, ft_h, "HH"), (ht_h, ft_d, "HD"), (ht_h, ft_a, "HA"),
            (ht_d, ft_h, "DH"), (ht_d, ft_d, "DD"), (ht_d, ft_a, "DA"),
            (ht_a, ft_h, "AH"), (ht_a, ft_d, "AD"), (ht_a, ft_a, "AA"),
        ]:
            htft[code] = round(float(np.sum(weights[ht_m & ft_m])), 4)
        htft_sorted = sorted(htft.items(), key=lambda x: -x[1])

        return {
            "lambda_home": round(lambda_home, 3),
            "lambda_away": round(lambda_away, 3),
            "p_home": round(float(np.sum(weights[hg > ag])), 4),
            "p_draw": round(float(np.sum(weights[hg == ag])), 4),
            "p_away": round(float(np.sum(weights[hg < ag])), 4),
            "over25": round(float(np.sum(weights[total > 2.5])), 4),
            "over15": round(float(np.sum(weights[total > 1.5])), 4),
            "over35": round(float(np.sum(weights[total > 3.5])), 4),
            "btts": round(float(np.sum(weights[(hg > 0) & (ag > 0)])), 4),
            "cs_home": round(float(np.sum(weights[ag == 0])), 4),
            "cs_away": round(float(np.sum(weights[hg == 0])), 4),
            "dnb_home": round(float(np.sum(weights[hg > ag])) / max(float(np.sum(weights[hg != ag])), 1e-9), 4),
            "dnb_away": round(float(np.sum(weights[hg < ag])) / max(float(np.sum(weights[hg != ag])), 1e-9), 4),
            "ah_plus_half_home": round(float(np.sum(weights[hg >= ag])), 4),
            "ah_plus_half_away": round(float(np.sum(weights[ag >= hg])), 4),
            "htft": dict(htft_sorted),
            "htft_top": [{"combo": c, "label": _HTFT_LABEL[c], "prob": p} for c, p in htft_sorted[:5]],
            "top_scores": top_scores,
        }

    # ── In-play simulation ────────────────────────────────────────────────────

    def simulate_inplay(
        self,
        home_team: str,
        away_team: str,
        score_home: int,
        score_away: int,
        minute: int,
        n_sim: int = 50_000,
        rho: float = -0.10,
    ) -> dict:
        """
        Conditional simulation from current match state.
        Scales Dixon-Coles lambdas to remaining time, then simulates
        additional goals and conditions on current score.
        """
        ts = self._team_strengths
        minute = max(1, min(minute, 89))
        remaining = (90 - minute) / 90.0

        if (ts and home_team in ts["attack"] and away_team in ts["attack"]):
            lh_full = max(ts["home_mean"] * ts["attack"][home_team] * ts["defense"][away_team], 0.2)
            la_full = max(ts["away_mean"] * ts["attack"][away_team] * ts["defense"][home_team], 0.2)
        else:
            lh_full, la_full = 1.3, 1.1

        lh = lh_full * remaining
        la = la_full * remaining

        rng = np.random.default_rng()
        add_h = rng.poisson(lh, n_sim)
        add_a = rng.poisson(la, n_sim)

        # Dixon-Coles τ on remaining goals
        tau = np.ones(n_sim)
        tau[(add_h == 0) & (add_a == 0)] = 1.0 - lh * la * rho
        tau[(add_h == 1) & (add_a == 0)] = 1.0 + la * rho
        tau[(add_h == 0) & (add_a == 1)] = 1.0 + lh * rho
        tau[(add_h == 1) & (add_a == 1)] = 1.0 - rho
        tau = np.maximum(tau, 1e-9)
        weights = tau / tau.sum()

        fh = score_home + add_h
        fa = score_away + add_a
        total = fh + fa

        pairs = np.stack([fh, fa], axis=1)
        unique_pairs, inverse = np.unique(pairs, axis=0, return_inverse=True)
        score_w = np.zeros(len(unique_pairs))
        np.add.at(score_w, inverse, weights)
        top_idx = np.argsort(-score_w)[:6]
        top_scores = [
            {"score": f"{unique_pairs[i][0]}-{unique_pairs[i][1]}", "prob": round(float(score_w[i]), 4)}
            for i in top_idx
        ]

        return {
            "lambda_home_remaining": round(lh, 3),
            "lambda_away_remaining": round(la, 3),
            "lambda_home_full": round(lh_full, 3),
            "lambda_away_full": round(la_full, 3),
            "p_home": round(float(np.sum(weights[fh > fa])), 4),
            "p_draw": round(float(np.sum(weights[fh == fa])), 4),
            "p_away": round(float(np.sum(weights[fh < fa])), 4),
            "over25": round(float(np.sum(weights[total > 2.5])), 4),
            "over15": round(float(np.sum(weights[total > 1.5])), 4),
            "over35": round(float(np.sum(weights[total > 3.5])), 4),
            "btts": round(float(np.sum(weights[(fh > 0) & (fa > 0)])), 4),
            "cs_home": round(float(np.sum(weights[fa == score_away])), 4),
            "cs_away": round(float(np.sum(weights[fh == score_home])), 4),
            "dnb_home": round(float(np.sum(weights[fh > fa])) / max(float(np.sum(weights[fh != fa])), 1e-9), 4),
            "dnb_away": round(float(np.sum(weights[fh < fa])) / max(float(np.sum(weights[fh != fa])), 1e-9), 4),
            "top_scores": top_scores,
            "current_score": f"{score_home}-{score_away}",
            "minute": minute,
            "remaining_minutes": 90 - minute,
        }

    # ── main predict ──────────────────────────────────────────────────────────

    def predict_match(
        self,
        home: str, away: str,
        home_league: str = "SP1", away_league: str = "SP1",
        b365h: float | None = None,
        b365d: float | None = None,
        b365a: float | None = None,
    ) -> dict:
        home_feats = self._team_recent(home, True, home_league)
        away_feats = self._team_recent(away, False, away_league)
        h2h = self._h2h_stats(home, away)
        row = {**home_feats, **away_feats, **h2h}

        for stat in ["avg_GF", "avg_GA", "avg_SoT", "avg_Pts", "avg_GD"]:
            row[f"diff_{stat}"] = row.get(f"home_{stat}", 0) - row.get(f"away_{stat}", 0)

        # Shots diff
        if "home_avg_shots" in row and "away_avg_shots" in row:
            row["diff_avg_shots"] = row["home_avg_shots"] - row["away_avg_shots"]
        if "home_avg_corners" in row and "away_avg_corners" in row:
            row["diff_avg_corners"] = row["home_avg_corners"] - row["away_avg_corners"]
        if "home_avg_xG_proxy" in row and "away_avg_xG_proxy" in row:
            row["diff_avg_xG_proxy"] = row["home_avg_xG_proxy"] - row["away_avg_xG_proxy"]

        rh, ra = self.elo.get(home), self.elo.get(away)
        row["elo_diff"]     = rh - ra
        row["elo_exp_home"] = 1.0 / (1.0 + 10 ** ((ra - (rh + 65)) / 400.0))

        if b365h and b365d and b365a:
            total = 1 / b365h + 1 / b365d + 1 / b365a
            row["norm_pH"]    = (1 / b365h) / total
            row["norm_pD"]    = (1 / b365d) / total
            row["norm_pA"]    = (1 / b365a) / total
            row["odds_spread"] = row["norm_pH"] - row["norm_pA"]

        row["rest_home"] = 7
        row["rest_away"] = 7
        row["rest_diff"] = 0

        X = pd.DataFrame([row]).reindex(columns=self.used_cols, fill_value=0)
        proba = self.model.predict_proba(self.scaler.transform(X.values))[0]

        home_stats_ret = {
            "avg_GF":    row.get("home_avg_GF", 0),
            "avg_GA":    row.get("home_avg_GA", 0),
            "avg_SoT":   row.get("home_avg_SoT", 0),
            "avg_Pts":   row.get("home_avg_Pts", 0),
            "avg_GF_h":  row.get("home_avg_GF_h"),
            "avg_GA_h":  row.get("home_avg_GA_h"),
            "avg_shots":   row.get("home_avg_shots"),
            "avg_corners": row.get("home_avg_corners"),
            "form":   row.get("_home_form", []),
            "streak": row.get("_home_streak", 0),
        }
        away_stats_ret = {
            "avg_GF":    row.get("away_avg_GF", 0),
            "avg_GA":    row.get("away_avg_GA", 0),
            "avg_SoT":   row.get("away_avg_SoT", 0),
            "avg_Pts":   row.get("away_avg_Pts", 0),
            "avg_GF_a":  row.get("away_avg_GF_a"),
            "avg_GA_a":  row.get("away_avg_GA_a"),
            "avg_shots":   row.get("away_avg_shots"),
            "avg_corners": row.get("away_avg_corners"),
            "form":   row.get("_away_form", []),
            "streak": row.get("_away_streak", 0),
        }

        simulation = self.simulate_match(home_stats_ret, away_stats_ret, home_team=home, away_team=away)

        if b365h and b365d and b365a:
            bk_total = 1/b365h + 1/b365d + 1/b365a
            bk_ph = round((1/b365h) / bk_total, 4)
            bk_pd = round((1/b365d) / bk_total, 4)
            bk_pa = round((1/b365a) / bk_total, 4)
        else:
            bk_ph = bk_pd = bk_pa = None

        return {
            "home": home,
            "away": away,
            "home_league": home_league,
            "away_league": away_league,
            "p_home": round(float(proba[2]), 4),
            "p_draw": round(float(proba[1]), 4),
            "p_away": round(float(proba[0]), 4),
            "elo_home": round(rh),
            "elo_away": round(ra),
            "elo_exp_home": round(row["elo_exp_home"], 4),
            "home_stats": home_stats_ret,
            "away_stats": away_stats_ret,
            "h2h": h2h,
            "bookmaker": {"p_home": bk_ph, "p_draw": bk_pd, "p_away": bk_pa},
            "simulation": simulation,
            "cross_league": home_league != away_league,
        }

    def elo_ranking(self, n: int = 20) -> list[dict]:
        return self.elo.top(n)

    def feature_importance(self, top_n: int = 15) -> list[dict]:
        if self.model is None:
            return []
        xgb = self.model.named_estimators_["xgb"]
        scores = xgb.feature_importances_
        return sorted(
            [{"feature": f, "importance": round(float(s), 4)}
             for f, s in zip(self.used_cols, scores)],
            key=lambda x: -x["importance"]
        )[:top_n]


# ─── POLYMARKET ────────────────────────────────────────────────────────────────

def polymarket_search(home: str, away: str) -> dict | None:
    keywords = [
        w.lower() for team in [home, away]
        for w in team.split() if len(w) > 3
    ] + ["conference", "league", "soccer"]
    try:
        resp = requests.get(
            f"{POLYMARKET_GAMMA}/markets",
            params={"active": "true", "closed": "false", "limit": 200},
            timeout=10,
        )
        for market in resp.json():
            q = market.get("question", "").lower()
            if sum(1 for kw in keywords if kw in q) >= 2:
                prices_raw = market.get("outcomePrices", "[]")
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                if prices:
                    return {
                        "question": market.get("question"),
                        "prices": [round(float(p), 4) for p in prices],
                        "outcomes": market.get("outcomes", []),
                        "liquidity": float(market.get("liquidity") or 0),
                        "volume_24h": float(market.get("volume24hr") or 0),
                    }
    except Exception:
        pass
    return None
