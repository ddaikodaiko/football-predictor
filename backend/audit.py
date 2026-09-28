"""
Data audit: everything that looks wrong in the store, league by league.

    python audit.py

Each check prints what it found; nothing is changed. The point is to catch silent
problems (a team under two names, a mis-parsed date, xG attached to the wrong match)
before they quietly bend the model.
"""

import sys

import numpy as np
import pandas as pd

import store
from ingest import LEAGUES


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 70 - len(title)))


def main() -> int:
    conn = store.connect()
    m = store.load_matches(conn)
    problems = 0

    section("Partidos por temporada (esperado: n·(n−1) con n equipos)")
    for (lg, season), g in m.groupby(["league", "season"]):
        teams = set(g["home"]) | set(g["away"])
        expected = len(teams) * (len(teams) - 1)
        if len(g) != expected and season != m["season"].max():
            print(f"  {lg} {season}: {len(g)} partidos, {len(teams)} equipos (esperados {expected})")
            problems += 1

    section("Duplicados (mismo partido dos veces en una temporada)")
    dup = m[m.duplicated(["league", "season", "home", "away"], keep=False)]
    for r in dup.sort_values(["league", "season", "home"]).itertuples():
        print(f"  {r.league} {r.season} {r.date.date()} {r.home} {r.fthg}-{r.ftag} {r.away}")
    problems += len(dup)

    section("Fechas fuera de su temporada")
    start = pd.to_datetime("20" + m["season"].str[:2] + "-07-01")
    # Up to mid-August of the next year: 2019/20 finished in August because of COVID.
    bad = m[(m["date"] < start) | (m["date"] > start + pd.Timedelta(days=412))]
    for r in bad.head(20).itertuples():
        print(f"  {r.league} {r.season} {r.date.date()} {r.home}-{r.away}")
    problems += len(bad)

    section("Marcadores raros (más de 9 goles de un equipo, o descanso > final)")
    odd = m[(m["fthg"] > 9) | (m["ftag"] > 9) | (m["hthg"] > m["fthg"]) | (m["htag"] > m["ftag"])]
    for r in odd.itertuples():
        print(f"  {r.league} {r.season} {r.date.date()} {r.home} {r.fthg}-{r.ftag} {r.away} (desc. {r.hthg}-{r.htag})")
    problems += len(odd)

    section("Equipos con nombres parecidos en la misma liga (¿el mismo con dos nombres?)")
    from difflib import SequenceMatcher
    for lg, g in m.groupby("league"):
        seasons_of = g.groupby("home")["season"].agg(set)
        names = sorted(seasons_of.index)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.8 and not (seasons_of[a] & seasons_of[b]):
                    print(f"  {lg}: '{a}' ({min(seasons_of[a])}-{max(seasons_of[a])}) / '{b}' ({min(seasons_of[b])}-{max(seasons_of[b])})")
                    problems += 1

    section("Márgenes de las casas fuera de lo normal (1X2 media: <0 % o >15 %)")
    for col in ("avg", "b365", "pin", "close"):
        o = m[[f"{col}_h", f"{col}_d", f"{col}_a"]].to_numpy(float)
        ok = np.all(o > 1, axis=1)
        margin = (1 / o[ok]).sum(axis=1) - 1
        weird = (margin < 0) | (margin > 0.15)
        print(f"  {col:5s}: {ok.sum():6d} con cuota, margen mediano {np.median(margin):.1%}, {weird.sum()} raros")
        problems += int(weird.sum())
        for r in m[ok].iloc[np.nonzero(weird)[0][:5]].itertuples():
            print(f"      {r.league} {r.season} {r.home}-{r.away}: {getattr(r, col + '_h')} {getattr(r, col + '_d')} {getattr(r, col + '_a')}")

    section("xG: coherencia con los goles (correlación por temporada, esperado > 0,5)")
    x = m.dropna(subset=["xg_home", "xg_away"])
    for (lg, season), g in x.groupby(["league", "season"]):
        corr = np.corrcoef(np.r_[g["xg_home"], g["xg_away"]], np.r_[g["fthg"], g["ftag"]])[0, 1]
        ratio = (g["fthg"].sum() + g["ftag"].sum()) / (g["xg_home"].sum() + g["xg_away"].sum())
        if corr < 0.5 or not 0.85 < ratio < 1.15:
            print(f"  {lg} {season}: correlación {corr:.2f}, goles/xG {ratio:.2f} ({len(g)} partidos, fuente {g['xg_source'].mode().iat[0]})")
            problems += 1

    section("Tiros a puerta mayores que tiros")
    st = m[(m["hst"] > m["hs"]) | (m["ast"] > m["as_"])]
    print(f"  {len(st)} partidos")
    problems += len(st)

    section("Calendario pendiente que ya aparece como jugado")
    fx = store.load_fixtures(conn)
    played = set(zip(m["league"], m["season"], m["home"], m["away"]))
    stale = [f for f in fx.itertuples() if (f.league, f.season, f.home, f.away) in played]
    for f in stale[:10]:
        print(f"  {f.league} {f.date.date()} {f.home}-{f.away}")
    problems += len(stale)

    print(f"\n{problems} cosas a revisar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
