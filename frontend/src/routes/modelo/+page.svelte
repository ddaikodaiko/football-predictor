<script lang="ts">
  import LineChart from '$lib/components/LineChart.svelte';
  import Reliability from '$lib/components/Reliability.svelte';
  import { pct, seasonLabel } from '$lib/format';

  let { data } = $props();
  const b = $derived(data.backtest);
  const names = $derived(Object.fromEntries(data.leagues.map((l) => [l.code, `${l.flag} ${l.name}`])));

  // Share of the way from "knowing nothing" to the market that the model covers.
  const covered = $derived(b.available
    ? (b.overall.base.log_loss - b.overall.model.log_loss) / (b.overall.base.log_loss - b.overall.market.log_loss)
    : 0);
  const bars = $derived(b.available ? [
    { label: 'Sin modelo (frecuencias)', v: b.overall.base.log_loss, c: 'var(--text3)' },
    { label: 'Nuestro modelo', v: b.overall.model.log_loss, c: 'var(--accent)' },
    { label: 'Pinnacle al cierre', v: b.overall.market.log_loss, c: 'var(--blue)' },
  ] : []);
  const lo = $derived(bars.length ? Math.min(...bars.map((x) => x.v)) - 0.02 : 0);
  const hi = $derived(bars.length ? Math.max(...bars.map((x) => x.v)) : 1);
  const best = $derived(b.available ? b.betting.find((x) => x.edge === 0.05) : null);
</script>

