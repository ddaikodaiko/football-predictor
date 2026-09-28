"""
Live scores from football-data.org (needs FOOTBALL_DATA_KEY; free tier).

Team names are translated to football-data.co.uk spelling, which is what the store and
the model use.
"""

import os
import time
from datetime import date, datetime

import requests

FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_KEY", "")
FOOTBALL_DATA_ORG = "https://api.football-data.org/v4"

# football-data.org competition codes -> our league codes (football-data.co.uk codes)
COMP_TO_LEAGUE = {"PD": "SP1", "PL": "E0", "FL1": "F1", "BL1": "D1", "SA": "I1"}

# Map football-data.org team names -> football-data.co.uk names
TEAM_NAME_MAP: dict[str, str] = {
    "FC Barcelona": "Barcelona",
    "Real Madrid CF": "Real Madrid",
    "Club Atlético de Madrid": "Ath Madrid",
    "Athletic Club": "Ath Bilbao",
    "Real Sociedad de Fútbol": "Sociedad",
    "Real Betis Balompié": "Betis",
    "Sevilla FC": "Sevilla",
    "Villarreal CF": "Villarreal",
    "Valencia CF": "Valencia",
    "Celta de Vigo": "Celta",
    "CA Osasuna": "Osasuna",
    "RCD Mallorca": "Mallorca",
    "Getafe CF": "Getafe",
    "Girona FC": "Girona",
    "Deportivo Alavés": "Alaves",
    "Rayo Vallecano de Madrid": "Vallecano",
    "UD Las Palmas": "Las Palmas",
    "Real Valladolid CF": "Valladolid",
    "RCD Espanyol de Barcelona": "Espanol",
    "Espanyol": "Espanol",
    "CD Leganés": "Leganes",
    "UD Almería": "Almeria",
    "Cádiz CF": "Cadiz",
    "Elche CF": "Elche",
    "Levante UD": "Levante",
    "Real Oviedo": "Oviedo",
    "Arsenal FC": "Arsenal",
    "Chelsea FC": "Chelsea",
    "Liverpool FC": "Liverpool",
    "Manchester City FC": "Man City",
    "Manchester United FC": "Man United",
    "Tottenham Hotspur FC": "Tottenham",
    "Newcastle United FC": "Newcastle",
    "West Ham United FC": "West Ham",
    "Aston Villa FC": "Aston Villa",
    "Brighton & Hove Albion FC": "Brighton",
    "Crystal Palace FC": "Crystal Palace",
    "Brentford FC": "Brentford",
    "Everton FC": "Everton",
    "Fulham FC": "Fulham",
    "Wolverhampton Wanderers FC": "Wolves",
    "Nottingham Forest FC": "Nott'm Forest",
    "Leicester City FC": "Leicester",
    "Ipswich Town FC": "Ipswich",
    "Southampton FC": "Southampton",
    "AFC Bournemouth": "Bournemouth",
    "Bournemouth": "Bournemouth",
    "Paris Saint-Germain FC": "Paris SG",
    "Olympique de Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon",
    "AS Monaco FC": "Monaco",
    "Stade Rennais FC 1901": "Rennes",
    "RC Lens": "Lens",
    "OGC Nice": "Nice",
    "Lille OSC": "Lille",
    "Stade de Reims": "Reims",
    "RC Strasbourg Alsace": "Strasbourg",
    "FC Nantes": "Nantes",
    "Toulouse FC": "Toulouse",
    "Montpellier HSC": "Montpellier",
    "Le Havre AC": "Le Havre",
    "Angers SCO": "Angers",
    "Stade Brestois 29": "Brest",
    "AJ Auxerre": "Auxerre",
    "AS Saint-Étienne": "St Etienne",
    # Bundesliga
    "FC Bayern München": "Bayern Munich",
    "Borussia Dortmund": "Dortmund",
    "Bayer 04 Leverkusen": "Leverkusen",
    "RB Leipzig": "RB Leipzig",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "VfB Stuttgart": "Stuttgart",
    "SC Freiburg": "Freiburg",
    "Borussia Mönchengladbach": "Monchengladbach",
    "1. FC Union Berlin": "Union Berlin",
    "FC Augsburg": "Augsburg",
    "VfL Wolfsburg": "Wolfsburg",
    "1. FSV Mainz 05": "Mainz",
    "TSG Hoffenheim": "Hoffenheim",
    "SV Werder Bremen": "Werder Bremen",
    "VfL Bochum 1848": "Bochum",
    "1. FC Heidenheim 1846": "Heidenheim",
    "FC St. Pauli 1910": "St Pauli",
    "Holstein Kiel": "Holstein Kiel",
    # Serie A
    "Juventus FC": "Juventus",
    "FC Internazionale Milano": "Inter",
    "SSC Napoli": "Napoli",
    "AC Milan": "AC Milan",
    "AS Roma": "Roma",
    "SS Lazio": "Lazio",
    "ACF Fiorentina": "Fiorentina",
    "Atalanta BC": "Atalanta",
    "Torino FC": "Torino",
    "Bologna FC 1909": "Bologna",
    "Udinese Calcio": "Udinese",
    "Genoa CFC": "Genoa",
    "Cagliari Calcio": "Cagliari",
    "Hellas Verona FC": "Verona",
    "Empoli FC": "Empoli",
    "US Lecce": "Lecce",
    "Frosinone Calcio": "Frosinone",
    "US Salernitana 1919": "Salernitana",
    "AC Monza": "Monza",
    "Parma Calcio 1913": "Parma",
    "Como 1907": "Como",
    "Venezia FC": "Venezia",
}


