<script lang="ts">
  import { base } from '$app/paths';
  import { goto } from '$app/navigation';
  import FormPills from '$lib/components/FormPills.svelte';
  import ProbBar from '$lib/components/ProbBar.svelte';
  import RatingsScatter from '$lib/components/RatingsScatter.svelte';
  import { matchHref } from '$lib/api';
  import { heat, pct, seasonLabel, shortDate, signed } from '$lib/format';

  let { data } = $props();

  type Tab = 'forecast' | 'table' | 'ratings' | 'fixtures';
  let tab = $state<Tab>('table');
  $effect(() => {
    tab = data.forecast ? 'forecast' : 'table';
  });

  const f = $derived(data.forecast);
  const nTeams = $derived(f ? f.table.length : 0);
  const zoneClass = (pos: number) => {
    if (!f) return '';
    if (pos <= f.zones.title) return 'z-title';
    if (pos <= f.zones.europe) return 'z-europe';
    if (pos > nTeams - f.zones.relegation) return 'z-rel';
    return '';
  };
  const posMax = $derived(f ? Math.max(...Object.values(f.positions).flat()) : 1);
  const tier1 = $derived(data.leagues.filter((l) => l.tier === 1));
  const tier2 = $derived(data.leagues.filter((l) => l.tier === 2));
</script>

