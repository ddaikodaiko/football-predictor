<script lang="ts">
  import { base } from '$app/paths';
  import { goto } from '$app/navigation';
  import FormPills from '$lib/components/FormPills.svelte';
  import LineChart from '$lib/components/LineChart.svelte';
  import MatchSim from '$lib/components/MatchSim.svelte';
  import ProbBar from '$lib/components/ProbBar.svelte';
  import ScoreHeatmap from '$lib/components/ScoreHeatmap.svelte';
  import { api, matchHref, type FormGame, type Inplay } from '$lib/api';
  import { dateWithYear, odds, pct, shortDate } from '$lib/format';
  import { linesAround, periodMarkets, type Period } from '$lib/props';

  let { data } = $props();
  const p = $derived(data.prediction);
  const leagueInfo = $derived(data.leagues.find((l) => l.code === data.league));

  function choose(league: string, home: string, away: string) {
    goto(matchHref(league, home, away), { keepFocus: true, noScroll: true });
  }
  async function changeLeague(code: string) {
    const teams = await api.teams(code);
    choose(code, teams[0], teams[1]);
  }

  // ── in-play calculator ──
  let minute = $state(60);
  let sh = $state(0);
  let sa = $state(0);
  let live = $state<Inplay | null>(null);
  let timer: ReturnType<typeof setTimeout>;
  $effect(() => {
    const args = [data.league, data.home, data.away, sh, sa, minute] as const;
    clearTimeout(timer);
    timer = setTimeout(async () => {
      live = await api.inplay(...args).catch(() => null);
    }, 150);
  });

  const markets = $derived(p ? [
    { label: 'Más de 1,5 goles', p: p.over15 },
    { label: 'Más de 2,5 goles', p: p.over25 },
    { label: 'Más de 3,5 goles', p: p.over35 },
    { label: 'Marcan los dos', p: p.btts },
    { label: `${p.home} no encaja`, p: p.cs_home },
    { label: `${p.away} no encaja`, p: p.cs_away },
  ] : []);

  const lastOdds = $derived(data.odds.points.at(-1) ?? null);
  const book = (key: string) => key.replace(/_(eu|uk|fr|se|nl|it|de)$/, '').replace(/_/g, ' ');
  const sides = $derived(p ? [
    { key: 'home' as const, label: p.home, model: p.p_home },
    { key: 'draw' as const, label: 'Empate', model: p.p_draw },
    { key: 'away' as const, label: p.away, model: p.p_away },
  ] : []);
  const moves = $derived(data.odds.points.filter((x) => x.fair));

  // ── corners and shots on target ──
  let stat = $state<'corners' | 'sot'>('corners');
  let period = $state<Period>('match');
  const STAT_LABEL = { corners: 'córners', sot: 'tiros a puerta' };
  const PERIODS: [Period, string][] = [['match', 'Partido'], ['first', '1.ª parte'], ['second', '2.ª parte']];
  const counts = $derived(p?.props ? periodMarkets(p.props[stat], period, p.props.first_half) : null);
  const countRows = $derived(counts && p ? [
    ...linesAround(counts.home + counts.away, 3).map((l) => ({ label: `Total: más de ${l.toLocaleString('es')}`, p: counts.overTotal(l) })),
    ...linesAround(counts.home, 2).map((l) => ({ label: `${p.home}: más de ${l.toLocaleString('es')}`, p: counts.overHome(l) })),
    ...linesAround(counts.away, 2).map((l) => ({ label: `${p.away}: más de ${l.toLocaleString('es')}`, p: counts.overAway(l) })),
  ] : []);

  const xgLine = (g: FormGame) => (g.xgf == null ? '' : `${g.xgf.toFixed(1)}–${g.xga?.toFixed(1)}`);
</script>

