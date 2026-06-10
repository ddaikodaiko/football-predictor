#!/usr/bin/env python3
"""
Football Predictor — La Liga + Conference League
Data: football-data.co.uk (free, no auth)
Model: XGBoost
Odds layer: Polymarket Gamma API (free, no auth)
"""

import json
import time
import warnings
from datetime import date
from io import StringIO

import numpy as np
import pandas as pd
import requests
from sklearn.metrics import accuracy_score, log_loss
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")

# ─── CONFIG ────────────────────────────────────────────────────────────────────

SEASONS = ["2526", "2425", "2324", "2223", "2122", "2021"]
BASE_URL = "https://www.football-data.co.uk/mmz4281"
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"

COLUMNS = [
    "Date", "HomeTeam", "AwayTeam",
    "FTHG", "FTAG", "FTR",
    "HS", "AS", "HST", "AST",
    "HC", "AC", "HF", "AF",
    "B365H", "B365D", "B365A",
]

# Conference League match — change RAYO_IS_HOME if needed
RAYO_IS_HOME = False  # Strasbourg local, Rayo visitante

# Override La Liga fixtures if auto-detect fails (add manually)
# e.g. [("Real Madrid", "Barcelona"), ("Atletico", "Sevilla")]
LALIGA_MANUAL_FIXTURES: list[tuple[str, str]] = []


# ─── DATA LOADING ──────────────────────────────────────────────────────────────

def load_league(league: str, seasons: list[str]) -> pd.DataFrame:
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
            print(f"  ✓ {league} {season}: {len(df)} partidos")
        except Exception as e:
            print(f"  ✗ {league} {season}: {e}")
        time.sleep(0.3)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)

    nums = ["FTHG", "FTAG", "HS", "AS", "HST", "AST",
            "HC", "AC", "HF", "AF", "B365H", "B365D", "B365A"]
    for c in nums:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["Result"] = df["FTR"].map({"H": 2, "D": 1, "A": 0})
    return df


def get_todays_laliga_fixtures() -> list[tuple]:
    """Pull today's unplayed La Liga matches from current season CSV."""
    url = f"{BASE_URL}/2526/SP1.csv"
    try:
        resp = requests.get(url, timeout=15)
        df = pd.read_csv(StringIO(resp.text), on_bad_lines="skip")
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        today = pd.Timestamp(date.today())
        mask = (df["Date"] == today) & (df["FTR"].isna())
        fixtures = df[mask][["HomeTeam", "AwayTeam"]].values.tolist()
        return [(h, a) for h, a in fixtures]
    except Exception:
        return []


# ─── ELO ───────────────────────────────────────────────────────────────────────

class ELO:
    def __init__(self, k: int = 32, home_adv: int = 65):
        self.k = k
        self.home_adv = home_adv
        self.ratings: dict[str, float] = {}

    def get(self, team: str) -> float:
        return self.ratings.setdefault(team, 1500.0)

    def expected(self, r_a: float, r_b: float) -> float:
        return 1.0 / (1.0 + 10 ** ((r_b - r_a) / 400.0))

    def update(self, home: str, away: str, hg: int, ag: int):
        r_h = self.get(home) + self.home_adv
        r_a = self.get(away)
        e_h = self.expected(r_h, r_a)
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
                "elo_home": rh,
                "elo_away": ra,
                "elo_diff": rh - ra,
                "elo_exp_home": self.expected(rh + self.home_adv, ra),
            })
            if pd.notna(r.get("FTHG")) and pd.notna(r.get("FTAG")):
                self.update(h, a, int(r["FTHG"]), int(r["FTAG"]))
        return pd.concat([df.reset_index(drop=True),
                          pd.DataFrame(rows)], axis=1)


# ─── FEATURES ──────────────────────────────────────────────────────────────────

