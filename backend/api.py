"""
FastAPI backend. Reads the local store (fill it with `python ingest.py`), so it starts
in about a second; all the maths lives in engine.py.

    uvicorn api:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import live  # noqa: E402
from engine import Engine, UnknownLeague  # noqa: E402

engine: Engine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    engine = Engine()
    yield


app = FastAPI(title="Football Predictor API", version="2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _engine() -> Engine:
    if engine is None:
        raise HTTPException(503, "arrancando")
    return engine


def _league(code: str) -> str:
    e = _engine()
    try:
        e._league(code)
    except UnknownLeague:
        raise HTTPException(404, f"liga desconocida: {code}")
    return code


def _team(league: str, team: str) -> str:
    if team not in _engine().teams(league):
        raise HTTPException(404, f"{team} no juega en {league} esta temporada")
    return team


# ─── schemas ───────────────────────────────────────────────────────────────────

class MatchRequest(BaseModel):
    league: str
    home: str
    away: str
    neutral: bool = False


class InplayRequest(BaseModel):
    league: str
    home: str
    away: str
    score_home: int = Field(0, ge=0, le=20)
    score_away: int = Field(0, ge=0, le=20)
    minute: int = Field(0, ge=0, le=90)


class TimelineRequest(BaseModel):
    league: str
    home: str
    away: str
    seed: int | None = None


# ─── routes ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    e = _engine()
    return {"ready": True, "season": e.season, "matches": len(e.matches),
            "leagues": len(e.leagues()), "live_scores": bool(live.FOOTBALL_DATA_KEY)}


@app.get("/api/leagues")
def leagues():
    return _engine().leagues()


@app.get("/api/leagues/{code}/table")
def table(code: str):
    return _engine().table(_league(code))


@app.get("/api/leagues/{code}/ratings")
def ratings(code: str):
    return _engine().ratings(_league(code))


@app.get("/api/leagues/{code}/teams")
def teams(code: str):
    return _engine().teams(_league(code))


@app.get("/api/leagues/{code}/fixtures")
def fixtures(code: str, limit: int = Query(10, ge=1, le=100)):
    return _engine().upcoming(_league(code), limit)


@app.get("/api/leagues/{code}/forecast")
def forecast(code: str, sims: int = Query(10_000, ge=500, le=50_000)):
    try:
        return _engine().forecast(_league(code), sims)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/predict")
def predict(req: MatchRequest):
    league = _league(req.league)
    return _engine().predict(league, _team(league, req.home), _team(league, req.away), req.neutral)


@app.post("/api/predict/inplay")
def predict_inplay(req: InplayRequest):
    league = _league(req.league)
    return _engine().inplay(league, _team(league, req.home), _team(league, req.away),
                            req.score_home, req.score_away, req.minute)


@app.post("/api/simulate/match")
def simulate_match(req: TimelineRequest):
    league = _league(req.league)
    return _engine().timeline(league, _team(league, req.home), _team(league, req.away), req.seed)


@app.get("/api/backtest")
def backtest():
    return _engine().backtest


@app.get("/api/track")
def track():
    """Predictions stored before each match, scored against the result and the market."""
    return _engine().track()


@app.get("/api/value")
def value(min_ev: float = Query(0.02, ge=0, le=0.5)):
    return _engine().value(min_ev)


@app.get("/api/odds/history")
def odds_history(league: str, home: str, away: str):
    return _engine().odds_history(_league(league), home, away)


@app.get("/api/value/clv")
def value_clv():
    return _engine().clv()


@app.get("/api/live")
def live_matches():
    e = _engine()
    return live.live_matches({code: e.teams(code) for code in live.COMP_TO_LEAGUE.values()})


@app.post("/api/reload")
def reload():
    """Re-read the store after running ingest.py, without restarting the server."""
    _engine().reload()
    return status()
