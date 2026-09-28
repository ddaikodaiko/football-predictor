<script lang="ts">
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
      <p>Probabilidades del modelo para la próxima jornada de las cinco grandes ligas. Pulsa un partido para ver el detalle y simularlo.</p>
    </div>
  </div>

  {#if surest.length}
    <section class="grid grid-3 highlights">
      {#each surest as m}
        <a class="card hl" href={matchHref(m.league, m.home, m.away)}>
          <span class="faint">{byCode[m.league]?.flag} {shortDate(m.date)}</span>
          <strong>{m.home} – {m.away}</strong>
          <span class="big num">{pct(m.top)}</span>
          <span class="muted">{m.top === m.p_home ? `gana ${m.home}` : m.top === m.p_away ? `gana ${m.away}` : 'empate'}</span>
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
      <h2><a href="/liga/{g.code}">{byCode[g.code]?.flag} {byCode[g.code]?.name}</a> <small>ver liga →</small></h2>
      <div class="rows">
        {#each g.matches as m}
          <a class="row" href={matchHref(g.code, m.home, m.away)}>
            <span class="date faint">{shortDate(m.date)}</span>
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
  .highlights { margin-bottom: 20px; }
  .hl { display: grid; gap: 2px; transition: border-color .15s; }
  .hl:hover { border-color: var(--border2); }
  .big { font-size: 30px; font-weight: 800; color: var(--accent); line-height: 1.2; margin-top: 6px; }
  .league { margin-bottom: 16px; }
  .league h2 a:hover { color: var(--text); }
  .rows { display: grid; }
  .row { display: grid; grid-template-columns: 90px minmax(0, 1fr) 70px minmax(0, 260px); align-items: center; gap: 12px; padding: 9px 6px; border-radius: 8px; }
  .row:hover { background: var(--bg3); }
  .teams { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .xg { text-align: center; font-size: 12px; }
  @media (max-width: 720px) {
    .row { grid-template-columns: 1fr; gap: 4px; }
    .xg { display: none; }
  }
  .legend { margin-top: 12px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-left: 6px; }
  .sw.h { background: var(--home); } .sw.d { background: var(--draw); } .sw.a { background: var(--away); }
</style>