def rolling_stats(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    df = df.sort_values("Date").copy()

    home_r = df[["Date", "HomeTeam", "FTHG", "FTAG", "HST", "AST"]].copy()
    home_r.columns = ["Date", "Team", "GF", "GA", "SoT", "SoTA"]
    home_r["IsHome"] = 1

    away_r = df[["Date", "AwayTeam", "FTAG", "FTHG", "AST", "HST"]].copy()
    away_r.columns = ["Date", "Team", "GF", "GA", "SoT", "SoTA"]
    away_r["IsHome"] = 0

    all_r = pd.concat([home_r, away_r]).sort_values("Date")

    per_team = {}
    for team in all_r["Team"].unique():
        td = all_r[all_r["Team"] == team].copy()
        td["Pts"] = td.apply(
            lambda r: 3 if r.GF > r.GA else (1 if r.GF == r.GA else 0), axis=1
        )
        for col in ["GF", "GA", "SoT", "Pts"]:
            td[f"avg_{col}"] = (
                td[col].shift(1).rolling(window, min_periods=2).mean()
            )
        per_team[team] = td

    all_stats = pd.concat(per_team.values())
    avg_cols = [c for c in all_stats.columns if c.startswith("avg_")]

    feat_list = []
    for idx, row in df.iterrows():
        h, a, dt = row["HomeTeam"], row["AwayTeam"], row["Date"]
        hs = all_stats[(all_stats["Team"] == h) & (all_stats["Date"] == dt) & (all_stats["IsHome"] == 1)]
        as_ = all_stats[(all_stats["Team"] == a) & (all_stats["Date"] == dt) & (all_stats["IsHome"] == 0)]
        if hs.empty or as_.empty:
            continue
        feat = {"match_idx": idx}
        for f in avg_cols:
            hv = hs[f].values[0]
            av = as_[f].values[0]
            feat[f"home_{f}"] = hv
            feat[f"away_{f}"] = av
            feat[f"diff_{f}"] = hv - av
        feat_list.append(feat)

    feat_df = pd.DataFrame(feat_list).set_index("match_idx")
    return df.join(feat_df, how="inner")


def odds_features(df: pd.DataFrame) -> pd.DataFrame:
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


def fatigue(df: pd.DataFrame) -> pd.DataFrame:
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

FEAT_COLS = [
    "home_avg_GF", "away_avg_GF", "diff_avg_GF",
    "home_avg_GA", "away_avg_GA", "diff_avg_GA",
    "home_avg_SoT", "away_avg_SoT", "diff_avg_SoT",
    "home_avg_Pts", "away_avg_Pts", "diff_avg_Pts",
    "elo_home", "elo_away", "elo_diff", "elo_exp_home",
    "norm_pH", "norm_pD", "norm_pA", "odds_spread",
    "rest_home", "rest_away", "rest_diff",
]


USED_COLS: list[str] = []


def train(df: pd.DataFrame) -> tuple[XGBClassifier, StandardScaler]:
    global USED_COLS
    df = df.dropna(subset=["Result"])
    cols = [c for c in FEAT_COLS if c in df.columns]
    USED_COLS = cols
    X = df[cols].fillna(df[cols].median())
    y = df["Result"].astype(int)

    split = int(len(X) * 0.8)
    X_tr, X_te = X.iloc[:split], X.iloc[split:]
    y_tr, y_te = y.iloc[:split], y.iloc[split:]

    scaler = StandardScaler()
    model = XGBClassifier(
        n_estimators=300, max_depth=5,
        learning_rate=0.05, subsample=0.8,
        colsample_bytree=0.8, random_state=42,
        eval_metric="mlogloss", verbosity=0,
    )
    model.fit(scaler.fit_transform(X_tr.values), y_tr)

    preds = model.predict(scaler.transform(X_te.values))
    proba = model.predict_proba(scaler.transform(X_te.values))
    print(f"  Accuracy (test 20%): {accuracy_score(y_te, preds):.3f}")
    print(f"  Log Loss:            {log_loss(y_te, proba):.3f}")
    print(f"  Partidos entrenamiento: {len(X_tr)} | test: {len(X_te)}")

    return model, scaler


# ─── POLYMARKET ────────────────────────────────────────────────────────────────

def polymarket_search(home: str, away: str) -> dict | None:
    keywords = [
        w.lower() for team in [home, away]
        for w in team.split() if len(w) > 3
    ] + ["conference", "league"]

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
                        "prices": [float(p) for p in prices],
                        "outcomes": market.get("outcomes", []),
                        "liquidity": float(market.get("liquidity") or 0),
                        "volume_24h": float(market.get("volume24hr") or 0),
                    }
    except Exception:
        pass
    return None


# ─── PREDICTION ────────────────────────────────────────────────────────────────

