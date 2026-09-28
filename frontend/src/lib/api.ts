import { env } from '$env/dynamic/public';

const BASE = env.PUBLIC_API_URL ?? 'http://localhost:8000';

type Fetch = typeof fetch;

export type League = {
  code: string; name: string; flag: string; tier: 1 | 2; season: string;
  played: number; has_xg: boolean; has_fixtures: boolean; has_forecast: boolean; last_match: string | null;
};

export type TableRow = {
  position: number; team: string; pj: number; pts: number; gf: number; ga: number; gd: number;
  form: ('W' | 'D' | 'L')[];
};

export type Rating = { team: string; attack: number; defense: number; xgf: number; xga: number; net: number };

export type Fixture = {
  date: string; home: string; away: string;
  p_home: number; p_draw: number; p_away: number; lambda_home: number; lambda_away: number;
};

export type ForecastRow = {
  team: string; pts_actual: number; pts_esperados: number; gd_esperada: number; posicion_media: number;
  p_campeon: number; p_champions: number; p_descenso: number;
};

export type Forecast = {
  league: string; season: string; sims: number; remaining: number;
  zones: { title: number; europe: number; relegation: number; top_label: string };
  table: ForecastRow[]; positions: Record<string, number[]>;
};

export type FormGame = {
  date: string; opponent: string; home: boolean; gf: number; ga: number;
  result: 'W' | 'D' | 'L'; xgf: number | null; xga: number | null;
};

export type SideRating = { attack: number; defense: number; net: number; rank: number } | null;

export type Prediction = {
  league: string; home: string; away: string; model: string; fitted_on: number;
  known: { home: boolean; away: boolean };
  lambda_home: number; lambda_away: number;
  p_home: number; p_draw: number; p_away: number;
  over15: number; over25: number; over35: number; btts: number; cs_home: number; cs_away: number;
  top_scores: { score: string; prob: number }[];
  score_matrix: number[][];
  ratings: { home: SideRating; away: SideRating };
  form: { home: FormGame[]; away: FormGame[] };
  h2h: { date: string; home: string; away: string; fthg: number; ftag: number }[];
};

export type Inplay = {
  minute: number; score: [number, number]; remaining_share: number;
  lambda_home_left: number; lambda_away_left: number;
  p_home: number; p_draw: number; p_away: number; over25: number;
  top_scores: { score: string; prob: number }[];
};

export type Timeline = { home: string; away: string; score: [number, number]; goals: { side: 'home' | 'away'; minute: number }[] };

export type Scores = { n: number; log_loss: number; brier: number; rps: number; accuracy: number };

export type Backtest = {
  available: boolean; how?: string; model: string; matches: number; from: string; to: string;
  overall: { model: Scores; market: Scores; base: Scores };
  by_league: { league: string; partidos: number; logloss_modelo: number; logloss_mercado: number; logloss_base: number; acierto_modelo: number; acierto_mercado: number }[];
  by_season: { season: string; n: number; model: number; market: number }[];
  reliability: { bin: string; n: number; predicted: number; observed: number }[];
  betting: { edge: number; bets: number; roi: number | null; profit: number | null; clv_positive: number | null; curve: number[] }[];
  bet_everything_roi: number;
};

export type LiveMatch = {
  id: number; home: string; away: string; league: string; status: string; minute: number | null;
  score_home: number; score_away: number;
};

async function get<T>(f: Fetch, path: string): Promise<T> {
  const r = await f(`${BASE}${path}`);
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `HTTP ${r.status}`);
  return r.json();
}

async function post<T>(f: Fetch, path: string, body: unknown): Promise<T> {
  const r = await f(`${BASE}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `HTTP ${r.status}`);
  return r.json();
}

export const api = {
  leagues: (f: Fetch = fetch) => get<League[]>(f, '/api/leagues'),
  table: (code: string, f: Fetch = fetch) => get<TableRow[]>(f, `/api/leagues/${code}/table`),
  ratings: (code: string, f: Fetch = fetch) => get<Rating[]>(f, `/api/leagues/${code}/ratings`),
  teams: (code: string, f: Fetch = fetch) => get<string[]>(f, `/api/leagues/${code}/teams`),
  fixtures: (code: string, limit = 10, f: Fetch = fetch) => get<Fixture[]>(f, `/api/leagues/${code}/fixtures?limit=${limit}`),
  forecast: (code: string, f: Fetch = fetch) => get<Forecast>(f, `/api/leagues/${code}/forecast`),
  predict: (league: string, home: string, away: string, f: Fetch = fetch) =>
    post<Prediction>(f, '/api/predict', { league, home, away }),
  inplay: (league: string, home: string, away: string, score_home: number, score_away: number, minute: number) =>
    post<Inplay>(fetch, '/api/predict/inplay', { league, home, away, score_home, score_away, minute }),
  timeline: (league: string, home: string, away: string, seed?: number) =>
    post<Timeline>(fetch, '/api/simulate/match', { league, home, away, seed }),
  backtest: (f: Fetch = fetch) => get<Backtest>(f, '/api/backtest'),
  live: (f: Fetch = fetch) => get<{ matches: LiveMatch[]; source?: string }>(f, '/api/live'),
};

export const BIG_FIVE = ['E0', 'SP1', 'D1', 'I1', 'F1'];

export function matchHref(league: string, home: string, away: string): string {
  const q = new URLSearchParams({ liga: league, local: home, visitante: away });
  return `/partido?${q}`;
}
