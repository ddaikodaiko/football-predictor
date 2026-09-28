/**
 * The scoreline maths of backend/ratings.py and simulate.py, for the static demo: given a
 * pairing's expected goals (fitted in Python and exported), everything else is computed
 * in the browser. Same formulas, same results to rounding.
 */

export const MAX_GOALS = 10;
// Relative goal intensity per 15-minute block (simulate.GOAL_INTENSITY).
const GOAL_INTENSITY = [0.8, 0.95, 1.0, 1.0, 1.05, 1.2];

function poissonPmf(k: number, lambda: number): number {
  let p = Math.exp(-lambda);
  for (let i = 1; i <= k; i++) p *= lambda / i;
  return p;
}

function tau(x: number, y: number, lh: number, la: number, rho: number): number {
  if (x === 0 && y === 0) return 1 - lh * la * rho;
  if (x === 0 && y === 1) return 1 + lh * rho;
  if (x === 1 && y === 0) return 1 + la * rho;
  if (x === 1 && y === 1) return 1 - rho;
  return 1;
}

/** P(home scores i, away scores j), Dixon-Coles corrected and renormalised. */
export function scoreMatrix(lh: number, la: number, rho = 0, max = MAX_GOALS): number[][] {
  const m: number[][] = [];
  let total = 0;
  for (let i = 0; i <= max; i++) {
    m.push([]);
    for (let j = 0; j <= max; j++) {
      const p = poissonPmf(i, lh) * poissonPmf(j, la) * tau(i, j, lh, la, rho);
      m[i].push(p);
      total += p;
    }
  }
  return m.map((row) => row.map((p) => p / total));
}

export function markets(m: number[][]) {
  let pHome = 0, pDraw = 0, pAway = 0, o15 = 0, o25 = 0, o35 = 0, btts = 0, csHome = 0, csAway = 0;
  const cells: { score: string; prob: number }[] = [];
  m.forEach((row, i) =>
    row.forEach((p, j) => {
      if (i > j) pHome += p; else if (i === j) pDraw += p; else pAway += p;
      if (i + j > 1.5) o15 += p;
      if (i + j > 2.5) o25 += p;
      if (i + j > 3.5) o35 += p;
      if (i > 0 && j > 0) btts += p;
      if (j === 0) csHome += p;
      if (i === 0) csAway += p;
      cells.push({ score: `${i}-${j}`, prob: p });
    }),
  );
  cells.sort((a, b) => b.prob - a.prob);
  return {
    p_home: pHome, p_draw: pDraw, p_away: pAway, over15: o15, over25: o25, over35: o35,
    btts, cs_home: csHome, cs_away: csAway, top_scores: cells.slice(0, 6),
  };
}

/** Final-score odds from the current state (engine.Engine.inplay). */
export function inplay(lh: number, la: number, rho: number, scoreHome: number, scoreAway: number, minute: number) {
  const profile = GOAL_INTENSITY.flatMap((w) => Array(15).fill(w) as number[]);
  const all = profile.reduce((a, b) => a + b, 0);
  const m0 = Math.max(0, Math.min(90, Math.round(minute)));
  const left = profile.slice(m0).reduce((a, b) => a + b, 0) / all;
  const m = scoreMatrix(lh * left, la * left, rho * left);
  let pHome = 0, pDraw = 0, pAway = 0, over25 = 0;
  const cells: { score: string; prob: number }[] = [];
  m.forEach((row, i) =>
    row.forEach((p, j) => {
      const fh = scoreHome + i, fa = scoreAway + j;
      if (fh > fa) pHome += p; else if (fh === fa) pDraw += p; else pAway += p;
      if (fh + fa > 2.5) over25 += p;
      cells.push({ score: `${fh}-${fa}`, prob: p });
    }),
  );
  cells.sort((a, b) => b.prob - a.prob);
  return {
    minute: m0, score: [scoreHome, scoreAway] as [number, number], remaining_share: left,
    lambda_home_left: lh * left, lambda_away_left: la * left,
    p_home: pHome, p_draw: pDraw, p_away: pAway, over25, top_scores: cells.slice(0, 5),
  };
}

/** Small deterministic PRNG (mulberry32), so a seed replays the same match. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** One plausible match: a scoreline from the matrix, goal minutes from the intensity profile. */
export function timeline(lh: number, la: number, rho: number, seed = Math.floor(Math.random() * 2 ** 31)) {
  const rand = rng(seed);
  const m = scoreMatrix(lh, la, rho);
  let u = rand(), hg = 0, ag = 0;
  outer: for (let i = 0; i < m.length; i++)
    for (let j = 0; j < m[i].length; j++) {
      u -= m[i][j];
      if (u <= 0) { hg = i; ag = j; break outer; }
    }
  const weights = GOAL_INTENSITY.flatMap((w) => Array(15).fill(w) as number[]);
  const total = weights.reduce((a, b) => a + b, 0);
  const minute = () => {
    let v = rand() * total;
    for (let k = 0; k < 90; k++) { v -= weights[k]; if (v <= 0) return k + 1; }
    return 90;
  };
  const goals = [
    ...Array.from({ length: hg }, () => ({ side: 'home' as const, minute: minute() })),
    ...Array.from({ length: ag }, () => ({ side: 'away' as const, minute: minute() })),
  ].sort((a, b) => a.minute - b.minute);
  return { score: [hg, ag] as [number, number], goals };
}
