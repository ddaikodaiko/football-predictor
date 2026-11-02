import { env } from '$env/dynamic/public';
import { base } from '$app/paths';
import * as dcm from './dixoncoles';
import type { PropsParams } from './props';

const BASE = env.PUBLIC_API_URL ?? 'http://localhost:8000';
/** Serverless demo: data from static JSON (backend/export_static.py), maths in the browser. */
export const STATIC = env.PUBLIC_STATIC === '1';

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
  props: PropsParams | null;
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
  /** the goals + xG model on the same matches: how much the prices add */
  reference: Scores | null;
};

export type TrackSummary = { n: number; model: number; market: number; diff_se: number | null; from: string; to: string };
export type Track = TrackSummary & {
  n_all: number;
  by_version: (TrackSummary & { version: string })[];
  matches: {
    date: string; league: string; home: string; away: string; fthg: number; ftag: number; outcome: 0 | 1 | 2;
    p_home: number; p_draw: number; p_away: number; m_home: number | null; m_draw: number | null; m_away: number | null;
    ll_model: number; ll_market: number | null; model_version: string; created_at: string;
  }[];
};

export type ValuePick = {
  event_id: string; league: string; kickoff: string; home: string; away: string;
  market: 'h2h' | 'totals' | 'spreads'; outcome: string; point: number;
  bookmaker: string; price: number; fair_p: number; ev: number; reference: string; model_p: number | null;
};

export type ClvSummary = { n: number; ev_close: number; t: number; beat_close: number } | null;

export type Clv = {
  n: number; all?: ClvSummary; final?: ClvSummary;
  picks: (ValuePick & { seen_at: string; fair_close: number; ev_close: number; final: boolean })[];
};

export type OddsPoint = {
  at: string; reference: string | null; books: number;
  fair: { home: number; draw: number; away: number } | null;
  best: Record<'home' | 'draw' | 'away', number>; best_book: Record<'home' | 'draw' | 'away', string>;
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

// ── static mode ──────────────────────────────────────────────────────────────

type Bundle = {
  code: string; model?: string; teams: string[]; rho: number; fitted_on: number; known: Record<string, boolean>;
  ratings: Record<string, NonNullable<SideRating>>; pairs: Record<string, [number, number]>;
  form: Record<string, FormGame[]>; h2h: Record<string, Prediction['h2h']>;
  // corners and shots on target: per pairing [corners home, corners away, sot home, sot away]
  props?: { first_half: number; alpha: Record<'corners' | 'sot', { home: number; away: number }>;
            pairs: Record<string, [number, number, number, number]> };
};
const bundles = new Map<string, Promise<Bundle>>();

async function file<T>(f: Fetch, path: string): Promise<T> {
  const r = await f(`${base}/data/${path}`);
  if (!r.ok) throw new Error(`Sin datos (${path})`);
  return r.json();
}

function bundle(league: string, f: Fetch = fetch): Promise<Bundle> {
  if (!bundles.has(league)) bundles.set(league, file<Bundle>(f, `${league}/bundle.json`));
  return bundles.get(league)!;
}

async function pairing(league: string, home: string, away: string, f: Fetch = fetch) {
  const b = await bundle(league, f);
  const pair = b.pairs[`${home}|${away}`];
  if (!pair) throw new Error(`${home} y ${away} no juegan juntos en ${league} esta temporada`);
  return { b, lh: pair[0], la: pair[1] };
}

async function staticPredict(league: string, home: string, away: string, f: Fetch): Promise<Prediction> {
  const { b, lh, la } = await pairing(league, home, away, f);
  const m = dcm.scoreMatrix(lh, la, b.rho);
  const key = home < away ? `${home}|${away}` : `${away}|${home}`;
  return {
    league, home, away, model: b.model ?? 'desconocido', fitted_on: b.fitted_on,
    known: { home: b.known[home] ?? false, away: b.known[away] ?? false },
    lambda_home: lh, lambda_away: la, ...dcm.markets(m),
    score_matrix: m.slice(0, 6).map((row) => row.slice(0, 6)),
    ratings: { home: b.ratings[home] ?? null, away: b.ratings[away] ?? null },
    form: { home: b.form[home] ?? [], away: b.form[away] ?? [] },
    h2h: b.h2h[key] ?? [],
    props: staticProps(b, `${home}|${away}`),
  };
}

function staticProps(b: Bundle, pair: string): PropsParams | null {
  const v = b.props?.pairs[pair];
  if (!b.props || !v) return null;
  const { alpha, first_half } = b.props;
  return {
    corners: { home: v[0], away: v[1], alpha_home: alpha.corners.home, alpha_away: alpha.corners.away },
    sot: { home: v[2], away: v[3], alpha_home: alpha.sot.home, alpha_away: alpha.sot.away },
    first_half,
  };
}

const live = {
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
  track: (f: Fetch = fetch) => get<Track>(f, '/api/track'),
};

const offline: typeof live = {
  leagues: (f = fetch) => file<League[]>(f, 'leagues.json'),
  table: (code, f = fetch) => file<TableRow[]>(f, `${code}/table.json`),
  ratings: (code, f = fetch) => file<Rating[]>(f, `${code}/ratings.json`),
  teams: async (code, f = fetch) => (await bundle(code, f)).teams,
  fixtures: async (code, limit = 10, f = fetch) => (await file<Fixture[]>(f, `${code}/fixtures.json`)).slice(0, limit),
  forecast: (code, f = fetch) => file<Forecast>(f, `${code}/forecast.json`),
  predict: (league, home, away, f = fetch) => staticPredict(league, home, away, f),
  inplay: async (league, home, away, sh, sa, minute) => {
    const { b, lh, la } = await pairing(league, home, away);
    return dcm.inplay(lh, la, b.rho, sh, sa, minute);
  },
  timeline: async (league, home, away, seed) => {
    const { b, lh, la } = await pairing(league, home, away);
    return { home, away, ...dcm.timeline(lh, la, b.rho, seed) };
  },
  backtest: (f = fetch) => file<Backtest>(f, 'backtest.json'),
  track: (f = fetch) => file<Track>(f, 'track.json'),
};

const core = STATIC ? offline : live;

export const api = {
  ...core,
  value: (minEv = 0.02, f: Fetch = fetch) =>
    get<{ picks: ValuePick[]; snapshot: string | null; credits_left: number | null }>(f, `/api/value?min_ev=${minEv}`),
  clv: (f: Fetch = fetch) => get<Clv>(f, '/api/value/clv'),
  oddsHistory: (league: string, home: string, away: string, f: Fetch = fetch) =>
    STATIC ? Promise.resolve({ points: [] as OddsPoint[], kickoff: null })
      : get<{ points: OddsPoint[]; kickoff: string | null }>(
        f, `/api/odds/history?${new URLSearchParams({ league, home, away })}`),
  live: (f: Fetch = fetch) => get<{ matches: LiveMatch[]; source?: string }>(f, '/api/live'),
};

export const BIG_FIVE = ['E0', 'SP1', 'D1', 'I1', 'F1'];

export function matchHref(league: string, home: string, away: string): string {
  const q = new URLSearchParams({ liga: league, local: home, visitante: away });
  return `${base}/partido?${q}`;
}