def team_recent(team: str, is_home: bool, df: pd.DataFrame, elo: ELO) -> dict:
    matches = df[
        (df["HomeTeam"] == team) | (df["AwayTeam"] == team)
    ].dropna(subset=["FTR"]).sort_values("Date").tail(5)

    if matches.empty:
        return {}

    gf, ga, sot, pts = [], [], [], []
    for _, m in matches.iterrows():
        if m["HomeTeam"] == team:
            gf.append(m.get("FTHG", 0) or 0)
            ga.append(m.get("FTAG", 0) or 0)
            sot.append(m.get("HST", 0) or 0)
            pts.append(3 if m["FTR"] == "H" else (1 if m["FTR"] == "D" else 0))
        else:
            gf.append(m.get("FTAG", 0) or 0)
            ga.append(m.get("FTHG", 0) or 0)
            sot.append(m.get("AST", 0) or 0)
            pts.append(3 if m["FTR"] == "A" else (1 if m["FTR"] == "D" else 0))

    p = "home" if is_home else "away"
    return {
        f"{p}_avg_GF": np.mean(gf),
        f"{p}_avg_GA": np.mean(ga),
        f"{p}_avg_SoT": np.mean(sot),
        f"{p}_avg_Pts": np.mean(pts),
        f"elo_{p}": elo.get(team),
    }


def predict(
    home: str, away: str,
    model: XGBClassifier, scaler: StandardScaler,
    df_all: pd.DataFrame, elo: ELO,
    b365h: float = None, b365d: float = None, b365a: float = None,
    home_league: str = "SP1", away_league: str = "SP1",
) -> dict:
    df_h = df_all[df_all["League"] == home_league]
    df_a = df_all[df_all["League"] == away_league]

    row = {
        **team_recent(home, True, df_h, elo),
        **team_recent(away, False, df_a, elo),
    }

    for stat in ["avg_GF", "avg_GA", "avg_SoT", "avg_Pts"]:
        row[f"diff_{stat}"] = row.get(f"home_{stat}", 0) - row.get(f"away_{stat}", 0)

    rh, ra = elo.get(home), elo.get(away)
    row["elo_diff"] = rh - ra
    row["elo_exp_home"] = 1.0 / (1.0 + 10 ** ((ra - (rh + 65)) / 400.0))

    if b365h and b365d and b365a:
        total = 1 / b365h + 1 / b365d + 1 / b365a
        row["norm_pH"] = (1 / b365h) / total
        row["norm_pD"] = (1 / b365d) / total
        row["norm_pA"] = (1 / b365a) / total
        row["odds_spread"] = row["norm_pH"] - row["norm_pA"]

    row["rest_home"] = 7
    row["rest_away"] = 7
    row["rest_diff"] = 0

    X = pd.DataFrame([row]).reindex(columns=USED_COLS, fill_value=0)
    X_s = scaler.transform(X.values)
    proba = model.predict_proba(X_s)[0]  # [away, draw, home]

    return {
        "home": home, "away": away,
        "p_home": proba[2], "p_draw": proba[1], "p_away": proba[0],
        "elo_home": rh, "elo_away": ra,
    }


# ─── OUTPUT ────────────────────────────────────────────────────────────────────

