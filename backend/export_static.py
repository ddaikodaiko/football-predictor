"""
Export everything the web needs as static JSON, for a serverless demo (GitHub Pages).

    python export_static.py            # -> frontend/static/data/

What can't be precomputed stays in the browser: the frontend computes score matrices,
markets, the in-play odds and the minute-by-minute simulation from each pairing's expected
goals (see frontend/src/lib/dixoncoles.ts), with the same maths as ratings.py.
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine import Engine, _round
from ingest import LEAGUES

OUT = Path(__file__).resolve().parent.parent / "frontend" / "static" / "data"


def write(name: str, obj) -> int:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
    path.write_text(text)
    return len(text)


def league_bundle(e: Engine, code: str) -> dict:
    """Per league: every pairing's expected goals, plus form and head-to-head, so the
    match page works for any two teams without a server."""
    teams = e.teams(code)
    dc = e.model(code)
    ratings = dc.ratings()
    ratings = ratings[ratings["team"].isin(teams)].reset_index(drop=True)
    rank = {t: i + 1 for i, t in enumerate(ratings["team"])}
    pairs = {}
    h2h = {}
    for h in teams:
        for a in teams:
            if h == a:
                continue
            pairs[f"{h}|{a}"] = [round(x, 4) for x in dc.lambdas(h, a)]
            games = e.h2h(code, h, a)
            if games and h < a:
                h2h[f"{h}|{a}"] = games
    return {
        "code": code, "teams": teams, "rho": round(dc.rho, 4), "fitted_on": dc.n_matches,
        "known": {t: dc.knows(t) for t in teams},
        "ratings": {r.team: {"attack": round(r.attack, 3), "defense": round(r.defense, 3),
                             "net": round(r.net, 3), "rank": rank[r.team]} for r in ratings.itertuples()},
        "pairs": pairs, "form": {t: e.form(code, t) for t in teams}, "h2h": h2h,
    }


def main() -> int:
    e = Engine()
    if OUT.exists():
        shutil.rmtree(OUT)
    sizes = {}
    leagues = e.leagues()
    sizes["leagues.json"] = write("leagues.json", leagues)
    for lg in leagues:
        code = lg["code"]
        sizes[f"{code}/table.json"] = write(f"{code}/table.json", e.table(code))
        sizes[f"{code}/ratings.json"] = write(f"{code}/ratings.json", e.ratings(code))
        sizes[f"{code}/fixtures.json"] = write(f"{code}/fixtures.json", e.upcoming(code, 20))
        if lg["has_forecast"]:
            sizes[f"{code}/forecast.json"] = write(f"{code}/forecast.json", e.forecast(code))
        sizes[f"{code}/bundle.json"] = write(f"{code}/bundle.json", _round(league_bundle(e, code)))
        print(f"{code:4s} listo", flush=True)
    sizes["backtest.json"] = write("backtest.json", e.backtest)
    # Live odds (value.json, clv.json) are NOT exported: The Odds API data is for personal
    # use, so the public demo leaves the Valor page to the local version.
    sizes["meta.json"] = write("meta.json", {"exported_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                                             "model": "dc-xg0.5-xi0.003-joint"})
    total = sum(sizes.values())
    print(f"\n{len(sizes)} ficheros, {total / 1e6:.1f} MB en {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
