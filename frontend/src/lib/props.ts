// Corners and shots on target, from each team's expected count and its dispersion.
// Same maths as backend/props.py (`nb_pmf`, `markets`): the API and the static demo both
// send only the parameters, and the lines are computed here.

export type StatParams = { home: number; away: number; alpha_home: number; alpha_away: number };
export type PropsParams = { corners: StatParams; sot: StatParams; first_half: number };
export type Period = 'match' | 'first' | 'second';
export type PeriodMarkets = {
  home: number; away: number;
  overHome: (line: number) => number; overAway: (line: number) => number; overTotal: (line: number) => number;
};

/** Negative binomial (NB2: variance μ + αμ²) by recurrence. */
export function nbPmf(mu: number, alpha: number, n = 40): number[] {
  const r = 1 / alpha;
  const q = mu / (r + mu);
  const p = [Math.pow(r / (r + mu), r)];
  for (let k = 0; k < n - 1; k++) p.push((p[k] * (k + r)) / (k + 1) * q);
  return p;
}

function convolve(a: number[], b: number[]): number[] {
  const out = new Array(a.length).fill(0);
  for (let i = 0; i < a.length; i++) for (let j = 0; i + j < a.length; j++) out[i + j] += a[i] * b[j];
  return out;
}

const over = (pmf: number[]) => (line: number) => 1 - pmf.slice(0, Math.floor(line) + 1).reduce((s, x) => s + x, 0);

/** A half is NB with the same α and the mean scaled by its share (see props.py). */
export function periodMarkets(p: StatParams, period: Period, firstHalf: number): PeriodMarkets {
  const share = period === 'match' ? 1 : period === 'first' ? firstHalf : 1 - firstHalf;
  const ph = nbPmf(p.home * share, p.alpha_home);
  const pa = nbPmf(p.away * share, p.alpha_away);
  return {
    home: p.home * share, away: p.away * share,
    overHome: over(ph), overAway: over(pa), overTotal: over(convolve(ph, pa)),
  };
}

/** The .5 lines either side of a mean: the ones worth reading. */
export function linesAround(mean: number, n: number): number[] {
  const mid = Math.round(mean) - 0.5;
  const first = Math.max(0.5, mid - Math.floor((n - 1) / 2));
  return Array.from({ length: n }, (_, i) => first + i);
}
