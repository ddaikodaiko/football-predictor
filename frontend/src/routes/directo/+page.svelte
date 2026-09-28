<script lang="ts">
  import { base } from '$app/paths';
  import { onDestroy, onMount } from 'svelte';
  import ProbBar from '$lib/components/ProbBar.svelte';
  import { api, matchHref, type Inplay, type LiveMatch } from '$lib/api';

  let matches = $state<LiveMatch[]>([]);
  let source = $state('');
  let loading = $state(true);
  let probs = $state<Record<number, Inplay | null>>({});
  let timer: ReturnType<typeof setInterval>;

  const PLAYING = new Set(['IN_PLAY', 'PAUSED', 'HALFTIME']);
  const statusLabel: Record<string, string> = { IN_PLAY: 'En juego', PAUSED: 'Descanso', HALFTIME: 'Descanso', FINISHED: 'Final' };

  async function refresh() {
    const r = await api.live().catch(() => ({ matches: [], source: 'error' }));
    matches = r.matches;
    source = r.source ?? '';
    loading = false;
    for (const m of matches.filter((m) => PLAYING.has(m.status))) {
      probs[m.id] = await api.inplay(m.league, m.home, m.away, m.score_home, m.score_away, m.minute ?? 45).catch(() => null);
    }
  }

  onMount(() => {
    refresh();
    timer = setInterval(refresh, 60_000);
  });
  onDestroy(() => clearInterval(timer));
</script>

<div class="page">
  <div class="page-head">
    <div>
      <h1>Directo</h1>
      <p>Partidos de hoy en las cinco grandes, con la probabilidad del resultado final según el marcador y el minuto.
        Se actualiza cada minuto.</p>
    </div>
  </div>

  {#if loading}
    <p class="empty">Cargando…</p>
  {:else if source === 'no_key'}
    <p class="empty">Falta <code>FOOTBALL_DATA_KEY</code> en <code>backend/.env</code> (clave gratuita de football-data.org).</p>
  {:else if !matches.length}
    <p class="empty">Hoy no hay partidos de las cinco grandes ligas. Mientras tanto, prueba la calculadora en directo de cualquier
      <a href="{base}/">partido</a>.</p>
  {:else}
    <div class="grid grid-2">
      {#each matches as m (m.id)}
        <a class="card match" href={matchHref(m.league, m.home, m.away)}>
          <div class="top">
            <span class="pill {PLAYING.has(m.status) ? 'pill-green' : ''}">{statusLabel[m.status] ?? m.status}{m.minute != null && PLAYING.has(m.status) ? ` · ${m.minute}'` : ''}</span>
          </div>
          <div class="board"><span>{m.home}</span><b class="num">{m.score_home} – {m.score_away}</b><span>{m.away}</span></div>
          {#if probs[m.id]}
            <ProbBar home={probs[m.id]!.p_home} draw={probs[m.id]!.p_draw} away={probs[m.id]!.p_away} compact />
          {/if}
        </a>
      {/each}
    </div>
  {/if}
</div>

<style>
  .match { display: grid; gap: 10px; }
  .board { display: grid; grid-template-columns: 1fr auto 1fr; gap: 10px; align-items: center; font-weight: 700; }
  .board span:first-child { text-align: right; }
  .board b { font-size: 24px; }
  .empty a { text-decoration: underline; }
</style>