def print_pred(pred: dict, poly: dict | None = None, note: str = ""):
    W = 58
    print(f"\n{'─' * W}")
    print(f"  {pred['home']} vs {pred['away']}")
    if note:
        print(f"  ⚠  {note}")
    print(f"  ELO: {pred['elo_home']:.0f} vs {pred['elo_away']:.0f}")
    print()

    ph = f"{pred['p_home']:.1%}"
    pd_ = f"{pred['p_draw']:.1%}"
    pa = f"{pred['p_away']:.1%}"

    poly_h = poly_d = poly_a = "—"
    if poly:
        prices = poly["prices"]
        outcomes = [o.lower() for o in poly.get("outcomes", [])]
        if len(prices) == 3:
            poly_h = f"{prices[0]:.1%}"
            poly_d = f"{prices[1]:.1%}"
            poly_a = f"{prices[2]:.1%}"
        elif len(prices) == 2:
            # Binary market — map to home/away
            poly_h = f"{prices[0]:.1%}"
            poly_a = f"{prices[1]:.1%}"

    print(f"  {'':18} {'Modelo':>10}  {'Polymarket':>12}")
    print(f"  {'─' * 18} {'─' * 10}  {'─' * 12}")
    print(f"  {'1  ' + pred['home'][:14]:<18} {ph:>10}  {poly_h:>12}")
    print(f"  {'X  Empate':<18} {pd_:>10}  {poly_d:>12}")
    print(f"  {'2  ' + pred['away'][:14]:<18} {pa:>10}  {poly_a:>12}")

    best_label = max(
        [("1", pred["p_home"]), ("X", pred["p_draw"]), ("2", pred["p_away"])],
        key=lambda x: x[1],
    )
    conf = best_label[1]
    conf_str = "Alta" if conf > 0.55 else ("Media" if conf > 0.44 else "Baja")
    print(f"\n  → {best_label[0]}  |  Confianza: {conf_str} ({conf:.1%})")
    if poly:
        print(f"  → Polymarket: ${poly['liquidity']:,.0f} liquidez "
              f"| ${poly['volume_24h']:,.0f} vol 24h")


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 58)
    print("  FOOTBALL PREDICTOR")
    print(f"  {date.today()}")
    print("=" * 58)

    # 1. Download data
    print("\n[1/4] Descargando datos históricos...")
    df_sp1 = load_league(league="SP1", seasons=SEASONS)
    df_f1 = load_league(league="F1", seasons=SEASONS)
    df_raw = pd.concat([df_sp1, df_f1], ignore_index=True)
    df = clean(df_raw)
    print(f"  Total: {len(df)} partidos")

    # 2. Features
    print("\n[2/4] Calculando features...")
    df = odds_features(df)
    df = fatigue(df)
    elo = ELO()
    df = elo.fit(df)
    df = rolling_stats(df)
    print(f"  Partidos con features completos: {len(df.dropna(subset=['Result']))}")

    # 3. Train
    print("\n[3/4] Entrenando modelo...")
    model, scaler = train(df)

    # 4. Predict
    print("\n[4/4] Predicciones de hoy")

    # --- La Liga ---
    print("\n  Buscando partidos de La Liga hoy...")
    fixtures = get_todays_laliga_fixtures()
    if not fixtures and LALIGA_MANUAL_FIXTURES:
        fixtures = LALIGA_MANUAL_FIXTURES
        print(f"  (usando fixtures manuales)")

    if not fixtures:
        print("  Sin partidos detectados. Añade manualmente en LALIGA_MANUAL_FIXTURES.")
    else:
        print(f"  {len(fixtures)} partido(s) detectado(s)")

    print("\n" + "=" * 58)
    print("  LA LIGA")
    print("=" * 58)

    for home, away in fixtures:
        # Get odds from current season data if available
        b365h = b365d = b365a = None
        try:
            resp = requests.get(f"{BASE_URL}/2526/SP1.csv", timeout=10)
            df_curr = pd.read_csv(StringIO(resp.text), on_bad_lines="skip")
            row = df_curr[(df_curr["HomeTeam"] == home) & (df_curr["AwayTeam"] == away)]
            if not row.empty:
                b365h = float(row["B365H"].values[0]) if "B365H" in row else None
                b365d = float(row["B365D"].values[0]) if "B365D" in row else None
                b365a = float(row["B365A"].values[0]) if "B365A" in row else None
        except Exception:
            pass

        pred = predict(home, away, model, scaler, df, elo,
                       b365h=b365h, b365d=b365d, b365a=b365a)
        poly = polymarket_search(home, away)
        print_pred(pred, poly)

    # --- Conference League ---
    print("\n" + "=" * 58)
    print("  CONFERENCE LEAGUE — SEMIFINAL")
    print("=" * 58)

    if RAYO_IS_HOME:
        cl_home, cl_away = "Vallecano", "Strasbourg"
        cl_home_league, cl_away_league = "SP1", "F1"
    else:
        cl_home, cl_away = "Strasbourg", "Vallecano"
        cl_home_league, cl_away_league = "F1", "SP1"

    pred_cl = predict(
        cl_home, cl_away, model, scaler, df, elo,
        home_league=cl_home_league,
        away_league=cl_away_league,
    )
    poly_cl = polymarket_search(cl_home, cl_away)
    print_pred(
        pred_cl, poly_cl,
        note="Cross-league — contexto europeo no capturado, ponderarlo",
    )

    # --- ELO ranking ---
    print("\n" + "=" * 58)
    print("  TOP 10 ELO (ambas ligas)")
    print("=" * 58)
    top = sorted(elo.ratings.items(), key=lambda x: -x[1])[:10]
    for i, (team, rating) in enumerate(top, 1):
        print(f"  {i:2}. {team:<28} {rating:.0f}")


if __name__ == "__main__":
    main()
