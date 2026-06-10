"""
FastAPI backend — exposes the prediction model as REST API.
Startup: downloads data, trains model (~60s first run).
"""

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from model import FootballPredictor, polymarket_search

try:
    import anthropic as _anthropic
    _ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    _claude: "_anthropic.Anthropic | None" = _anthropic.Anthropic(api_key=_ANTHROPIC_KEY) if _ANTHROPIC_KEY else None
except ImportError:
    _claude = None

predictor = FootballPredictor()

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

LEAGUE_FLAG = {"SP1": "🇪🇸", "E0": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "F1": "🇫🇷", "D1": "🇩🇪", "I1": "🇮🇹"}
LEAGUE_NAME = {"SP1": "La Liga", "E0": "Premier League", "F1": "Ligue 1", "D1": "Bundesliga", "I1": "Serie A"}
ALL_LEAGUES = ["SP1", "F1", "E0", "D1", "I1"]


_cached_upcoming: list[dict] = []


def _fetch_upcoming_sync(days_ahead: int = 7) -> list[dict]:
    """Fetch and cache upcoming fixtures from football-data.org (blocking)."""
    if not FOOTBALL_DATA_KEY:
        return []
    date_from = date.today().isoformat()
    date_to = (date.today() + timedelta(days=days_ahead)).isoformat()
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    all_matches: dict[str, list] = {}
    for comp_code, league_code in COMP_TO_LEAGUE.items():
        try:
            resp = requests.get(
                f"{FOOTBALL_DATA_ORG}/competitions/{comp_code}/matches",
                params={"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to},
                headers=headers, timeout=10,
            )
            if resp.status_code != 200:
                continue
            for m in resp.json().get("matches", []):
                match_date = m["utcDate"][:10]
                home = TEAM_NAME_MAP.get(m["homeTeam"]["name"], m["homeTeam"]["name"])
                away = TEAM_NAME_MAP.get(m["awayTeam"]["name"], m["awayTeam"]["name"])
                all_matches.setdefault(match_date, []).append({
                    "home": home, "away": away,
                    "home_league": league_code, "away_league": league_code,
                })
        except Exception:
            continue
    matchdays = []
    for match_date in sorted(all_matches.keys()):
        matches = all_matches[match_date]
        leagues_in_day = sorted({m["home_league"] for m in matches})
        label_parts = [f"{LEAGUE_FLAG.get(lg, '')} {LEAGUE_NAME.get(lg, lg)}" for lg in leagues_in_day]
        matchdays.append({
            "id": f"live_{match_date}",
            "label": f"{' · '.join(label_parts)} — {match_date}",
            "date": match_date,
            "matches": matches,
            "live": True,
        })
    return matchdays


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cached_upcoming
    print("⚽ Training model on startup...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: predictor.train(ALL_LEAGUES))
    print("✓ Model ready")
    if FOOTBALL_DATA_KEY:
        print("📅 Pre-fetching upcoming fixtures...")
        _cached_upcoming = await loop.run_in_executor(None, _fetch_upcoming_sync)
        print(f"✓ Cached {len(_cached_upcoming)} matchdays")
    yield


app = FastAPI(title="Football Predictor API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── SCHEMAS ───────────────────────────────────────────────────────────────────

class PredictRequest(BaseModel):
    home: str
    away: str
    home_league: str = "SP1"
    away_league: str = "SP1"
    b365h: Optional[float] = None
    b365d: Optional[float] = None
    b365a: Optional[float] = None


class InplayRequest(BaseModel):
    home: str
    away: str
    home_league: str = "SP1"
    away_league: str = "SP1"
    score_home: int = 0
    score_away: int = 0
    minute: int = 1


# ─── ROUTES ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    return {
        "ready": predictor.model is not None,
        "meta": predictor.meta,
    }


@app.post("/api/predict")
def predict(req: PredictRequest):
    if predictor.model is None:
        raise HTTPException(503, "Model not ready yet")

    result = predictor.predict_match(
        home=req.home, away=req.away,
        home_league=req.home_league, away_league=req.away_league,
        b365h=req.b365h, b365d=req.b365d, b365a=req.b365a,
    )
    result["polymarket"] = polymarket_search(req.home, req.away)
    result["analysis"] = _interpret(result)
    result["claude_analysis"] = _claude_analysis(result)
    return result


@app.post("/api/predict/inplay")
def predict_inplay(req: InplayRequest):
    """In-play prediction: re-simulate from current score + minute."""
    if predictor.model is None:
        raise HTTPException(503, "Model not ready yet")

    # Get base prediction (ML probs + team stats)
    base = predictor.predict_match(
        home=req.home, away=req.away,
        home_league=req.home_league, away_league=req.away_league,
    )
    # Replace simulation with in-play conditional simulation
    inplay_sim = predictor.simulate_inplay(
        home_team=req.home,
        away_team=req.away,
        score_home=req.score_home,
        score_away=req.score_away,
        minute=req.minute,
    )
    base["inplay_simulation"] = inplay_sim
    base["inplay_score"] = {"home": req.score_home, "away": req.score_away}
    base["inplay_minute"] = req.minute
    return base


@app.get("/api/elo")
def elo_ranking(n: int = 20):
    if predictor.elo is None:
        raise HTTPException(503, "Model not ready yet")
    return {"ranking": predictor.elo_ranking(n)}


@app.post("/api/predict/batch")
def predict_batch(matches: list[PredictRequest]):
    if predictor.model is None:
        raise HTTPException(503, "Model not ready yet")
    results = []
    for req in matches:
        try:
            result = predictor.predict_match(
                home=req.home, away=req.away,
                home_league=req.home_league, away_league=req.away_league,
                b365h=req.b365h, b365d=req.b365d, b365a=req.b365a,
            )
            result["polymarket"] = polymarket_search(req.home, req.away)
            result["analysis"] = _interpret(result)
            result["claude_analysis"] = _claude_analysis(result)
            result["error"] = None
        except Exception as e:
            result = {"home": req.home, "away": req.away, "error": str(e)}
        results.append(result)
    return results


@app.get("/api/feature-importance")
def feature_importance_endpoint(n: int = 15):
    if predictor.model is None:
        raise HTTPException(503, "Model not ready yet")
    return {"features": predictor.feature_importance(n)}


@app.get("/api/teams")
def teams():
    if predictor.df is None:
        raise HTTPException(503, "Model not ready yet")
    result = {}
    for league in ALL_LEAGUES:
        result[league] = sorted(
            predictor.df[predictor.df["League"] == league]["HomeTeam"].dropna().unique().tolist()
        )
    return result


@app.get("/api/matchdays")
def matchdays():
    """Predefined matchday fixtures."""
    return {
        "matchdays": [
            {
                "id": "uecl_sf_may7",
                "label": "🏆 Conference League — Semis (Hoy)",
                "date": "2026-05-07",
                "matches": [
                    {"home": "Strasbourg", "away": "Vallecano", "home_league": "F1", "away_league": "SP1"},
                    {"home": "Crystal Palace", "away": "Shakhtar", "home_league": "E0", "away_league": "E0"},
                ],
            },
            {
                "id": "laliga_j35_may8",
                "label": "🇪🇸 La Liga J35 — Viernes",
                "date": "2026-05-08",
                "matches": [
                    {"home": "Levante", "away": "Osasuna", "home_league": "SP1", "away_league": "SP1"},
                ],
            },
            {
                "id": "laliga_j35_may9",
                "label": "🇪🇸 La Liga J35 — Sábado",
                "date": "2026-05-09",
                "matches": [
                    {"home": "Elche", "away": "Alaves", "home_league": "SP1", "away_league": "SP1"},
                    {"home": "Sevilla", "away": "Espanol", "home_league": "SP1", "away_league": "SP1"},
                    {"home": "Ath Madrid", "away": "Celta", "home_league": "SP1", "away_league": "SP1"},
                    {"home": "Sociedad", "away": "Betis", "home_league": "SP1", "away_league": "SP1"},
                ],
            },
            {
                "id": "laliga_j35_may10",
                "label": "🇪🇸 La Liga J35 — Domingo",
                "date": "2026-05-10",
                "matches": [
                    {"home": "Mallorca", "away": "Villarreal", "home_league": "SP1", "away_league": "SP1"},
                    {"home": "Ath Bilbao", "away": "Valencia", "home_league": "SP1", "away_league": "SP1"},
                    {"home": "Oviedo", "away": "Getafe", "home_league": "SP1", "away_league": "SP1"},
                    {"home": "Barcelona", "away": "Real Madrid", "home_league": "SP1", "away_league": "SP1"},
                ],
            },
        ]
    }


@app.get("/api/live")
def live_matches():
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


@app.get("/api/matchdays/upcoming")
def upcoming_matchdays(
    days_ahead: int = Query(default=7, ge=1, le=30),
    refresh: bool = Query(default=False),
):
    """
    Upcoming fixtures from football-data.org.
    Returns cached data from startup; pass refresh=true to re-fetch.
    """
    global _cached_upcoming
    if not FOOTBALL_DATA_KEY:
        return {"matchdays": [], "error": "FOOTBALL_DATA_KEY not configured"}
    if refresh or not _cached_upcoming:
        _cached_upcoming = _fetch_upcoming_sync(days_ahead)
    return {"matchdays": _cached_upcoming}


# ─── CLAUDE ANALYSIS ───────────────────────────────────────────────────────────

def _claude_analysis(pred: dict) -> str | None:
    """Generate a natural language match analysis via Claude API. Returns None if key not set."""
    if _claude is None:
        return None
    try:
        home, away = pred["home"], pred["away"]
        hs, as_ = pred["home_stats"], pred["away_stats"]
        bk = pred.get("bookmaker", {})
        poly = pred.get("polymarket")
        sim = pred.get("simulation", {})

        bk_line = ""
        if bk.get("p_home") is not None:
            bk_line = f"\nBet365: {home} {bk['p_home']:.1%} | Empate {bk['p_draw']:.1%} | {away} {bk['p_away']:.1%}"

        poly_line = ""
        if poly and poly.get("prices") and len(poly["prices"]) >= 2:
            poly_line = f"\nPolymarket: precios {poly['prices'][:3]} (liquidez ${poly.get('liquidity', 0):,.0f})"

        top_scores = ", ".join(s["score"] for s in sim.get("top_scores", [])[:3])

        prompt = f"""Eres un analista experto de fútbol. Analiza este partido de forma concisa.

**{home}** vs **{away}**

Probabilidades modelo ML (ensemble LR+RF+XGBoost):
- {home}: {pred['p_home']:.1%} | Empate: {pred['p_draw']:.1%} | {away}: {pred['p_away']:.1%}{bk_line}{poly_line}

Estadísticas recientes:
- {home}: {hs['avg_GF']:.2f} goles/j anotados, {hs['avg_GA']:.2f} encajados, {hs['avg_Pts']:.1f} pts/j, ELO {pred['elo_home']}
- {away}: {as_['avg_GF']:.2f} goles/j anotados, {as_['avg_GA']:.2f} encajados, {as_['avg_Pts']:.1f} pts/j, ELO {pred['elo_away']}

Simulación Poisson: Over2.5={sim.get('over25', 0):.0%}, BTTS={sim.get('btts', 0):.0%}, marcadores probables: {top_scores}

Proporciona en máximo 100 palabras:
1. Factores clave que determinan el partido
2. Predicción con confianza (alta/media/baja)
3. Si hay divergencia notable entre ML/bookmaker/Polymarket, menciona el posible edge

Sé directo y específico, sin relleno."""

        msg = _claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return None


# ─── INTERPRETATION ────────────────────────────────────────────────────────────

def _interpret(pred: dict) -> dict:
    p_home = pred["p_home"]
    p_draw = pred["p_draw"]
    p_away = pred["p_away"]

    best = max([("1", p_home), ("X", p_draw), ("2", p_away)], key=lambda x: x[1])
    confidence = "alta" if best[1] > 0.55 else ("media" if best[1] > 0.44 else "baja")

    elo_diff = pred["elo_home"] - pred["elo_away"]
    elo_favors = pred["home"] if elo_diff > 30 else (pred["away"] if elo_diff < -30 else "ninguno")

    factors = []

    h_pts = pred["home_stats"]["avg_Pts"]
    a_pts = pred["away_stats"]["avg_Pts"]
    if h_pts > a_pts + 0.5:
        factors.append(f"{pred['home']} llega con mejor forma reciente ({h_pts:.1f} pts/partido vs {a_pts:.1f})")
    elif a_pts > h_pts + 0.5:
        factors.append(f"{pred['away']} llega con mejor forma reciente ({a_pts:.1f} pts/partido vs {h_pts:.1f})")

    if pred["home_stats"]["avg_GF"] > pred["away_stats"]["avg_GF"] + 0.4:
        factors.append(f"Ataque local superior: {pred['home_stats']['avg_GF']:.1f} vs {pred['away_stats']['avg_GF']:.1f} goles/partido")
    if pred["away_stats"]["avg_GA"] > pred["home_stats"]["avg_GA"] + 0.4:
        factors.append(f"Defensa local más sólida: {pred['home_stats']['avg_GA']:.1f} vs {pred['away_stats']['avg_GA']:.1f} goles encajados")

    if abs(elo_diff) > 50:
        factors.append(f"ELO favorece a {elo_favors} ({abs(elo_diff):.0f} puntos de diferencia)")

    # H2H
    h2h = pred.get("h2h", {})
    if h2h.get("h2h_home_win_pct") is not None:
        hwp = h2h["h2h_home_win_pct"]
        awp = h2h["h2h_away_win_pct"]
        if hwp >= 0.6:
            factors.append(f"H2H favorable para {pred['home']}: {hwp:.0%} victorias en los últimos enfrentamientos")
        elif awp >= 0.6:
            factors.append(f"H2H favorable para {pred['away']}: {awp:.0%} victorias en los últimos enfrentamientos")

    # Simulation market props
    sim = pred.get("simulation", {})
    if sim:
        if sim.get("over25", 0) > 0.65:
            factors.append(f"Partido con tendencia goleadora: {sim['over25']:.0%} de prob. Over 2.5")
        elif sim.get("over25", 0) < 0.40:
            factors.append(f"Partido con tendencia cerrada: {sim['over25']:.0%} de prob. Over 2.5")
        if sim.get("btts", 0) > 0.65:
            factors.append(f"Alta probabilidad de que ambos marquen ({sim['btts']:.0%})")

    bk = pred.get("bookmaker", {})
    if bk.get("p_home") is not None:
        div_home = abs(p_home - bk["p_home"])
        div_away = abs(p_away - bk["p_away"])
        max_div = max(div_home, div_away)
        if max_div > 0.08:
            factors.append(f"Divergencia modelo vs casas ({max_div:.0%}) — posible valor en el mercado")

    poly = pred.get("polymarket")
    if poly and len(poly.get("prices", [])) >= 2:
        poly_home = poly["prices"][0]
        div = abs(p_home - poly_home)
        if div > 0.08:
            factors.append(f"Divergencia modelo vs Polymarket ({div:.0%})")

    if pred.get("cross_league"):
        factors.append("Partido cross-league: el modelo no captura contexto europeo ni dinámica de eliminatoria")

    value_bets = []
    if bk.get("p_home") is not None:
        for outcome, ml_p_val, bk_p_val in [
            ("1", p_home, bk["p_home"]),
            ("X", p_draw, bk["p_draw"]),
            ("2", p_away, bk["p_away"]),
        ]:
            edge = ml_p_val - bk_p_val
            if edge > 0.07:
                value_bets.append({
                    "outcome": outcome,
                    "edge": round(edge, 3),
                    "ml_p": round(ml_p_val, 3),
                    "bk_p": round(bk_p_val, 3),
                })

    return {
        "verdict": best[0],
        "confidence": confidence,
        "confidence_pct": round(best[1], 4),
        "elo_favors": elo_favors,
        "elo_diff": elo_diff,
        "key_factors": factors,
        "value_bets": value_bets,
        "has_value": len(value_bets) > 0,
    }
