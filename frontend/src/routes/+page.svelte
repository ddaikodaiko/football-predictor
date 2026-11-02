<script lang="ts">
  import { base } from '$app/paths';
  import ProbBar from '$lib/components/ProbBar.svelte';
  import { matchHref } from '$lib/api';
  import { pct, shortDate } from '$lib/format';

  let { data } = $props();

  const byCode = $derived(Object.fromEntries(data.leagues.map((l) => [l.code, l])));
  let filter = $state('all');
  const groups = $derived(data.fixtures.filter((g) => g.matches.length && (filter === 'all' || g.code === filter)));

  // The pick the model is most sure about, across all leagues.
  const surest = $derived(
    data.fixtures
      .flatMap((g) => g.matches.map((m) => ({ ...m, league: g.code })))
      .map((m) => ({ ...m, top: Math.max(m.p_home, m.p_draw, m.p_away) }))
      .sort((a, b) => b.top - a.top)
      .slice(0, 3),
  );
</script>

<div class="page">
  <div class="page-head">
    <div>
      <h1>Próximos partidos</h1>
      <p>Probabilidades del modelo para la próxima jornada de las cinco grandes ligas. Pulsa un partido para ver
        marcadores, mercados y el simulador.</p>
    </div>
  </div>

  {#if surest.length}
    <section class="board" aria-label="Los pronósticos más seguros de la jornada">
      {#each surest as m}
        {@const side = m.top === m.p_home ? 'home' : m.top === m.p_away ? 'away' : 'draw'}
        <a class="pick" href={matchHref(m.league, m.home, m.away)}>
          <span class="label">{byCode[m.league]?.flag} {byCode[m.league]?.name} · {shortDate(m.date)}</span>
          <span class="fig big" style="color: var(--{side})">{pct(m.top)}</span>
          <span class="what">{side === 'home' ? `gana ${m.home}` : side === 'away' ? `gana ${m.away}` : 'empate'}</span>
          <span class="vs faint">{m.home} – {m.away}</span>
        </a>
      {/each}
    </section>
  {/if}

  <div class="tabs">
    <button class:on={filter === 'all'} onclick={() => (filter = 'all')}>Todas</button>
    {#each data.fixtures as g}
      <button class:on={filter === g.code} onclick={() => (filter = g.code)}>{byCode[g.code]?.flag} {byCode[g.code]?.name}</button>
    {/each}
  </div>

  {#each groups as g}
    <section class="card league">
      <h2><a href="{base}/liga/{g.code}">{byCode[g.code]?.flag} {byCode[g.code]?.name}</a> <small>ver liga →</small></h2>
      <div class="rows">
        {#each g.matches as m}
          <a class="row" href={matchHref(g.code, m.home, m.away)}>
            <span class="date label">{shortDate(m.date)}</span>
            <span class="teams"><b>{m.home}</b> <span class="faint">vs</span> <b>{m.away}</b></span>
            <span class="xg faint num" title="Goles esperados">{m.lambda_home.toFixed(1)} – {m.lambda_away.toFixed(1)}</span>
            <span class="bar"><ProbBar home={m.p_home} draw={m.p_draw} away={m.p_away} compact /></span>
          </a>
        {/each}
      </div>
    </section>
  {:else}
    <p class="empty">No hay partidos pendientes en el calendario. Ejecuta <code>python ingest.py --refresh</code>.</p>
  {/each}

  <p class="note legend"><span class="sw h"></span>local <span class="sw d"></span>empate <span class="sw a"></span>visitante · Los números entre equipos son los goles esperados.</p>
</div>

<style>
  /* Marcador: los tres pronósticos más seguros, separados por filetes y sin cajas. */
  .board { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin-bottom: 36px; border-block: 1px solid var(--border2); }
  .pick { display: grid; gap: 4px; padding: 20px 20px 22px; min-width: 0; transition: background .15s; }
  .pick + .pick { border-left: 1px solid var(--border); }
  .pick:hover { background: var(--bg2); }
  .big { font-size: clamp(64px, 9vw, 104px); margin: 6px 0 2px; }
  .what { font-weight: 600; font-size: 15px; }
  .vs { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  @media (max-width: 720px) {
    .board { grid-template-columns: minmax(0, 1fr); }
    .pick { grid-template-columns: auto minmax(0, 1fr); column-gap: 16px; padding: 14px 4px; }
    .pick + .pick { border-left: 0; border-top: 1px solid var(--border); }
    .pick .label { grid-column: 1 / -1; }
    .big { grid-row: span 2; font-size: 56px; margin: 0; }
    .what { align-self: end; }
  }
  .league { margin-bottom: 16px; }
  .league h2 a:hover { color: var(--text); }
  .rows { display: grid; }
  .row { display: grid; grid-template-columns: 90px minmax(0, 1fr) 70px minmax(0, 280px); align-items: center; gap: 12px; padding: 10px 8px; border-radius: 4px; }
  .row:hover { background: var(--bg3); }
  .teams { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .xg { text-align: center; font-family: var(--mono); font-size: 11.5px; }
  @media (max-width: 720px) {
    .row { grid-template-columns: 1fr; gap: 4px; }
    .xg { display: none; }
  }
  .legend { margin-top: 12px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-left: 6px; }
  .sw.h { background: var(--home); } .sw.d { background: var(--draw); } .sw.a { background: var(--away); }
</style>