_cache: dict = {"at": 0.0, "value": None}
STARTED = {"IN_PLAY", "LIVE", "PAUSED", "HALFTIME", "FINISHED"}
CACHE_S = 30  # free tier allows 10 requests/minute; the page polls every 60 s


_teams_cache: dict = {}


def competition_names(comp: str) -> list[str]:
    """Team names of one competition on football-data.org, cached for a day."""
    hit = _teams_cache.get(comp)
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    try:
        resp = requests.get(f"{FOOTBALL_DATA_ORG}/competitions/{comp}/teams",
                            headers={"X-Auth-Token": FOOTBALL_DATA_KEY}, timeout=10)
        resp.raise_for_status()
        names = [t["name"] for t in resp.json().get("teams", [])]
    except (requests.RequestException, ValueError):
        return hit[1] if hit else []
    _teams_cache[comp] = (time.time(), names)
    return names


def name_map(theirs: list[str], ours: list[str]) -> dict[str, str]:
    """football-data.org names -> ours, one to one. The hand-written TEAM_NAME_MAP counts
    as an exact match; the rest by name similarity, solved as an assignment so the hard
    ones ('Borussia Mönchengladbach' / "M'gladbach") fall into place by elimination.
    It missed 21 of 96 teams in 2026/27 with the hand map alone."""
    from odds_live import _similar
    from scipy.optimize import linear_sum_assignment
    import numpy as np

    if not theirs or not ours:
        return {}
    sim = np.array([[1.0 if TEAM_NAME_MAP.get(t) == o else _similar(t, o) for o in ours] for t in theirs])
    rows, cols = linear_sum_assignment(-sim)
    return {theirs[i]: ours[j] for i, j in zip(rows, cols) if sim[i, j] >= 0.3}


def live_matches(teams_by_league: dict[str, list[str]] | None = None) -> dict:
    """Today's matches of the big five with score and minute, from football-data.org.

    One request for all five competitions (the per-competition loop took ~9 s), cached
    for 30 s so several open tabs don't burn the free quota.
    """
    if not FOOTBALL_DATA_KEY:
        return {"matches": [], "source": "no_key", "ts": datetime.now().isoformat()}
    if _cache["value"] is not None and time.time() - _cache["at"] < CACHE_S:
        return _cache["value"]

    today = date.today().isoformat()
    try:
        resp = requests.get(
            f"{FOOTBALL_DATA_ORG}/matches",
            # No `status` filter: the API rejects HALFTIME in it (400), which silently broke
            # the old per-competition version. Filtered below instead.
            params={"competitions": ",".join(COMP_TO_LEAGUE), "dateFrom": today, "dateTo": today},
            headers={"X-Auth-Token": FOOTBALL_DATA_KEY}, timeout=8,
        )
        resp.raise_for_status()
        raw = resp.json().get("matches", [])
    except (requests.RequestException, ValueError):
        return {"matches": [], "source": "error", "ts": datetime.now().isoformat()}

    maps = {}
    if teams_by_league:
        maps = {league: name_map(competition_names(comp), teams_by_league.get(league, []))
                for comp, league in COMP_TO_LEAGUE.items()}
    matches = []
    for m in raw:
        league = COMP_TO_LEAGUE.get(m.get("competition", {}).get("code", ""))
        status = m.get("status", "")
        if league is None or status not in STARTED:
            continue
        ft = m.get("score", {}).get("fullTime", {})
        minute = m.get("minute")
        if minute is None and status in ("HALFTIME", "PAUSED"):
            minute = 45
        matches.append({
            "id": m["id"], "league": league, "status": status, "minute": minute,
            "home": maps.get(league, {}).get(m["homeTeam"]["name"], TEAM_NAME_MAP.get(m["homeTeam"]["name"], m["homeTeam"]["name"])),
            "away": maps.get(league, {}).get(m["awayTeam"]["name"], TEAM_NAME_MAP.get(m["awayTeam"]["name"], m["awayTeam"]["name"])),
            "score_home": ft.get("home") or 0, "score_away": ft.get("away") or 0,
        })
    value = {"matches": matches, "ts": datetime.now().isoformat()}
    _cache.update(at=time.time(), value=value)
    return value
