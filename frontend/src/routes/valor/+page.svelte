<script lang="ts">
  import { matchHref, type ValuePick } from '$lib/api';
  import { pct, signed } from '$lib/format';

  let { data } = $props();
  const flags = $derived(Object.fromEntries(data.leagues.map((l) => [l.code, l.flag])));

  let minEv = $state(0.02);
  let market = $state<'all' | ValuePick['market']>('all');
  const book = (key: string) => key.replace(/_(eu|uk|fr|se|nl|it|de)$/, '').replace(/_/g, ' ');
  // The same bookmaker in several countries (unibet_nl, unibet_se) is one price: keep one row.
  const picks = $derived.by(() => {
    const seen = new Set<string>();
    return data.value.picks.filter((p) => {
      const k = `${p.event_id}|${p.market}|${p.point}|${p.outcome}|${book(p.bookmaker)}`;
      if (seen.has(k) || p.ev < minEv || (market !== 'all' && p.market !== market)) return false;
      seen.add(k);
      return true;
    });
  });

  const outcomeLabel = (p: ValuePick): string => {
    if (p.market === 'h2h') return { home: `Gana ${p.home}`, draw: 'Empate', away: `Gana ${p.away}` }[p.outcome] ?? p.outcome;
    if (p.market === 'totals') return `${p.outcome === 'over' ? 'Más' : 'Menos'} de ${p.point} goles`;
    const line = p.outcome === 'home' ? p.point : -p.point;
    return `${p.outcome === 'home' ? p.home : p.away} ${signed(line, 2).replace('+0.00', '0')}`;
  };
  const when = (iso: string) =>
    new Date(iso).toLocaleString('es', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const summaries = $derived([
    { label: 'Todos los picks puntuados', s: data.clv.all },
    { label: 'Con cierre a menos de 3 h del partido', s: data.clv.final },
  ]);
</script>

<div class="page">
  <div class="page-head">
    <div>
      <h1>Valor</h1>
      <p>Cuotas de casas de apuestas que pagan más que la probabilidad justa de Pinnacle (la casa más afilada, sin
        su margen). Es como compiten los profesionales: no adivinando mejor que el mercado, sino encontrando las
        casas que se quedan atrás.</p>
    </div>
    {#if data.value.credits_left != null}
      <span class="pill">{data.value.credits_left} créditos de The Odds API este mes</span>
    {/if}
  </div>

  <section class="grid grid-2 top">
    <div class="card">
      <h2>¿Funciona? <small>valor esperado medido contra el cierre</small></h2>
      {#if data.clv.n === 0}
        <p class="note">Aún no hay picks con una consulta de cuotas posterior. Cada pick se puntúa contra la última
          cuota de Pinnacle antes del partido: si el precio que se cogió era mejor que la probabilidad justa de cierre,
          había ventaja de verdad, gane o pierda la apuesta. Hacen falta cientos de picks para que el número signifique algo.</p>
      {:else}
        {#each summaries as { label, s }}
          {#if s}
            <div class="clv">
              <span class="muted">{label}</span>
              <b class="num" style="color: {s.ev_close > 0 ? 'var(--good)' : 'var(--bad)'}">{pct(s.ev_close, 1)}</b>
              <span class="faint num">n = {s.n} · t = {s.t.toFixed(1)} · baten el cierre {pct(s.beat_close)}</span>
            </div>
          {/if}
        {/each}
        <p class="note">Con |t| &lt; 2 todavía es ruido.</p>
      {/if}
    </div>
    <div class="card">
      <h2>Cómo leerlo</h2>
      <ul class="note list">
        <li><strong>Justa</strong>: probabilidad de Pinnacle sin margen (método de potencia, que no sobrevalora a los tapados).</li>
        <li><strong>Valor</strong>: justa × cuota − 1. Un 5 % significa ganar 5 céntimos por euro a la larga, si Pinnacle acierta.</li>
        <li><strong>Modelo</strong>: lo que dice nuestro Dixon-Coles, como segunda opinión. No decide nada: en el backtest no le gana al mercado.</li>
        <li>Las casas blandas suelen limitar las cuentas que ganan con esto.</li>
      </ul>
    </div>
  </section>

  <div class="filters">
    <div class="tabs">
      {#each [['all', 'Todos'], ['h2h', '1X2'], ['totals', 'Goles'], ['spreads', 'Hándicap']] as [k, label]}
        <button class:on={market === k} onclick={() => (market = k as typeof market)}>{label}</button>
      {/each}
    </div>
    <label class="muted">Valor mínimo
      <select bind:value={minEv}>
        {#each [0.02, 0.03, 0.05, 0.08] as v}<option value={v}>{pct(v)}</option>{/each}
      </select>
    </label>
  </div>

  {#if !data.value.snapshot}
    <p class="empty">Todavía no hay cuotas. Ejecuta <code>python odds_live.py snapshot</code> en el backend.</p>
  {:else}
    <p class="faint small">Cuotas de {when(data.value.snapshot)} · {picks.length} precios</p>
    <div class="card table-wrap">
      <table class="data">
        <thead><tr><th>Partido</th><th>Apuesta</th><th>Casa</th><th class="r">Cuota</th><th class="r">Justa</th><th class="r">Modelo</th><th class="r">Valor</th></tr></thead>
        <tbody>
          {#each picks as p}
            <tr>
              <td><a href={matchHref(p.league, p.home, p.away)}>{flags[p.league] ?? ''} <b>{p.home}</b> – <b>{p.away}</b></a>
                <div class="faint small">{when(p.kickoff)}</div></td>
              <td>{outcomeLabel(p)}</td>
              <td class="muted">{book(p.bookmaker)}</td>
              <td class="r"><b>{p.price.toFixed(2)}</b></td>
              <td class="r">{pct(p.fair_p, 1)}</td>
              <td class="r faint">{p.model_p == null ? '—' : pct(p.model_p, 1)}</td>
              <td class="r"><span class="pill pill-green">+{pct(p.ev, 1)}</span></td>
            </tr>
          {:else}
            <tr><td colspan="7" class="empty">Nada por encima de ese valor ahora mismo.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .top { margin-bottom: 18px; }
  .clv { display: grid; gap: 2px; margin-bottom: 12px; }
  .clv b { font-size: 26px; font-weight: 800; }
  .list { padding-left: 18px; display: grid; gap: 6px; }
  .filters { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
  .filters .tabs { margin-bottom: 0; border-bottom: 0; }
  select { background: var(--bg3); color: var(--text); border: 1px solid var(--border2); border-radius: 8px; padding: 6px 8px; margin-left: 6px; }
  .small { font-size: 12px; margin: 8px 0; }
  td a:hover b { text-decoration: underline; }
</style>
