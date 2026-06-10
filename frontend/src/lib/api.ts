const BASE = 'http://localhost:8000';

export type MatchStats = {
  avg_GF: number; avg_GA: number; avg_SoT: number; avg_Pts: number;
  avg_GF_h?: number | null; avg_GA_h?: number | null;
  avg_GF_a?: number | null; avg_GA_a?: number | null;
  avg_shots?: number | null;
  avg_corners?: number | null;
  form?: string[];
  streak?: number;
};

export type H2H = {
  h2h_home_win_pct: number; h2h_draw_pct: number; h2h_away_win_pct: number;
  h2h_avg_goals_home: number; h2h_avg_goals_away: number;
};

export type Bookmaker = {
  p_home: number | null; p_draw: number | null; p_away: number | null;
};

export type Polymarket = {
  question: string; prices: number[]; outcomes: string[];
  liquidity: number; volume_24h: number;
} | null;

export type SimScore = { score: string; prob: number };

export type HtFtEntry = { combo: string; label: string; prob: number };

export type Simulation = {
  lambda_home: number; lambda_away: number;
  p_home: number; p_draw: number; p_away: number;
  over25: number; over15: number; over35: number; btts: number;
  cs_home: number; cs_away: number;
  dnb_home: number; dnb_away: number;
  ah_plus_half_home: number; ah_plus_half_away: number;
  htft: Record<string, number>;
  htft_top: HtFtEntry[];
  top_scores: SimScore[];
} | null;

export type InplaySimulation = {
  lambda_home_remaining: number; lambda_away_remaining: number;
  lambda_home_full: number; lambda_away_full: number;
  p_home: number; p_draw: number; p_away: number;
  over25: number; over15: number; over35: number; btts: number;
  cs_home: number; cs_away: number;
  dnb_home: number; dnb_away: number;
  top_scores: SimScore[];
  current_score: string; minute: number; remaining_minutes: number;
};

export type ValueBet = { outcome: string; edge: number; ml_p: number; bk_p: number };

export type Analysis = {
  verdict: string; confidence: string; confidence_pct: number;
  elo_favors: string; elo_diff: number; key_factors: string[];
  value_bets: ValueBet[];
  has_value: boolean;
};

export type Prediction = {
  home: string; away: string;
  home_league: string; away_league: string;
  p_home: number; p_draw: number; p_away: number;
  elo_home: number; elo_away: number; elo_exp_home: number;
  home_stats: MatchStats; away_stats: MatchStats;
  h2h: H2H;
  bookmaker: Bookmaker; polymarket: Polymarket;
  simulation: Simulation;
  analysis: Analysis;
  claude_analysis?: string | null;
  cross_league: boolean; error?: string | null;
  inplay_simulation?: InplaySimulation | null;
  inplay_score?: { home: number; away: number } | null;
  inplay_minute?: number | null;
};

export type EloEntry = { team: string; elo: number };

export type StatusResponse = {
  ready: boolean;
  meta: {
    total_matches: number; train_matches: number; test_matches: number;
    accuracy: number; log_loss: number; leagues: string[]; seasons: string[];
    features: number;
  };
};

export type MatchFixture = {
  home: string; away: string;
  home_league: string; away_league: string;
  b365h?: number; b365d?: number; b365a?: number;
};

export type Matchday = {
  id: string; label: string; date: string;
  matches: MatchFixture[];
  live?: boolean;
};

export type FeatureImportanceEntry = { feature: string; importance: number };

export type LiveMatch = {
  id: number;
  home: string;
  away: string;
  league: string;
  status: 'IN_PLAY' | 'HALFTIME' | 'PAUSED' | 'FINISHED' | string;
  minute: number | null;
  score_home: number;
  score_away: number;
  ht_home: number | null;
  ht_away: number | null;
};

export async function getStatus(): Promise<StatusResponse> {
  const r = await fetch(`${BASE}/api/status`);
  return r.json();
}

export async function predictMatch(params: MatchFixture): Promise<Prediction> {
  const r = await fetch(`${BASE}/api/predict`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function predictBatch(matches: MatchFixture[]): Promise<Prediction[]> {
  const r = await fetch(`${BASE}/api/predict/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(matches),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function getMatchdays(): Promise<Matchday[]> {
  const r = await fetch(`${BASE}/api/matchdays`);
  const data = await r.json();
  return data.matchdays;
}

export async function getUpcomingMatchdays(daysAhead = 7): Promise<{ matchdays: Matchday[]; error?: string }> {
  const r = await fetch(`${BASE}/api/matchdays/upcoming?days_ahead=${daysAhead}`);
  return r.json();
}

export async function getElo(n = 20): Promise<EloEntry[]> {
  const r = await fetch(`${BASE}/api/elo?n=${n}`);
  const data = await r.json();
  return data.ranking;
}

export async function getTeams(): Promise<Record<string, string[]>> {
  const r = await fetch(`${BASE}/api/teams`);
  return r.json();
}

export async function getFeatureImportance(n = 15): Promise<FeatureImportanceEntry[]> {
  const r = await fetch(`${BASE}/api/feature-importance?n=${n}`);
  const data = await r.json();
  return data.features;
}

export async function getLiveMatches(): Promise<{ matches: LiveMatch[]; ts: string; source?: string }> {
  const r = await fetch(`${BASE}/api/live`);
  return r.json();
}

export type InplayRequest = {
  home: string; away: string;
  home_league: string; away_league: string;
  score_home: number; score_away: number; minute: number;
};

export async function predictInplay(params: InplayRequest): Promise<Prediction> {
  const r = await fetch(`${BASE}/api/predict/inplay`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