<div class="page">
  <div class="pickers card">
    <select value={data.league} onchange={(e) => changeLeague(e.currentTarget.value)} aria-label="Liga">
      {#each data.leagues as l}<option value={l.code}>{l.flag} {l.name}</option>{/each}
    </select>
    <select value={data.home} onchange={(e) => choose(data.league, e.currentTarget.value, data.away)} aria-label="Local">
      {#each data.teams as t}<option>{t}</option>{/each}
    </select>
    <span class="faint">vs</span>
    <select value={data.away} onchange={(e) => choose(data.league, data.home, e.currentTarget.value)} aria-label="Visitante">
      {#each data.teams as t}<option>{t}</option>{/each}
    </select>
    <button class="btn" onclick={() => choose(data.league, data.away, data.home)} title="Invertir local y visitante">⇄</button>
  </div>

  {#if data.error || !p}
    <p class="error">{data.error || 'Sin predicción'}</p>
  {:else}
    <section class="hero">
      <div class="side home"><span class="label">Local{#if p.ratings.home} · {p.ratings.home.rank}º en fuerza{/if}</span>
        <h1>{p.home}</h1></div>
      <div class="xg"><span class="label">Goles esperados</span>
        <span class="fig score"><span>{p.lambda_home.toFixed(2)}</span><i>–</i><span>{p.lambda_away.toFixed(2)}</span></span></div>
      <div class="side away"><span class="label">Visitante{#if p.ratings.away} · {p.ratings.away.rank}º en fuerza{/if}</span>
        <h1>{p.away}</h1></div>
      <div class="probs">
        <ProbBar home={p.p_home} draw={p.p_draw} away={p.p_away} />
        <div class="fair num">
          <span>1 · cuota justa <b>{odds(p.p_home)}</b></span><span>X · <b>{odds(p.p_draw)}</b></span><span>2 · <b>{odds(p.p_away)}</b></span>
        </div>
      </div>
      {#if !p.known.home || !p.known.away}
        <p class="note warn">Uno de los equipos no tiene partidos recientes en esta liga (recién ascendido): el modelo lo trata como un equipo medio.</p>
      {/if}
    </section>

    {#if lastOdds?.fair}
      <section class="card market">
        <h2>Mercado <small>{lastOdds.books} casas · probabilidad justa de {lastOdds.reference} sin margen</small></h2>
        <table class="data">
          <thead><tr><th></th><th class="r">Mercado</th><th class="r">Modelo</th><th class="r">Mejor cuota</th><th class="r">Valor a esa cuota</th></tr></thead>
          <tbody>
            {#each sides as s}
              {@const fair = lastOdds.fair[s.key]}
              {@const ev = fair * lastOdds.best[s.key] - 1}
              <tr><td><b>{s.label}</b></td><td class="r">{pct(fair, 1)}</td>
                <td class="r faint">{pct(s.model, 1)}</td>
                <td class="r">{lastOdds.best[s.key]?.toFixed(2)} <span class="faint">{book(lastOdds.best_book[s.key])}</span></td>
                <td class="r"><span class="pill {ev > 0.02 ? 'pill-green' : ''}">{ev >= 0 ? '+' : ''}{pct(ev, 1)}</span></td></tr>
            {/each}
          </tbody>
        </table>
        {#if moves.length > 1}
          <div class="moves">
            <LineChart yFormat={(v) => pct(v)} labels={moves.map((m) => new Date(m.at).toLocaleDateString('es', { day: 'numeric', month: 'short' }))}
              series={[
                { label: p.home, color: 'var(--home)', values: moves.map((m) => m.fair!.home) },
                { label: 'Empate', color: 'var(--draw)', values: moves.map((m) => m.fair!.draw) },
                { label: p.away, color: 'var(--away)', values: moves.map((m) => m.fair!.away) },
              ]} />
          </div>
        {:else}
          <p class="note">Con más consultas de cuotas aquí saldrá cómo se mueve el mercado hasta el partido.</p>
        {/if}
      </section>
    {/if}

    <div class="grid grid-2">
      <section class="card">
        <h2>Marcadores <small>probabilidad de cada resultado, en %</small></h2>
        <ScoreHeatmap matrix={p.score_matrix} home={p.home} away={p.away} />
        <div class="tops">
          {#each p.top_scores.slice(0, 4) as s}<span class="pill">{s.score} · {pct(s.prob)}</span>{/each}
        </div>
      </section>
      <section class="card">
        <h2>Mercados</h2>
        <div class="mk">
          {#each markets as m}
            <div class="mrow"><span>{m.label}</span><span class="bar"><i style="width: {m.p * 100}%"></i></span>
              <b class="num">{pct(m.p)}</b><span class="faint num">{odds(m.p)}</span></div>
          {/each}
        </div>
      </section>
    </div>

    {#if p.props && counts}
      <section class="card gap">
        <h2>Córners y tiros a puerta <small>esperados por equipo y probabilidad de cada línea</small></h2>
        <div class="toggles">
          <div class="seg" role="group" aria-label="Estadística">
            <button class:on={stat === 'corners'} onclick={() => (stat = 'corners')}>Córners</button>
            <button class:on={stat === 'sot'} onclick={() => (stat = 'sot')}>Tiros a puerta</button>
          </div>
          <div class="seg" role="group" aria-label="Periodo">
            {#each PERIODS as [key, label]}
              <button class:on={period === key} onclick={() => (period = key)}>{label}</button>
            {/each}
          </div>
        </div>
        <div class="counts">
          <div><span class="faint">{p.home}</span><b class="num">{counts.home.toFixed(1)}</b></div>
          <div><span class="faint">Total</span><b class="num">{(counts.home + counts.away).toFixed(1)}</b></div>
          <div><span class="faint">{p.away}</span><b class="num">{counts.away.toFixed(1)}</b></div>
        </div>
        <div class="mk">
          {#each countRows as m}
            <div class="mrow"><span>{m.label}</span><span class="bar"><i style="width: {m.p * 100}%"></i></span>
              <b class="num">{pct(m.p)}</b><span class="faint num">{odds(m.p)}</span></div>
          {/each}
        </div>
        <p class="note">{STAT_LABEL[stat][0].toUpperCase() + STAT_LABEL[stat].slice(1)} esperados a partir de los goles esperados y de
          lo que genera y concede cada equipo en {STAT_LABEL[stat]}. Medido sin mirar el futuro en 18.000 partidos: la probabilidad
          de cada línea se aparta menos de 3 puntos de lo que pasó.
          {#if period !== 'match'}Las mitades reparten el partido como se reparten los goles ({pct(p.props.first_half)} en la primera): no hay datos de {STAT_LABEL[stat]} por mitad para medirlo.{/if}</p>
      </section>
    {/if}

    <div class="grid grid-2 gap">
      {#each [{ side: 'home', team: p.home, games: p.form.home }, { side: 'away', team: p.away, games: p.form.away }] as t}
        <section class="card">
          <h2>{t.team} <small>últimos partidos · marcador y xG</small></h2>
          <FormPills results={t.games.map((g) => g.result)} />
          <table class="data form">
            <tbody>
              {#each [...t.games].reverse() as g}
                <tr><td class="faint">{shortDate(g.date)}</td><td>{g.home ? 'vs' : '@'} {g.opponent}</td>
                  <td class="r"><b>{g.gf}-{g.ga}</b></td><td class="r faint num">{xgLine(g)}</td></tr>
              {/each}
            </tbody>
          </table>
        </section>
      {/each}
    </div>

    <div class="grid grid-2 gap">
      <section class="card">
        <h2>Simulador <small>un partido posible, minuto a minuto</small></h2>
        {#key `${data.league}-${data.home}-${data.away}`}
          <MatchSim league={data.league} home={p.home} away={p.away} />
        {/key}
      </section>
      <section class="card">
        <h2>En directo <small>¿y si va así en el minuto…?</small></h2>
        <div class="live-in">
          <label>Minuto <input type="range" min="0" max="90" bind:value={minute} /> <b class="num">{minute}'</b></label>
          <div class="steppers">
            <span>{p.home}</span>
            <button class="btn" onclick={() => (sh = Math.max(0, sh - 1))}>−</button><b class="num">{sh}</b>
            <button class="btn" onclick={() => sh++}>+</button>
            <span class="faint">–</span>
            <button class="btn" onclick={() => (sa = Math.max(0, sa - 1))}>−</button><b class="num">{sa}</b>
            <button class="btn" onclick={() => sa++}>+</button>
            <span>{p.away}</span>
          </div>
        </div>
        {#if live}
          <ProbBar home={live.p_home} draw={live.p_draw} away={live.p_away} />
          <p class="note">Quedan {pct(live.remaining_share)} de los goles esperados del partido
            ({live.lambda_home_left.toFixed(2)} y {live.lambda_away_left.toFixed(2)}).
            Final más probable: {live.top_scores.slice(0, 3).map((s) => `${s.score} (${pct(s.prob)})`).join(', ')}.</p>
        {/if}
      </section>
    </div>

    {#if p.h2h.length}
      <section class="card gap">
        <h2>Últimos enfrentamientos</h2>
        <div class="h2h">
          {#each p.h2h as g}
            <span class="pill">{dateWithYear(g.date)} · {g.home} {g.fthg}-{g.ftag} {g.away}</span>
          {/each}
        </div>
        <p class="note">El modelo no usa el historial directo: con 5 o 6 partidos repartidos en años dice poco que no digan ya las fuerzas actuales.</p>
      </section>
    {/if}

    <p class="note foot">Modelo {p.model}, ajustado con {p.fitted_on.toLocaleString('es')} partidos de {leagueInfo?.name}.
      Qué tal acierta: <a href="{base}/modelo">El modelo</a>.</p>
  {/if}
</div>

<style>
  .market { margin-bottom: 16px; }
  .moves { margin-top: 14px; }
  .pickers { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 28px; padding: 10px; }
  select { background: var(--bg3); color: var(--text); border: 1px solid var(--border2); border-radius: 8px; padding: 8px 10px; }
  /* Marcador de retransmisión: cada equipo con un filete de su color de la barra 1X2. */
  .hero { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 20px 24px; align-items: end; margin-bottom: 28px; }
  .hero h1 { font-family: var(--display); font-weight: 900; text-transform: uppercase; font-size: clamp(34px, 5.4vw, 64px); line-height: .9; letter-spacing: .005em; overflow-wrap: anywhere; }
  .side { display: grid; gap: 8px; padding-bottom: 10px; border-bottom: 3px solid var(--c); }
  .side.home { --c: var(--home); }
  .side.away { --c: var(--away); }
  .score { display: flex; align-items: baseline; gap: 10px; font-size: clamp(40px, 6vw, 72px); }
  .score i { font-style: normal; color: var(--text3); font-weight: 600; }
  .side.away { text-align: right; }
  .xg { display: grid; justify-items: center; gap: 8px; padding-bottom: 13px; }
  .probs { grid-column: 1 / -1; display: grid; gap: 8px; }
  .fair { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--text3); }
  .fair b { color: var(--text2); font-weight: 600; }
  .warn { grid-column: 1 / -1; color: var(--warn); }
  @media (max-width: 640px) {
    .hero { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
    .xg { grid-column: 1 / -1; grid-row: 2; padding-bottom: 0; }
    .hero h1 { font-size: 32px; }
  }
  .gap { margin-top: 16px; }
  .tops { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }
  .mk { display: grid; gap: 10px; }
  .mrow { display: grid; grid-template-columns: minmax(0, 1fr) 90px 44px 40px; gap: 10px; align-items: center; font-size: 13px; }
  .mrow .bar { height: 6px; background: var(--bg4); border-radius: 3px; overflow: hidden; }
  .mrow .bar i { display: block; height: 100%; background: var(--accent); }
  .mrow b { text-align: right; }
  .form { margin-top: 10px; font-size: 13px; }
  .live-in { display: grid; gap: 12px; margin-bottom: 14px; }
  .live-in label { display: flex; gap: 10px; align-items: center; }
  .live-in input { flex: 1; accent-color: var(--accent); }
  .steppers { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .steppers .btn { padding: 2px 10px; }
  .steppers b { min-width: 16px; text-align: center; font-size: 18px; }
  .h2h { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
  .foot { margin-top: 20px; }
  .toggles { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
  .seg { display: inline-flex; border: 1px solid var(--border2); border-radius: 8px; overflow: hidden; }
  .seg button { background: none; border: 0; color: var(--text2); padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; }
  .seg button.on { background: var(--bg4); color: var(--text); font-weight: 700; }
  .counts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 14px; text-align: center; }
  .counts div { display: grid; gap: 2px; font-size: 12px; }
  .counts b { font-size: 22px; font-weight: 800; }
  .foot a { text-decoration: underline; }
</style>
