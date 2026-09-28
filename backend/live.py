"""
Live scores from football-data.org (needs FOOTBALL_DATA_KEY; free tier).

Team names are translated to football-data.co.uk spelling, which is what the store and
the model use.
"""

import os
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


def live_matches() -> dict:
    """Live/today's in-play matches with real score and minute from football-data.org."""
    if not FOOTBALL_DATA_KEY:
        return {"matches": [], "source": "no_key", "ts": datetime.now().isoformat()}

    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    today = date.today().isoformat()
    all_live: list[dict] = []

    for comp_code, league_code in COMP_TO_LEAGUE.items():
        try:
            resp = requests.get(
                f"{FOOTBALL_DATA_ORG}/competitions/{comp_code}/matches",
                params={"status": "IN_PLAY,PAUSED,HALFTIME,FINISHED", "dateFrom": today, "dateTo": today},
                headers=headers,
                timeout=8,
            )
            if resp.status_code != 200:
                continue
            for m in resp.json().get("matches", []):
                home_raw = m["homeTeam"]["name"]
                away_raw = m["awayTeam"]["name"]
                home = TEAM_NAME_MAP.get(home_raw, home_raw)
                away = TEAM_NAME_MAP.get(away_raw, away_raw)
                score = m.get("score", {})
                ft = score.get("fullTime", {})
                ht_score = score.get("halfTime", {})
                status_val = m.get("status", "")
                minute = m.get("minute")
                if minute is None and status_val == "HALFTIME":
                    minute = 45
                all_live.append({
                    "id": m["id"],
                    "home": home,
                    "away": away,
                    "league": league_code,
                    "status": status_val,
                    "minute": minute,
                    "score_home": ft.get("home") or 0,
                    "score_away": ft.get("away") or 0,
                    "ht_home": ht_score.get("home"),
                    "ht_away": ht_score.get("away"),
                })
        except Exception:
            continue

    return {"matches": all_live, "ts": datetime.now().isoformat()}
