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

import market
import odds_live
import props
import store
from backtest import (COMPANION, OUT_DIR as BACKTEST_DIR, PRODUCTION_FILE as BACKTEST_FILE, REFERENCE_FILE,
                      market_probs, outcome_index, report, scores)
from ingest import LEAGUES, UNDERSTAT_LEAGUES, season_code
from ratings import DixonColes, markets, outcome_probs, score_matrix
from simulate import (GOAL_INTENSITY, ZONES, ZONE_LABELS, DEFAULT_ZONES, betting_backtest, simulate_season,
                      simulate_timeline, standings)

MODEL_VERSION = "dc-market-mxi0.03-sd10-joint"
# Ratings fitted on what the market priced each past match (market.py), with a ~3-week
# half-life and an almost free prior. Backtest: 0.9705 log loss against 0.9785 for the
# goals + xG fit it replaces, and goals or xG on top add nothing (ROADMAP.md).
MODEL = {"xg_weight": 0.0, "market_weight": 1.0, "market_xi": 0.03, "prior_sd": 10.0}
FLAGS = {"E": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "SP": "🇪🇸", "D": "🇩🇪", "I": "🇮🇹", "F": "🇫🇷", "N": "🇳🇱", "P": "🇵🇹"}


class UnknownLeague(KeyError):
    pass