<div class="page">
  <div class="page-head">
    <div>
      <h1>{data.league.flag} {data.league.name}</h1>
      <p>Temporada {seasonLabel(data.league.season)} · {data.league.played} partidos jugados
        {#if data.league.has_xg}· con xG{/if}</p>
    </div>
    <select value={data.league.code} onchange={(e) => goto(`${base}/liga/${e.currentTarget.value}`)} aria-label="Cambiar de liga">
      <optgroup label="Primera división">
        {#each tier1 as l}<option value={l.code}>{l.flag} {l.name}</option>{/each}
      </optgroup>
      <optgroup label="Segunda división">
        {#each tier2 as l}<option value={l.code}>{l.flag} {l.name}</option>{/each}
      </optgroup>
    </select>
  </div>

  <div class="tabs">
    {#if f}<button class:on={tab === 'forecast'} onclick={() => (tab = 'forecast')}>Pronóstico de temporada</button>{/if}
    <button class:on={tab === 'table'} onclick={() => (tab = 'table')}>Clasificación</button>
    <button class:on={tab === 'ratings'} onclick={() => (tab = 'ratings')}>Fuerza de los equipos</button>
    {#if data.fixtures.length}<button class:on={tab === 'fixtures'} onclick={() => (tab = 'fixtures')}>Próximos partidos</button>{/if}
  </div>

  {#if tab === 'forecast' && f}
    <p class="note intro">{f.sims.toLocaleString('es')} temporadas simuladas desde la clasificación actual, jugando los
      <strong>{f.remaining}</strong> partidos que faltan con el modelo.</p>
    <div class="card table-wrap">
      <table class="data">
        <thead>
          <tr><th>#</th><th>Equipo</th><th class="r">Pts hoy</th><th class="r">Pts final</th>
            <th class="r">Campeón</th><th class="r">{f.zones.top_label} (top {f.zones.europe})</th><th class="r">Descenso</th></tr>
        </thead>
        <tbody>
          {#each f.table as r, i}
            <tr class={zoneClass(i + 1)}>
              <td class="faint">{i + 1}</td>
              <td><b>{r.team}</b></td>
              <td class="r">{r.pts_actual}</td>
              <td class="r"><b>{r.pts_esperados.toFixed(0)}</b></td>
              <td class="r"><span class="cell" style={heat(r.p_campeon, 1)}>{pct(r.p_campeon)}</span></td>
              <td class="r"><span class="cell" style={heat(r.p_champions, 1, 'good')}>{pct(r.p_champions)}</span></td>
              <td class="r"><span class="cell" style={heat(r.p_descenso, 1, 'bad')}>{pct(r.p_descenso)}</span></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="card positions">
      <h2>Dónde acaba cada equipo <small>probabilidad de cada puesto final</small></h2>
      <div class="table-wrap">
        <table class="heat">
          <thead><tr><th></th>{#each f.table as _, k}<th>{k + 1}</th>{/each}</tr></thead>
          <tbody>
            {#each f.table as r}
              <tr>
                <th>{r.team}</th>
                {#each f.positions[r.team] as p, k}
                  <td style={heat(p, posMax)} title="{r.team} {k + 1}º: {pct(p, 1)}">{p >= 0.05 ? Math.round(p * 100) : ''}</td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {:else if tab === 'table'}
    <div class="card table-wrap">
      <table class="data">
        <thead><tr><th>#</th><th>Equipo</th><th class="r">PJ</th><th class="r">GF</th><th class="r">GC</th><th class="r">DG</th><th class="r">Pts</th><th>Últimos 5</th></tr></thead>
        <tbody>
          {#each data.table as r}
            <tr>
              <td class="faint">{r.position}</td><td><b>{r.team}</b></td>
              <td class="r">{r.pj}</td><td class="r">{r.gf}</td><td class="r">{r.ga}</td>
              <td class="r">{signed(r.gd, 0)}</td><td class="r"><b>{r.pts}</b></td>
              <td><FormPills results={r.form} /></td>
            </tr>
          {:else}
            <tr><td colspan="8" class="empty">Todavía no se ha jugado ningún partido esta temporada.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else if tab === 'ratings'}
    <div class="grid grid-2">
      <div class="card"><RatingsScatter ratings={data.ratings} /></div>
      <div class="card table-wrap">
        <table class="data">
          <thead><tr><th>Equipo</th><th class="r">A favor</th><th class="r">En contra</th><th class="r">Balance</th></tr></thead>
          <tbody>
            {#each data.ratings as r}
              <tr><td><b>{r.team}</b></td><td class="r">{r.xgf.toFixed(2)}</td><td class="r">{r.xga.toFixed(2)}</td>
                <td class="r"><b style="color: {r.net >= 0 ? 'var(--good)' : 'var(--bad)'}">{signed(r.net)}</b></td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
    <p class="note intro">Goles que marcaría y encajaría cada equipo, por partido, contra un rival medio en campo
      neutral. Salen del modelo Dixon-Coles sobre lo que el mercado esperaba de cada equipo en sus partidos ya
      jugados: tienen en cuenta la fuerza de los rivales y pesan mucho los partidos recientes.</p>
  {:else if tab === 'fixtures'}
    <div class="card">
      {#each data.fixtures as m}
        <a class="fx" href={matchHref(data.league.code, m.home, m.away)}>
          <span class="faint">{shortDate(m.date)}</span>
          <span><b>{m.home}</b> <span class="faint">vs</span> <b>{m.away}</b></span>
          <ProbBar home={m.p_home} draw={m.p_draw} away={m.p_away} compact />
        </a>
      {/each}
    </div>
  {/if}
</div>

<style>
  select { background: var(--bg3); color: var(--text); border: 1px solid var(--border2); border-radius: 8px; padding: 8px 10px; }
  .intro { margin-bottom: 14px; }
  .cell { display: inline-block; min-width: 48px; padding: 2px 6px; border-radius: 4px; text-align: right; }
  tr.z-title td:first-child { box-shadow: inset 3px 0 var(--accent); }
  tr.z-europe td:first-child { box-shadow: inset 3px 0 var(--good); }
  tr.z-rel td:first-child { box-shadow: inset 3px 0 var(--bad); }
  .positions { margin-top: 16px; }
  table.heat { border-collapse: separate; border-spacing: 2px; font-size: 11px; font-variant-numeric: tabular-nums; }
  table.heat th { color: var(--text3); font-weight: 600; padding: 0 4px; white-space: nowrap; text-align: right; }
  table.heat thead th { text-align: center; }
  table.heat td { width: 30px; height: 22px; text-align: center; border-radius: 3px; color: var(--text); }
  .fx { display: grid; grid-template-columns: 90px minmax(0, 1fr) minmax(0, 260px); gap: 12px; align-items: center; padding: 9px 6px; border-radius: 8px; }
  .fx:hover { background: var(--bg3); }
  @media (max-width: 720px) { .fx { grid-template-columns: 1fr; gap: 4px; } }
</style>