<div class="page">
  <div class="page-head">
    <div>
      <h1>¿Qué tal acierta el modelo?</h1>
      <p>Medido como se mide de verdad: temporada a temporada, semana a semana, prediciendo cada jornada solo con
        lo que se sabía antes, y comparado con las casas de apuestas.</p>
    </div>
  </div>

  {#if !b.available}
    <p class="empty">Todavía no hay backtest. Ejecuta <code>{b.how}</code> en el backend.</p>
  {:else}
    <section class="grid grid-3 kpis">
      <div class="card"><span class="faint">Partidos evaluados</span><strong class="num">{b.matches.toLocaleString('es')}</strong>
        <span class="muted">5 grandes ligas, {seasonLabel(b.from)} – {seasonLabel(b.to)}</span></div>
      <div class="card"><span class="faint">Distancia al mercado cubierta</span><strong class="num">{pct(covered)}</strong>
        <span class="muted">entre no saber nada y la cuota de cierre</span></div>
      <div class="card"><span class="faint">Acierto del favorito</span><strong class="num">{pct(b.overall.model.accuracy, 1)}</strong>
        <span class="muted">el mercado: {pct(b.overall.market.accuracy, 1)}</span></div>
    </section>

    <div class="grid grid-2">
      <section class="card">
        <h2>Log loss <small>menos es mejor</small></h2>
        <div class="ll">
          {#each bars as x}
            <div class="llrow"><span>{x.label}</span>
              <span class="track"><i style="width: {((x.v - lo) / (hi - lo)) * 100}%; background: {x.c}"></i></span>
              <b class="num">{x.v.toFixed(4)}</b></div>
          {/each}
        </div>
        <p class="note">El log loss castiga dar poca probabilidad a lo que acaba pasando. El modelo se queda cerca del
          mercado, pero <strong>no le gana</strong>. La diferencia es parecida en todas las ligas y en todas las épocas del año:
          es información que el mercado tiene y el modelo no (bajas, alineaciones, fichajes).</p>
      </section>
      <section class="card">
        <h2>Calibración <small>¿lo que dice que pasa el 30 %, pasa el 30 %?</small></h2>
        <Reliability points={b.reliability} />
        <p class="note">Cada punto agrupa partidos por la probabilidad que dio el modelo. Sobre la diagonal, el modelo dice
          la verdad sobre su propia incertidumbre: <strong>está bien calibrado</strong>.</p>
      </section>
    </div>

    <section class="card gap">
      <h2>Por temporada <small>log loss del modelo y del mercado</small></h2>
      <LineChart labels={b.by_season.map((s) => seasonLabel(s.season))} yFormat={(v) => v.toFixed(3)}
        series={[
          { label: 'Modelo', color: 'var(--accent)', values: b.by_season.map((s) => s.model) },
          { label: 'Pinnacle al cierre', color: 'var(--blue)', values: b.by_season.map((s) => s.market), dashed: true },
        ]} />
    </section>

    <section class="card gap table-wrap">
      <h2>Por liga</h2>
      <table class="data">
        <thead><tr><th>Liga</th><th class="r">Partidos</th><th class="r">Modelo</th><th class="r">Mercado</th><th class="r">Sin modelo</th><th class="r">Acierto modelo</th><th class="r">Acierto mercado</th></tr></thead>
        <tbody>
          {#each b.by_league as r}
            <tr><td>{names[r.league] ?? r.league}</td><td class="r">{r.partidos.toLocaleString('es')}</td>
              <td class="r"><b>{r.logloss_modelo.toFixed(4)}</b></td><td class="r">{r.logloss_mercado.toFixed(4)}</td>
              <td class="r faint">{r.logloss_base.toFixed(4)}</td>
              <td class="r">{pct(r.acierto_modelo, 1)}</td><td class="r">{pct(r.acierto_mercado, 1)}</td></tr>
          {/each}
        </tbody>
      </table>
    </section>

    <section class="card gap bet">
      <h2>¿Y si hubiera apostado con él? <small>simulación, 1 unidad por apuesta</small></h2>
      <div class="grid grid-2">
        <div>
          {#if best}
            <LineChart zero labels={[]} yFormat={(v) => `${v.toFixed(0)} u`}
              series={[{ label: `Banca apostando cuando el modelo ve más de un ${pct(best.edge)} de valor`, color: 'var(--red)', values: best.curve }]} />
          {/if}
        </div>
        <div>
          <table class="data">
            <thead><tr><th>Valor mínimo</th><th class="r">Apuestas</th><th class="r">ROI</th><th class="r">Mejor que el cierre</th></tr></thead>
            <tbody>
              {#each b.betting as r}
                <tr><td>{pct(r.edge)}</td><td class="r">{r.bets.toLocaleString('es')}</td>
                  <td class="r" style="color: var(--red)"><b>{pct(r.roi, 1)}</b></td><td class="r">{pct(r.clv_positive)}</td></tr>
              {/each}
            </tbody>
          </table>
          <p class="note">Apostar a <em>todo</em> pierde un {pct(-b.bet_everything_roi, 1)} (el margen de la casa); apostar con el
            modelo pierde <strong>más</strong>. Cuando el modelo y el mercado no están de acuerdo, casi siempre tiene razón el
            mercado, y el modelo ve "valor" sobre todo en cuotas altas, justo donde más se pierde. Conclusión honesta:
            <strong>este modelo sirve para entender partidos, no para ganar dinero.</strong></p>
        </div>
      </div>
    </section>

    <section class="card gap how">
      <h2>Cómo funciona</h2>
      <ol class="note">
        <li><strong>Datos</strong>: ~95.000 partidos de 12 ligas desde 2005 (football-data.co.uk) y xG por partido de las
          cinco grandes desde 2014 (Understat).</li>
        <li><strong>Modelo</strong>: Dixon-Coles. Cada equipo tiene un ataque y una defensa; los goles de un partido son
          Poisson con esas fuerzas más la ventaja de jugar en casa, con una corrección para los marcadores bajos.</li>
        <li><strong>Ajuste</strong>: máxima verosimilitud sobre los últimos tres años, pesando más lo reciente (vida media
          de ~8 meses) y mezclando al 50 % goles y xG, que es menos ruidoso para medir lo bueno que es un equipo.</li>
        <li><strong>Simulaciones</strong>: con las fuerzas se calcula la probabilidad de cada marcador, y con eso se juegan
          miles de veces los partidos que quedan de temporada.</li>
      </ol>
    </section>
  {/if}
</div>

<style>
  .kpis { margin-bottom: 16px; }
  .kpis .card { display: grid; gap: 2px; }
  .kpis strong { font-size: 30px; font-weight: 800; line-height: 1.2; }
  .ll { display: grid; gap: 12px; margin-bottom: 14px; }
  .llrow { display: grid; grid-template-columns: 170px 1fr 60px; gap: 10px; align-items: center; font-size: 13px; }
  .track { height: 10px; background: var(--bg4); border-radius: 5px; overflow: hidden; }
  .track i { display: block; height: 100%; border-radius: 5px; }
  .llrow b { text-align: right; }
  .gap { margin-top: 16px; }
  .bet .note { margin-top: 12px; }
  .how ol { padding-left: 20px; display: grid; gap: 8px; }
</style>
