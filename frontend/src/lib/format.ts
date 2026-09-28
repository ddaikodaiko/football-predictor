export const pct = (p: number | null | undefined, digits = 0): string =>
  p == null ? '—' : `${(p * 100).toFixed(digits)}%`;

export const signed = (x: number, digits = 2): string => `${x >= 0 ? '+' : ''}${x.toFixed(digits)}`;

/** Fair decimal odds for a probability. */
export const odds = (p: number): string => (p > 0 ? (1 / p).toFixed(2) : '—');

const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const DAYS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];

export function shortDate(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function dateWithYear(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export const seasonLabel = (code: string): string => `20${code.slice(0, 2)}/${code.slice(2)}`;

/** Colour ramp for heatmaps: transparent -> accent, by share of the max. */
export function heat(value: number, max: number, rgb = '0,201,107'): string {
  const a = max > 0 ? Math.min(value / max, 1) : 0;
  return `rgba(${rgb},${(0.06 + a * 0.84).toFixed(3)})`;
}
