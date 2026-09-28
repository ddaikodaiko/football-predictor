<script lang="ts">
  import { pct } from '$lib/format';

  let { home, draw, away, compact = false }: { home: number; draw: number; away: number; compact?: boolean } = $props();
</script>

<div class="bar" class:compact role="img" aria-label="Local {pct(home)}, empate {pct(draw)}, visitante {pct(away)}">
  <span class="seg h" style="flex-grow: {home}">{#if home >= 0.12}{pct(home)}{/if}</span>
  <span class="seg d" style="flex-grow: {draw}">{#if draw >= 0.12}{pct(draw)}{/if}</span>
  <span class="seg a" style="flex-grow: {away}">{#if away >= 0.12}{pct(away)}{/if}</span>
</div>

<style>
  .bar { display: flex; gap: 2px; height: 26px; border-radius: 6px; overflow: hidden; font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .bar.compact { height: 18px; font-size: 10.5px; }
  .seg { flex-basis: 0; display: flex; align-items: center; justify-content: center; min-width: 0; color: #0c1018; transition: flex-grow .4s ease; }
  .h { background: var(--home); }
  .d { background: var(--draw); }
  .a { background: var(--away); }
</style>
