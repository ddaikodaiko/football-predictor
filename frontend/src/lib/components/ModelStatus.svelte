<script lang="ts">
  import type { StatusResponse } from '$lib/api';
  let { status }: { status: StatusResponse } = $props();
  const m = $derived(status.meta);
</script>

<div class="pill">
  {#if status.ready}
    <span class="dot live"></span>
    <span class="acc">{(m.accuracy * 100).toFixed(1)}%</span>
    <span class="sep">·</span>
    <span class="info">{m.total_matches.toLocaleString()} partidos</span>
    <span class="sep">·</span>
    <span class="info">{m.features} feat.</span>
    <span class="sep">·</span>
    <span class="leagues">{m.leagues.join(' · ')}</span>
  {:else}
    <span class="dot training"></span>
    <span class="info">Entrenando modelo…</span>
  {/if}
</div>

<style>
.pill {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 5px 12px; border-radius: 4px;
  background: rgba(0,201,107,.08);
  border: 1px solid rgba(0,201,107,.2);
  font-size: 10px; font-weight: 600;
}
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot.live {
  background: var(--green);
  box-shadow: 0 0 8px rgba(0,201,107,.9);
  animation: pulse-g 2s ease-in-out infinite;
}
.dot.training { background: var(--amber); animation: blink 1s ease-in-out infinite; }
@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: .2; } }
@keyframes pulse-g {
  0%,100% { box-shadow: 0 0 5px rgba(0,201,107,.7); }
  50% { box-shadow: 0 0 14px rgba(0,201,107,1), 0 0 22px rgba(0,201,107,.4); }
}
.acc { font-weight: 900; font-size: 12px; color: var(--green); }
.sep { color: var(--text3); }
.info { color: var(--text2); }
.leagues { color: var(--text); font-weight: 700; }
</style>
