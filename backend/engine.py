"""
Everything the API serves, computed from the local store. No network here.

Models are fitted lazily per league (~0.02 s each) and cached until the data changes;
season forecasts are cached per league too, since 10,000 seasons take ~2 s.
"""

import json
import threading
from datetime import datetime, timezone
from functools import cached_property

import numpy as np
import pandas as pd

import store
from backtest import OUT_DIR as BACKTEST_DIR, market_probs, outcome_index, report, scores
from ingest import LEAGUES, UNDERSTAT_LEAGUES, season_code
from ratings import DixonColes, markets, outcome_probs, score_matrix
from simulate import (GOAL_INTENSITY, ZONES, DEFAULT_ZONES, betting_backtest, simulate_season,
                      simulate_timeline, standings)

MODEL_VERSION = "dc-xg0.5-xi0.003"
XG_WEIGHT = 0.5
BACKTEST_FILE = "dc_xg0.5_xi0.003.csv.gz"
FLAGS = {"E": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "SP": "🇪🇸", "D": "🇩🇪", "I": "🇮🇹", "F": "🇫🇷", "N": "🇳🇱", "P": "🇵🇹"}


class UnknownLeague(KeyError):
    pass


class Engine:
    def __init__(self, db_path=None):
        self.conn = store.connect(db_path)
        self._write = threading.Lock()
        self.reload()

    def reload(self) -> None:
        """Re-read the store (after an ingest) and drop every cache."""
        self.matches = store.load_matches(self.conn)
        self.season = season_code(datetime.now(timezone.utc).date())
        self.all_fixtures = store.load_fixtures(self.conn, season=self.season)
        self._models: dict[str, DixonColes] = {}
        self._forecasts: dict[tuple[str, int], dict] = {}
        self.__dict__.pop("backtest", None)

    # ── leagues ────────────────────────────────────────────────────────────────

    def _league(self, league: str) -> pd.DataFrame:
        if league not in LEAGUES:
            raise UnknownLeague(league)
        return self.matches[self.matches["league"] == league]

    def leagues(self) -> list[dict]:
        out = []
        for code, name in LEAGUES.items():
            lg = self._league(code)
            current = lg[lg["season"] == self.season]
            out.append({
                "code": code, "name": name, "flag": FLAGS[code.rstrip("0123456789")],
                "tier": 1 if code.endswith("1") or code == "E0" else 2,
                "season": self.season, "played": len(current),
                "has_xg": code in UNDERSTAT_LEAGUES,
                "has_fixtures": not self.fixtures(code).empty,
                "last_match": current["date"].max().strftime("%Y-%m-%d") if len(current) else None,
            })
        return out

    def fixtures(self, league: str) -> pd.DataFrame:
        return self.all_fixtures[self.all_fixtures["league"] == league]

    def model(self, league: str) -> DixonColes:
        if league not in self._models:
            self._models[league] = DixonColes(xg_weight=XG_WEIGHT).fit(self._league(league))
        return self._models[league]

    def current(self, league: str) -> pd.DataFrame:
        lg = self._league(league)
        return lg[lg["season"] == self.season]

    def teams(self, league: str) -> list[str]:
        cur = self.current(league)
        teams = set(cur["home"]) | set(cur["away"])
        fixtures = self.fixtures(league)
        teams |= set(fixtures["home"]) | set(fixtures["away"])
        return sorted(teams)

    def table(self, league: str) -> list[dict]:
        t = standings(self.current(league))
        t["position"] = np.arange(1, len(t) + 1)
        t["form"] = [self.form(league, team, 5, only_results=True) for team in t["team"]]
        return t.to_dict(orient="records")

    def ratings(self, league: str) -> list[dict]:
        r = self.model(league).ratings()
        current = set(self.teams(league))
        r = r[r["team"].isin(current)] if current else r
        return r.round(4).to_dict(orient="records")

    # ── one team / one match ───────────────────────────────────────────────────

    def form(self, league: str, team: str, n: int = 5, only_results: bool = False):
        lg = self._league(league)
        games = lg[(lg["home"] == team) | (lg["away"] == team)].tail(n)
        rows = []
        for g in games.itertuples(index=False):
            home = g.home == team
            gf, ga = (g.fthg, g.ftag) if home else (g.ftag, g.fthg)
            res = "W" if gf > ga else "D" if gf == ga else "L"
            if only_results:
                rows.append(res)
                continue
            xgf, xga = (g.xg_home, g.xg_away) if home else (g.xg_away, g.xg_home)
            rows.append({"date": g.date.strftime("%Y-%m-%d"), "opponent": g.away if home else g.home,
                         "home": bool(home), "gf": int(gf), "ga": int(ga), "result": res,
                         "xgf": _num(xgf), "xga": _num(xga)})
        return rows

    def h2h(self, league: str, home: str, away: str, n: int = 6) -> list[dict]:
        lg = self.matches
        games = lg[((lg["home"] == home) & (lg["away"] == away)) | ((lg["home"] == away) & (lg["away"] == home))]
        return [{"date": g.date.strftime("%Y-%m-%d"), "home": g.home, "away": g.away,
                 "fthg": int(g.fthg), "ftag": int(g.ftag)} for g in games.tail(n).itertuples(index=False)][::-1]

    def predict(self, league: str, home: str, away: str, neutral: bool = False) -> dict:
        dc = self.model(league)
        lh, la = dc.lambdas(home, away, neutral)
        m = score_matrix(lh, la, dc.rho)
        ratings = dc.ratings().set_index("team")
        side = lambda t: ({"attack": round(float(ratings.at[t, "attack"]), 3),
                           "defense": round(float(ratings.at[t, "defense"]), 3),
                           "net": round(float(ratings.at[t, "net"]), 3),
                           "rank": int(ratings.index.get_loc(t)) + 1}
                          if t in ratings.index else None)
        return {
            "league": league, "home": home, "away": away, "neutral": neutral,
            "model": MODEL_VERSION, "fitted_on": dc.n_matches,
            "known": {"home": dc.knows(home), "away": dc.knows(away)},
            "lambda_home": round(lh, 3), "lambda_away": round(la, 3),
            **_round(markets(m)),
            "score_matrix": np.round(m[:6, :6], 4).tolist(),
            "ratings": {"home": side(home), "away": side(away)},
            "form": {"home": self.form(league, home), "away": self.form(league, away)},
            "h2h": self.h2h(league, home, away),
        }

    def inplay(self, league: str, home: str, away: str, score_home: int, score_away: int, minute: int) -> dict:
        """Final-score odds from the current state: the remaining expected goals are the
        full-match λ times the share of the goal-intensity profile still to be played."""
        dc = self.model(league)
        lh, la = dc.lambdas(home, away)
        minute = int(np.clip(minute, 0, 90))
        profile = np.repeat(GOAL_INTENSITY, 15)
        left = profile[minute:].sum() / profile.sum()
        m = score_matrix(lh * left, la * left, dc.rho * left)
        i, j = np.indices(m.shape)
        fh, fa = score_home + i, score_away + j
        top = np.argsort(-m, axis=None)[:5]
        return {
            "minute": minute, "score": [score_home, score_away], "remaining_share": round(float(left), 3),
            "lambda_home_left": round(lh * left, 3), "lambda_away_left": round(la * left, 3),
            "p_home": round(float(m[fh > fa].sum()), 4), "p_draw": round(float(m[fh == fa].sum()), 4),
            "p_away": round(float(m[fh < fa].sum()), 4),
            "over25": round(float(m[fh + fa > 2.5].sum()), 4),
            "top_scores": [{"score": f"{fh.flat[k]}-{fa.flat[k]}", "prob": round(float(m.flat[k]), 4)} for k in top],
        }

    def timeline(self, league: str, home: str, away: str, seed: int | None = None) -> dict:
        dc = self.model(league)
        return {"home": home, "away": away, **simulate_timeline(*dc.lambdas(home, away), dc.rho, seed)}

    # ── fixtures and season ────────────────────────────────────────────────────

    def upcoming(self, league: str, limit: int = 10) -> list[dict]:
        """Next fixtures with the model's odds. Each prediction is stored the first time
        it's made, so the model can be scored live once the matches are played."""
        fixtures = self.fixtures(league)
        if fixtures.empty:
            return []
        today = pd.Timestamp(datetime.now(timezone.utc).date())
        # The next `limit` fixtures, however far: international breaks leave two-week gaps.
        soon = fixtures[fixtures["date"] >= today - pd.Timedelta(days=1)].head(limit)
        dc = self.model(league)
        out, now = [], datetime.now(timezone.utc).isoformat(timespec="seconds")
        for f in soon.itertuples(index=False):
            lh, la = dc.lambdas(f.home, f.away)
            ph, pd_, pa = outcome_probs(score_matrix(lh, la, dc.rho))
            row = {"date": f.date.strftime("%Y-%m-%d"), "home": f.home, "away": f.away,
                   "p_home": round(ph, 4), "p_draw": round(pd_, 4), "p_away": round(pa, 4),
                   "lambda_home": round(lh, 3), "lambda_away": round(la, 3)}
            out.append(row)
        with self._write, self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO predictions (created_at, model_version, league, date, home, away,"
                " p_home, p_draw, p_away, lambda_home, lambda_away) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(now, MODEL_VERSION, league, r["date"], r["home"], r["away"], r["p_home"], r["p_draw"],
                  r["p_away"], r["lambda_home"], r["lambda_away"]) for r in out])
        return out

    def forecast(self, league: str, sims: int = 10_000) -> dict:
        key = (league, sims)
        if key not in self._forecasts:
            remaining = self.fixtures(league)
            if remaining.empty:
                raise LookupError(f"sin calendario pendiente para {league}")
            f = simulate_season(self.model(league), self.current(league), remaining, sims, seed=0,
                                zones=ZONES.get(league, DEFAULT_ZONES))
            title, europe, relegated = ZONES.get(league, DEFAULT_ZONES)
            self._forecasts[key] = {
                "league": league, "season": self.season, "sims": f.n_sims, "remaining": f.remaining,
                "zones": {"title": title, "europe": europe, "relegation": relegated},
                "table": f.table.round(4).to_dict(orient="records"),
                "positions": {team: [round(float(p), 4) for p in row]
                              for team, row in f.positions.iterrows()},
            }
        return self._forecasts[key]

    # ── backtest ───────────────────────────────────────────────────────────────

    @cached_property
    def backtest(self) -> dict:
        """Summary of backtest.py's output. Takes ~9 s (the betting replays), so it's
        cached next to the predictions and rebuilt only when they change."""
        path = BACKTEST_DIR / BACKTEST_FILE
        if not path.exists():
            return {"available": False, "how": "python backtest.py --xg 0.5"}
        cache = path.with_suffix(".summary.json")
        if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
            return json.loads(cache.read_text())
        summary = self._summarise_backtest(path)
        cache.write_text(json.dumps(summary))
        return summary

    def _summarise_backtest(self, path) -> dict:
        pred = pd.read_csv(path, parse_dates=["date"])
        y = outcome_index(pred)
        model_p = pred[["p_home", "p_draw", "p_away"]].to_numpy()
        market_p, _ = market_probs(pred)
        ok = ~np.isnan(market_p).any(axis=1)
        base = np.tile(np.bincount(y[ok], minlength=3) / ok.sum(), (ok.sum(), 1))

        # Reliability: every (match, outcome) pair binned by the model's probability.
        p_flat, y_flat = model_p.ravel(), (np.eye(3)[y]).ravel()
        bins = np.linspace(0, 1, 11)
        which = np.clip(np.digitize(p_flat, bins) - 1, 0, 9)
        reliability = [{"bin": f"{bins[b]:.1f}-{bins[b + 1]:.1f}", "n": int((which == b).sum()),
                        "predicted": float(p_flat[which == b].mean()), "observed": float(y_flat[which == b].mean())}
                       for b in range(10) if (which == b).sum() >= 50]

        seasons = []
        for season, idx in pred.groupby("season").indices.items():
            idx = idx[ok[idx]]
            seasons.append({"season": season, "n": len(idx),
                            "model": scores(model_p[idx], y[idx])["log_loss"],
                            "market": scores(market_p[idx], y[idx])["log_loss"]})

        betting = []
        for edge in (0.02, 0.05, 0.10, 0.20):
            r = betting_backtest(pred, edge=edge)
            curve = r["log"]["bankroll"].iloc[:: max(len(r["log"]) // 200, 1)].round(1).tolist() if r["bets"] else []
            betting.append({"edge": edge, "bets": r["bets"], "roi": r.get("roi"), "profit": r.get("profit"),
                            "clv_positive": r.get("clv_positive"), "curve": curve})
        everything = betting_backtest(pred, edge=-1.0)

        return _round({
            "available": True, "model": MODEL_VERSION, "matches": int(ok.sum()),
            "from": pred["season"].min(), "to": pred["season"].max(),
            "overall": {"model": scores(model_p[ok], y[ok]), "market": scores(market_p[ok], y[ok]),
                        "base": scores(base, y[ok])},
            "by_league": report(pred).to_dict(orient="records"),
            "by_season": seasons,
            "reliability": reliability,
            "betting": betting,
            "bet_everything_roi": everything["roi"],
        })


# ─── helpers ───────────────────────────────────────────────────────────────────

def _num(x) -> float | None:
    return None if x is None or pd.isna(x) else round(float(x), 2)


def _round(obj, nd: int = 4):
    if isinstance(obj, dict):
        return {k: _round(v, nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v, nd) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return None if np.isnan(obj) else round(float(obj), nd)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj
