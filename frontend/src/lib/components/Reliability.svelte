<script lang="ts">
  import { pct } from '$lib/format';

  let { points }: { points: { bin: string; n: number; predicted: number; observed: number }[] } = $props();

  const S = 300;
  const pad = 36;
  const inner = S - pad * 2;
  const x = (p: number) => pad + p * inner;
  const y = (p: number) => S - pad - p * inner;
  const maxN = $derived(Math.max(...points.map((p) => p.n)));
</script>

<svg viewBox="0 0 {S} {S}" role="img" aria-label="Diagrama de calibración">
  {#each [0, 0.25, 0.5, 0.75, 1] as t}
    <line x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} class="grid" />
    <text x={pad - 6} y={y(t) + 4} text-anchor="end" class="tick">{pct(t)}</text>
    <text x={x(t)} y={S - pad + 16} text-anchor="middle" class="tick">{pct(t)}</text>
  {/each}
  <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} class="ideal" />
  <path d={points.map((p, i) => `${i ? 'L' : 'M'}${x(p.predicted)},${y(p.observed)}`).join('')} class="line" />
  {#each points as p}
    <circle cx={x(p.predicted)} cy={y(p.observed)} r={3 + 5 * Math.sqrt(p.n / maxN)} class="dot">
      <title>El modelo dijo {pct(p.predicted, 1)} y pasó el {pct(p.observed, 1)} ({p.n} casos)</title>
    </circle>
  {/each}
  <text x={S / 2} y={S - 4} text-anchor="middle" class="axis">Lo que dijo el modelo</text>
  <text x={10} y={S / 2} text-anchor="middle" class="axis" transform="rotate(-90 10 {S / 2})">Lo que pasó</text>
</svg>

<style>
  svg { width: 100%; max-width: 360px; height: auto; display: block; margin: 0 auto; }
  .grid { stroke: var(--border); }
  .ideal { stroke: var(--text3); stroke-dasharray: 4 4; }
  .line { fill: none; stroke: var(--accent); stroke-width: 2; }
  .dot { fill: var(--accent); fill-opacity: .8; stroke: var(--bg2); stroke-width: 1.5; }
  .tick { fill: var(--text3); font-size: 10px; }
  .axis { fill: var(--text2); font-size: 11px; }
</style>
