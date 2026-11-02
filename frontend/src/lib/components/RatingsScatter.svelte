<script lang="ts">
  import type { Rating } from '$lib/api';

  let { ratings }: { ratings: Rating[] } = $props();

  const W = 640;
  const H = 400;
  const pad = 44;
  const xs = $derived(ratings.map((r) => r.xgf));
  const ys = $derived(ratings.map((r) => r.xga));
  const [x0, x1] = $derived([Math.min(...xs) - 0.1, Math.max(...xs) + 0.1]);
  const [y0, y1] = $derived([Math.min(...ys) - 0.1, Math.max(...ys) + 0.1]);
  const x = (v: number) => pad + ((v - x0) / (x1 - x0)) * (W - pad * 2);
  // Fewer goals conceded is better: up.
  const y = (v: number) => pad + ((v - y0) / (y1 - y0)) * (H - pad * 2);
  const mx = $derived(xs.reduce((a, b) => a + b, 0) / xs.length);
  const my = $derived(ys.reduce((a, b) => a + b, 0) / ys.length);
</script>

<svg viewBox="0 0 {W} {H}" role="img" aria-label="Ataque contra defensa por equipo">
  <line x1={x(mx)} x2={x(mx)} y1={pad} y2={H - pad} class="mid" />
  <line x1={pad} x2={W - pad} y1={y(my)} y2={y(my)} class="mid" />
  <text x={W - pad} y={pad - 12} text-anchor="end" class="corner">buen ataque, buena defensa</text>
  <text x={pad} y={H - pad + 22} class="corner">mal ataque, mala defensa</text>
  <text x={W / 2} y={H - 8} text-anchor="middle" class="axis">Goles a favor esperados por partido →</text>
  <text x={12} y={H / 2} text-anchor="middle" class="axis" transform="rotate(-90 12 {H / 2})">← Goles en contra esperados</text>
  {#each ratings as r}
    <g transform="translate({x(r.xgf)},{y(r.xga)})">
      <circle r="5" class="dot" style="fill: color-mix(in oklab, var(--bad), var(--good) {Math.round(Math.max(0, Math.min(1, 0.5 + r.net * 0.375)) * 100)}%)">
        <title>{r.team}: {r.xgf.toFixed(2)} a favor, {r.xga.toFixed(2)} en contra</title>
      </circle>
      <text x="8" y="4" class="label">{r.team}</text>
    </g>
  {/each}
</svg>

<style>
  svg { width: 100%; height: auto; display: block; }
  .mid { stroke: var(--border2); stroke-dasharray: 3 4; }
  .dot { stroke: var(--bg2); stroke-width: 1.5; }
  .label { fill: var(--text2); font-size: 11px; }
  .corner { fill: var(--text3); font-size: 11px; font-style: italic; }
  .axis { fill: var(--text2); font-size: 11px; }
</style>