class Engine:
    def __init__(self, db_path=None):
        self.conn = store.connect(db_path)
        self.conn.executescript(odds_live.SCHEMA)
        self._write = threading.Lock()
        self.reload()

    def reload(self) -> None:
        """Re-read the store (after an ingest) and drop every cache."""
        self.matches = market.add_market_lambdas(store.load_matches(self.conn))
        self.season = season_code(datetime.now(timezone.utc).date())
        self.all_fixtures = store.load_fixtures(self.conn, season=self.season)
        # Filtering 95k rows costs ~20 ms and pages ask for it hundreds of times: split once.
        self._by_league = {code: df for code, df in self.matches.groupby("league")}
        self._teams: dict[str, list[str]] = {}
        self._value_cache: dict = {}
        self._models: dict[str, DixonColes] = {}
        self._count_models: dict[tuple[str, str], DixonColes] = {}
        self.props_weights = props.load_weights()
        self._forecasts: dict[tuple[str, int], dict] = {}
        self.__dict__.pop("backtest", None)

    # ── leagues ────────────────────────────────────────────────────────────────

    def _league(self, league: str) -> pd.DataFrame:
        if league not in LEAGUES:
            raise UnknownLeague(league)
        return self._by_league.get(league, self.matches.iloc[0:0])

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
                "has_forecast": len(current) > 0,
                "last_match": current["date"].max().strftime("%Y-%m-%d") if len(current) else None,
            })
        return out

    def fixtures(self, league: str) -> pd.DataFrame:
        return self.all_fixtures[self.all_fixtures["league"] == league]

    def remaining(self, league: str) -> pd.DataFrame:
        """Matches left this season. The published calendar when there is one; otherwise
        every home/away pairing not played yet, which is exactly the rest of a double
        round-robin (checked against the real calendars of SP1, E0, N1 and E1: identical).
        No dates then, which the season simulator doesn't need."""
        published = self.fixtures(league)
        if not published.empty:
            return published
        cur = self.current(league)
        teams = sorted(set(cur["home"]) | set(cur["away"]))
        played = set(zip(cur["home"], cur["away"]))
        pairs = [(h, a) for h in teams for a in teams if h != a and (h, a) not in played]
        return pd.DataFrame(pairs, columns=["home", "away"]).assign(date=pd.NaT)

    def model(self, league: str) -> DixonColes:
        if league not in self._models:
            # First divisions are fitted with their second (backtest.py --joint), so promoted
            # teams arrive with a real rating.
            fit_on = self._league(league)
            if league in COMPANION:
                fit_on = self.matches[self.matches["league"].isin([league, COMPANION[league]])]
            self._models[league] = DixonColes(**MODEL).fit(fit_on, primary=league)
        return self._models[league]

    def count_model(self, league: str, stat: str) -> DixonColes:
        """Ratings on corners or shots on target (see props.py)."""
        if (league, stat) not in self._count_models:
            self._count_models[league, stat] = props.count_model(self._league(league), stat)
        return self._count_models[league, stat]

    def props(self, league: str, home: str, away: str, lambdas: tuple[float, float]) -> dict | None:
        """Expected corners and shots on target per team. None until props.py has fitted
        the weights, or in a league without those counts."""
        if self.props_weights is None:
            return None
        try:
            ratings = {s: self.count_model(league, s).lambdas(home, away) for s in props.STATS}
        except ValueError:
            return None
        first = float(GOAL_INTENSITY[:3].sum() / GOAL_INTENSITY.sum())
        return {**_round(props.predict(self.props_weights, lambdas, ratings)), "first_half": round(first, 4)}

    def current(self, league: str) -> pd.DataFrame:
        lg = self._league(league)
        return lg[lg["season"] == self.season]

    def teams(self, league: str) -> list[str]:
        if league not in self._teams:
            cur = self.current(league)
            teams = set(cur["home"]) | set(cur["away"])
            fixtures = self.fixtures(league)
            teams |= set(fixtures["home"]) | set(fixtures["away"])
            self._teams[league] = sorted(teams)
        return self._teams[league]

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
        lg = self._league(league)
        games = lg[((lg["home"] == home) & (lg["away"] == away)) | ((lg["home"] == away) & (lg["away"] == home))]
        return [{"date": g.date.strftime("%Y-%m-%d"), "home": g.home, "away": g.away,
                 "fthg": int(g.fthg), "ftag": int(g.ftag)} for g in games.tail(n).itertuples(index=False)][::-1]

    def predict(self, league: str, home: str, away: str, neutral: bool = False) -> dict:
        dc = self.model(league)
        lh, la = dc.lambdas(home, away, neutral)
        m = score_matrix(lh, la, dc.rho)
        ratings = dc.ratings()
        ratings = ratings[ratings["team"].isin(self.teams(league))].set_index("team")
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
            "props": self.props(league, home, away, (lh, la)),
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
            remaining = self.remaining(league)
            if self.current(league).empty:
                raise LookupError(f"{league}: la temporada aún no ha empezado")
            f = simulate_season(self.model(league), self.current(league), remaining, sims, seed=0,
                                zones=ZONES.get(league, DEFAULT_ZONES))
            title, europe, relegated = ZONES.get(league, DEFAULT_ZONES)
            self._forecasts[key] = {
                "league": league, "season": self.season, "sims": f.n_sims, "remaining": f.remaining,
                "zones": {"title": title, "europe": europe, "relegation": relegated,
                          "top_label": ZONE_LABELS.get(league, "Champions")},
                "table": f.table.round(4).to_dict(orient="records"),
                "positions": {team: [round(float(p), 4) for p in row]
                              for team, row in f.positions.iterrows()},
            }
        return self._forecasts[key]

    # ── live value (odds_live.py) ──────────────────────────────────────────────

    def value(self, min_ev: float = 0.02) -> dict:
        """Prices above the sharp fair probability in the latest snapshot, with the
        model's own probability alongside where it has one (1X2 and over/under 2.5)."""
        stamp = self.conn.execute("SELECT MAX(rowid) FROM odds_snapshots").fetchone()[0]
        if stamp is None:
            return {"picks": [], "snapshot": None}
        key = (stamp, min_ev)
        if self._value_cache.get("key") == key:
            return self._value_cache["value"]
        snap = odds_live.latest(self.conn)
        picks = odds_live.find_value(snap, min_ev)
        rows = []
        cache: dict[tuple, dict] = {}
        for p in picks.to_dict(orient="records"):
            model_p = None
            if p["league"] in LEAGUES and p["home"] in self.teams(p["league"]) and p["away"] in self.teams(p["league"]):
                match = (p["league"], p["home"], p["away"])
                if match not in cache:
                    dc = self.model(p["league"])
                    cache[match] = markets(dc.score_matrix(p["home"], p["away"]))
                pred = cache[match]
                if p["market"] == "h2h":
                    model_p = pred[{"home": "p_home", "draw": "p_draw", "away": "p_away"}[p["outcome"]]]
                elif p["market"] == "totals" and p["point"] == 2.5:
                    model_p = pred["over25"] if p["outcome"] == "over" else 1 - pred["over25"]
            rows.append({**p, "model_p": model_p})
        usage = self.conn.execute("SELECT at, remaining FROM odds_api_usage ORDER BY rowid DESC LIMIT 1").fetchone()
        value = _round({"picks": rows, "snapshot": snap["fetched_at"].max(),
                        "credits_left": usage[1] if usage else None})
        self._value_cache = {"key": key, "value": value}
        return value

    def odds_history(self, league: str, home: str, away: str) -> dict:
        """1X2 odds of one match over time, from every stored snapshot: the sharp fair
        probability (Pinnacle without margin) and the best price on offer per outcome."""
        snaps = pd.read_sql_query(
            "SELECT fetched_at, kickoff, bookmaker, outcome, price FROM odds_snapshots"
            " WHERE league = ? AND home = ? AND away = ? AND market = 'h2h'",
            self.conn, params=[league, home, away])
        if snaps.empty:
            return {"points": [], "kickoff": None}
        points = []
        for at, g in snaps.groupby("fetched_at"):
            fair = odds_live.fair_probabilities(g)
            best = g.groupby("outcome")["price"].max()
            books = g.loc[g.groupby("outcome")["price"].idxmax()].set_index("outcome")["bookmaker"]
            points.append({"at": at, "reference": fair[1] if fair else None,
                           "fair": fair[0] if fair else None,
                           "best": best.to_dict(), "best_book": books.to_dict(),
                           "books": int(g["bookmaker"].nunique())})
        return _round({"points": points, "kickoff": snaps["kickoff"].iat[0]})

    def clv(self) -> dict:
        scored = odds_live.score_picks(self.conn)
        if scored.empty:
            return {"n": 0, "picks": []}
        final = scored[scored["final"]]
        summary = lambda df: None if len(df) < 2 else {
            "n": len(df), "ev_close": float(df["ev_close"].mean()),
            "t": float(df["ev_close"].mean() / (df["ev_close"].std(ddof=1) / np.sqrt(len(df)))),
            "beat_close": float((df["ev_close"] > 0).mean())}
        return _round({"n": len(scored), "all": summary(scored), "final": summary(final),
                       "picks": scored.sort_values("kickoff", ascending=False).head(100).to_dict(orient="records")})

    def track(self) -> dict:
        """The model measured live: the last prediction stored before each match day
        (upcoming() stores them), scored once the result is in, next to the bookmakers'
        price for the same match. Unlike the backtest, nobody can redo these afterwards."""
        pred = pd.read_sql_query("SELECT * FROM predictions", self.conn)
        # Made on an earlier day than the match: kick-off times aren't stored, so a
        # prediction from the match day itself might have been made after the start.
        pred = pred[pred["created_at"].str[:10] < pred["date"]]
        pred = pred.sort_values("created_at").drop_duplicates(["league", "date", "home", "away"], keep="last")
        odds = [c for c in self.matches.columns if c.split("_")[0] in {"b365", "avg", "pin", "close"}]
        played = self.matches[["league", "date", "home", "away", "fthg", "ftag", *odds]].assign(
            date=self.matches["date"].dt.strftime("%Y-%m-%d"))
        j = pred.merge(played, on=["league", "date", "home", "away"]).dropna(subset=["fthg", "ftag"])
        if j.empty:
            return {"n": 0, "by_version": [], "matches": []}
        y = outcome_index(j)
        model_p = j[["p_home", "p_draw", "p_away"]].to_numpy()
        market_p, _ = market_probs(j)
        ok = ~np.isnan(market_p).any(axis=1)
        j = j.assign(outcome=y, ll_model=-np.log(model_p[np.arange(len(j)), y]),
                     ll_market=np.where(ok, -np.log(np.where(ok[:, None], market_p, 1.0)[np.arange(len(j)), y]), np.nan),
                     m_home=market_p[:, 0], m_draw=market_p[:, 1], m_away=market_p[:, 2])
        def summary(df: pd.DataFrame) -> dict:
            # Standard error of the paired difference: with a few dozen matches, a gap of
            # several hundredths either way is still luck.
            diff = df["ll_model"] - df["ll_market"]
            return {"n": len(df), "model": float(df["ll_model"].mean()), "market": float(df["ll_market"].mean()),
                    "diff_se": float(diff.std(ddof=1) / np.sqrt(len(df))) if len(df) > 1 else None,
                    "from": df["date"].min(), "to": df["date"].max()}

        cols = ["date", "league", "home", "away", "fthg", "ftag", "outcome", "p_home", "p_draw", "p_away",
                "m_home", "m_draw", "m_away", "ll_model", "ll_market", "model_version", "created_at"]
        return _round({
            **summary(j[ok]), "n_all": len(j),
            "by_version": [{"version": v, **summary(g)} for v, g in j[ok].groupby("model_version")],
            "matches": j.sort_values(["date", "league", "home"], ascending=[False, True, True])[cols]
                        .to_dict(orient="records"),
        })

    # ── backtest ───────────────────────────────────────────────────────────────

    @cached_property
    def backtest(self) -> dict:
        """Summary of backtest.py's output. Takes ~9 s (the betting replays), so it's
        cached next to the predictions and rebuilt only when they change."""
        path = BACKTEST_DIR / BACKTEST_FILE
        if not path.exists():
            return {"available": False, "how": "python backtest.py --joint --xg 0 --market 1 --market-xi 0.03 --prior 10 --name dc_market"}
        cache = path.with_suffix(".summary.json")
        if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
            return json.loads(cache.read_text())
        summary = self._summarise_backtest(path)
        cache.write_text(json.dumps(summary))
        return summary

    def _summarise_backtest(self, path) -> dict:
        pred = pd.read_csv(path, parse_dates=["date"], dtype={"season": str})
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

        # The goals + xG model, scored on the same matches: how much the prices add.
        reference = None
        if (BACKTEST_DIR / REFERENCE_FILE).exists():
            ref = pd.read_csv(BACKTEST_DIR / REFERENCE_FILE, parse_dates=["date"], dtype={"season": str})
            ref = pred[["date", "home", "away"]].merge(ref, on=["date", "home", "away"], how="left")
            ref_p = ref[["p_home", "p_draw", "p_away"]].to_numpy()
            both = ok & ~np.isnan(ref_p).any(axis=1)
            if both.sum() == ok.sum():
                reference = scores(ref_p[ok], y[ok])

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
            "reference": reference,
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
