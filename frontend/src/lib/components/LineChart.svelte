<script lang="ts">
  type Series = { label: string; color: string; values: number[]; dashed?: boolean };

  let {
    series, labels = [], height = 220, yFormat = (v: number) => v.toFixed(2), zero = false,
  }: {
    series: Series[]; labels?: string[]; height?: number; yFormat?: (v: number) => string; zero?: boolean;
  } = $props();

  const W = 640;
  const pad = { l: 48, r: 12, t: 10, b: 26 };
  const n = $derived(Math.max(...series.map((s) => s.values.length)));
  const all = $derived(series.flatMap((s) => s.values).filter(Number.isFinite));
  const lo = $derived(zero ? Math.min(0, ...all) : Math.min(...all));
  const hi = $derived(Math.max(...all));
  const span = $derived(hi - lo || 1);
  const x = (i: number) => pad.l + (n > 1 ? (i / (n - 1)) * (W - pad.l - pad.r) : 0);
  const y = (v: number) => pad.t + (1 - (v - lo) / span) * (height - pad.t - pad.b);
  const ticks = $derived([0, 0.25, 0.5, 0.75, 1].map((f) => lo + f * span));
  const path = (values: number[]) =>
    values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('');
  const every = $derived(Math.max(1, Math.ceil(labels.length / 8)));
</script>

<svg viewBox="0 0 {W} {height}" role="img" aria-label={series.map((s) => s.label).join(', ')}>
  {#each ticks as t}
    <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} class="grid" />
    <text x={pad.l - 6} y={y(t) + 4} class="tick" text-anchor="end">{yFormat(t)}</text>
  {/each}
  {#if zero && lo < 0}
    <line x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} class="zero" />
  {/if}
  {#each labels as l, i}
    {#if i % every === 0}
      <text x={x(i)} y={height - 6} class="tick" text-anchor="middle">{l}</text>
    {/if}
  {/each}
  {#each series as s}
    <path d={path(s.values)} fill="none" stroke={s.color} stroke-width="2.2" stroke-dasharray={s.dashed ? '5 4' : undefined} stroke-linejoin="round" />
  {/each}
</svg>
<div class="legend">
  {#each series as s}
    <span><i style="background: {s.color}"></i>{s.label}</span>
  {/each}
</div>

<style>
  svg { width: 100%; height: auto; display: block; }
  .grid { stroke: var(--border); }
  .zero { stroke: var(--text3); stroke-dasharray: 3 3; }
  .tick { fill: var(--text3); font-size: 11px; font-variant-numeric: tabular-nums; }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--text2); margin-top: 6px; }
  .legend i { display: inline-block; width: 10px; height: 3px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
</style>
