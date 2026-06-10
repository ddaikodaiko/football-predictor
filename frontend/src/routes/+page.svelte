<script lang="ts">
  import { onMount } from 'svelte';
  import { getStatus, getElo, getMatchdays, getUpcomingMatchdays, predictBatch, predictMatch, getTeams, getLiveMatches } from '$lib/api';
  import type { StatusResponse, EloEntry, Matchday, Prediction, LiveMatch } from '$lib/api';
  import MatchCard from '$lib/components/MatchCard.svelte';
  import EloTable from '$lib/components/EloTable.svelte';
  import ModelStatus from '$lib/components/ModelStatus.svelte';
  import FeatureImportance from '$lib/components/FeatureImportance.svelte';

  const CUSTOM_TAB = '__custom__';
  const LEAGUES = ['SP1', 'F1', 'E0', 'D1', 'I1'];
  const LEAGUE_LABEL: Record<string, string> = { SP1: 'La Liga', F1: 'Ligue 1', E0: 'Premier League', D1: 'Bundesliga', I1: 'Serie A' };

  let status          = $state<StatusResponse | null>(null);
  let elo             = $state<EloEntry[]>([]);
  let matchdays       = $state<Matchday[]>([]);
  let activeTab       = $state<string>('');
  let predictions     = $state<Record<string, Prediction[]>>({});
  let loading         = $state<Record<string, boolean>>({});
  let upcomingLoading = $state(false);
  let upcomingError   = $state('');

  let teams            = $state<Record<string, string[]>>({});
  let customHome       = $state('');
  let customAway       = $state('');
  let customHomeLeague = $state('SP1');
  let customAwayLeague = $state('SP1');
  let customB365h      = $state('');
  let customB365d      = $state('');
  let customB365a      = $state('');
  let customLoading    = $state(false);
  let customError      = $state('');

  const homeTeams = $derived(teams[customHomeLeague] ?? []);
  const awayTeams = $derived(teams[customAwayLeague] ?? []);

  onMount(() => {
    poll();
    pollLive();
    const liveInterval = setInterval(pollLive, 30000);
    return () => clearInterval(liveInterval);
  });

  async function poll() {
    try {
      status = await getStatus();
      if (status.ready) {
        const [eloData, mds, teamsData, upcomingRes] = await Promise.all([
          getElo(20), getMatchdays(), getTeams(), getUpcomingMatchdays(7),
        ]);
        elo = eloData; teams = teamsData;

        // Merge static + upcoming, deduplicate by id, upcoming first
        const upcomingMds = upcomingRes.matchdays ?? [];
        const staticIds = new Set(mds.map(m => m.id));
        const merged = [...upcomingMds, ...mds.filter(m => !upcomingMds.some(u => u.id === m.id))];
        matchdays = merged;

        const first = merged[0];
        if (first) { activeTab = first.id; loadMatchday(first); }
      } else { setTimeout(poll, 2000); }
    } catch { setTimeout(poll, 3000); }
  }

  async function loadUpcoming() {
    upcomingLoading = true; upcomingError = '';
    try {
      const res = await getUpcomingMatchdays(7);
      if (res.error) { upcomingError = res.error; return; }
      if (!res.matchdays?.length) { upcomingError = 'Sin fixtures próximos'; return; }
      const existing = new Set(matchdays.map(m => m.id));
      const fresh = res.matchdays.filter(m => !existing.has(m.id));
      matchdays = [...matchdays, ...fresh];
      if (fresh.length > 0) { activeTab = fresh[0].id; loadMatchday(fresh[0]); }
    } catch { upcomingError = 'Error conectando football-data.org'; }
    finally { upcomingLoading = false; }
  }

  async function loadMatchday(md: Matchday) {
    if (predictions[md.id] || loading[md.id]) return;
    loading[md.id] = true;
    try { predictions[md.id] = await predictBatch(md.matches); }
    finally { loading[md.id] = false; }
  }

  function selectTab(id: string) {
    activeTab = id;
    if (id === CUSTOM_TAB) return;
    const md = matchdays.find(m => m.id === id);
    if (md) loadMatchday(md);
  }

  async function submitCustom() {
    if (!customHome || !customAway) { customError = 'Selecciona ambos equipos'; return; }
    customError = ''; customLoading = true;
    try {
      const pred = await predictMatch({
        home: customHome, away: customAway,
        home_league: customHomeLeague, away_league: customAwayLeague,
        b365h: customB365h ? parseFloat(customB365h) : undefined,
        b365d: customB365d ? parseFloat(customB365d) : undefined,
        b365a: customB365a ? parseFloat(customB365a) : undefined,
      });
      predictions[CUSTOM_TAB] = [pred, ...(predictions[CUSTOM_TAB] ?? []).filter(
        p => !(p.home === pred.home && p.away === pred.away)
      )];
    } catch (e: unknown) {
      customError = e instanceof Error ? e.message : 'Error del servidor';
    }
    finally { customLoading = false; }
  }

  $effect(() => {
    if (matchdays.length > 0 && activeTab && activeTab !== CUSTOM_TAB && !predictions[activeTab]) {
      const md = matchdays.find(m => m.id === activeTab);
      if (md) loadMatchday(md);
    }
  });

  const activePredictions = $derived(predictions[activeTab] ?? []);
  const isLoading         = $derived(loading[activeTab] ?? false);
  const skeletonCount     = $derived(matchdays.find(m => m.id === activeTab)?.matches.length ?? 3);

  let liveMatches = $state<LiveMatch[]>([]);

  function findLive(home: string, away: string): LiveMatch | null {
    return liveMatches.find(
      lm => lm.home.toLowerCase() === home.toLowerCase() &&
            lm.away.toLowerCase() === away.toLowerCase()
    ) ?? null;
  }

  async function pollLive() {
    try {
      const res = await getLiveMatches();
      liveMatches = res.matches ?? [];
    } catch { /* ignore */ }
  }

  let sortBy = $state<'default' | 'confidence' | 'value'>('default');

  const sortedPredictions = $derived(
    sortBy === 'confidence'
      ? [...activePredictions].sort((a, b) => (b.analysis?.confidence_pct ?? 0) - (a.analysis?.confidence_pct ?? 0))
      : sortBy === 'value'
      ? [...activePredictions].sort((a, b) => {
          const av = a.analysis?.value_bets?.[0]?.edge ?? 0;
          const bv = b.analysis?.value_bets?.[0]?.edge ?? 0;
          return bv - av;
        })
      : activePredictions
  );

  const valueBetCount = $derived(
    activePredictions.filter(p => (p.analysis?.value_bets?.length ?? 0) > 0).length
  );
</script>

<svelte:head><title>Football Predictor</title></svelte:head>

<div class="page">

  <!-- ── HEADER ─────────────────────────────────────────── -->
  <header>
    <div class="hdr-glow"></div>
    <div class="hdr-inner">
      <div class="brand">
        <div class="brand-icon">
          <span class="bi-dot"></span>
          <span class="bi-dot b2"></span>
          <span class="bi-dot b3"></span>
        </div>
        <div class="brand-text">
          <h1>FOOTBALL PREDICTOR</h1>
          <p>ML · BOOKMAKER · POLYMARKET · DIXON-COLES</p>
        </div>
      </div>
      {#if status}<ModelStatus {status} />{/if}
    </div>
  </header>

  <main>
    {#if !status || !status.ready}
      <!-- ── SPLASH ────────────────────────────────────── -->
      <div class="splash">
        <div class="splash-inner card">
          <div class="splash-ring">
            <div class="spinner"></div>
          </div>
          <div>
            <p class="sp-title">ENTRENANDO MODELO</p>
            <p class="sp-sub">SP1 · F1 · E0 · ~90 SEG</p>
          </div>
        </div>
      </div>

    {:else}
      <div class="layout">

        <!-- ── MAIN ──────────────────────────────────────── -->
        <div class="col-main">

          <!-- Tabs -->
          <div class="tabs-wrap">
            <div class="tabs-bar">
              <div class="tabs">
                {#each matchdays as md}
                  <button class="tab" class:active={activeTab === md.id} class:live={md.live}
                    onclick={() => selectTab(md.id)}>
                    {#if md.live}<span class="live-dot"></span>{/if}
                    {md.label}
                    {#if predictions[md.id]}<span class="tbadge">{predictions[md.id].length}</span>{/if}
                  </button>
                {/each}
                <div class="tab-gap"></div>
                <button class="tab tab-next" onclick={loadUpcoming} disabled={upcomingLoading}>
                  {upcomingLoading ? 'CARGANDO…' : '▶ PRÓXIMAS'}
                </button>
                <button class="tab tab-add" class:active={activeTab === CUSTOM_TAB}
                  onclick={() => selectTab(CUSTOM_TAB)}>
                  + PARTIDO
                </button>
              </div>
            </div>
          </div>

          {#if upcomingError}
            <div class="alert">{upcomingError}</div>
          {/if}

          <!-- Custom form -->
          {#if activeTab === CUSTOM_TAB}
            <div class="custom-panel card">
              <div class="cp-header">
                <span class="cp-title">PARTIDO PERSONALIZADO</span>
                <span class="cp-sub">Cross-league soportado</span>
              </div>

              <div class="cp-grid">
                <div class="team-field">
                  <span class="tf-label">LOCAL</span>
                  <select bind:value={customHomeLeague} onchange={() => customHome = ''}>
                    {#each LEAGUES as l}<option value={l}>{LEAGUE_LABEL[l]}</option>{/each}
                  </select>
                  <select bind:value={customHome}>
                    <option value="">— EQUIPO —</option>
                    {#each homeTeams as t}<option value={t}>{t}</option>{/each}
                  </select>
                </div>
                <div class="cp-vs">VS</div>
                <div class="team-field right">
                  <span class="tf-label">VISITANTE</span>
                  <select bind:value={customAwayLeague} onchange={() => customAway = ''}>
                    {#each LEAGUES as l}<option value={l}>{LEAGUE_LABEL[l]}</option>{/each}
                  </select>
                  <select bind:value={customAway}>
                    <option value="">— EQUIPO —</option>
                    {#each awayTeams as t}<option value={t}>{t}</option>{/each}
                  </select>
                </div>
              </div>

              <details class="odds-box">
                <summary>CUOTAS BET365 <span class="opt-label">OPCIONAL</span></summary>
                <div class="odds-cols">
                  <div class="odd-f"><label for="b365h">1</label><input id="b365h" type="number" step="0.01" min="1" placeholder="2.10" bind:value={customB365h} /></div>
                  <div class="odd-f"><label for="b365d">X</label><input id="b365d" type="number" step="0.01" min="1" placeholder="3.40" bind:value={customB365d} /></div>
                  <div class="odd-f"><label for="b365a">2</label><input id="b365a" type="number" step="0.01" min="1" placeholder="3.50" bind:value={customB365a} /></div>
                </div>
              </details>

              {#if customError}<p class="cp-error">{customError}</p>{/if}

              <button class="predict-btn" onclick={submitCustom} disabled={customLoading}>
                {#if customLoading}<span class="btn-spin"></span>CALCULANDO…{:else}▶ PREDECIR PARTIDO{/if}
              </button>
            </div>
          {/if}

          <!-- Sort bar -->
          {#if activePredictions.length > 1 && activeTab !== CUSTOM_TAB}
            <div class="sort-row">
              <div class="sr-stats">
                <span class="sr-chip">{activePredictions.length} PARTIDOS</span>
                {#if valueBetCount > 0}
                  <span class="sr-chip value">{valueBetCount} VALUE BETS</span>
                {/if}
              </div>
              <div class="sr-sort">
                <span class="sr-lbl">ORDEN</span>
                <button class="sb" class:on={sortBy === 'default'} onclick={() => sortBy = 'default'}>DEFAULT</button>
                <button class="sb" class:on={sortBy === 'confidence'} onclick={() => sortBy = 'confidence'}>CONFIANZA</button>
                <button class="sb" class:on={sortBy === 'value'} onclick={() => sortBy = 'value'}>VALOR</button>
              </div>
            </div>
          {/if}

          <!-- Grid -->
          {#if activeTab !== CUSTOM_TAB && isLoading}
            <div class="grid">
              {#each { length: skeletonCount } as _}
                <div class="skel-card"></div>
              {/each}
            </div>
          {:else if activePredictions.length === 0 && activeTab !== CUSTOM_TAB}
            <div class="empty">
              <span class="empty-num">—</span>
              <p>SELECCIONA UNA JORNADA</p>
            </div>
          {:else if activePredictions.length > 0}
            <div class="grid">
              {#each sortedPredictions as pred}
                {#if pred.error}
                  <div class="card err-card">
                    <span class="err-match">{pred.home} VS {pred.away}</span>
                    <span class="err-msg">SIN DATOS SUFICIENTES</span>
                  </div>
                {:else}
                  <MatchCard {pred} liveData={findLive(pred.home, pred.away)} />
                {/if}
              {/each}
            </div>
          {/if}

        </div>

        <!-- ── SIDEBAR ─────────────────────────────────── -->
        <aside class="col-side">
          <EloTable entries={elo} />
          <FeatureImportance />
          <div class="card legend">
            <div class="lg-hdr">CAPAS DE PROBABILIDAD</div>
            <div class="lg-rows">
              <div class="lg-row"><span class="lg-tag ml">ML</span><span>Ensemble XGBoost + RF + LR + ELO</span></div>
              <div class="lg-row"><span class="lg-tag bk">BK</span><span>Bet365 — sin margen</span></div>
              <div class="lg-row"><span class="lg-tag pm">PM</span><span>Polymarket — mercado blockchain</span></div>
              <div class="lg-row"><span class="lg-tag mc">MC</span><span>Dixon-Coles 50k — τ corrección</span></div>
            </div>
            <p class="lg-note">Los badges +/− comparan capas entre sí. Cross-league: ELO > ML.</p>
          </div>
        </aside>

      </div>
    {/if}
  </main>
</div>

<style>
.page { min-height: 100vh; display: flex; flex-direction: column; }

/* ── HEADER ─────────────────────────────────────── */
header {
  background: var(--green3);
  border-bottom: 2px solid var(--green2);
  position: sticky; top: 0; z-index: 20;
}
.hdr-glow { display: none; }
.hdr-inner {
  max-width: 1400px; margin: 0 auto; padding: 11px 24px;
  display: flex; align-items: center; justify-content: space-between; gap: 20px;
}
.brand { display: flex; align-items: center; gap: 10px; }
.brand-icon {
  display: flex; flex-direction: column; gap: 2px; flex-shrink: 0;
  align-items: center; justify-content: center; width: 12px;
}
.bi-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: rgba(255,255,255,.9);
}
.bi-dot.b2 { width: 5px; height: 5px; background: rgba(255,255,255,.6); }
.bi-dot.b3 { width: 3px; height: 3px; background: rgba(255,255,255,.4); }
.brand-text h1 {
  font-size: 14px; font-weight: 900; letter-spacing: .05em;
  text-transform: uppercase; margin: 0; color: white;
}
.brand-text p {
  font-size: 9px; font-weight: 600; color: rgba(255,255,255,.5);
  letter-spacing: .08em; margin: 0; margin-top: 1px;
}

/* ── MAIN ──────────────────────────────────────── */
main { flex: 1; max-width: 1400px; margin: 0 auto; padding: 20px 24px; width: 100%; }

/* ── SPLASH ────────────────────────────────────── */
.splash {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; min-height: 60vh;
}
.splash-inner {
  display: flex; align-items: center; gap: 24px;
  padding: 32px 44px; border: 1px solid var(--border2);
  box-shadow: var(--shadow-lg);
}
.splash-ring {
  width: 48px; height: 48px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,201,107,.06); border: 1px solid rgba(0,201,107,.2);
  flex-shrink: 0;
}
.spinner {
  width: 30px; height: 30px;
  border: 3px solid var(--border2); border-top-color: var(--green);
  border-radius: 50%; animation: spin .85s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.sp-title { font-size: 13px; font-weight: 800; letter-spacing: .06em; }
.sp-sub { font-size: 10px; font-weight: 600; color: var(--text3); letter-spacing: .08em; margin-top: 4px; }

/* ── LAYOUT ────────────────────────────────────── */
.layout { display: grid; grid-template-columns: 1fr 262px; gap: 20px; align-items: start; }
.col-side { display: flex; flex-direction: column; gap: 8px; position: sticky; top: 60px; }

/* ── TABS ──────────────────────────────────────── */
.tabs-wrap { overflow-x: auto; margin-bottom: 18px; padding-bottom: 1px; }
.tabs-bar {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 3px;
}
.tabs {
  display: flex; align-items: stretch; gap: 2px; min-width: max-content;
}
.tab {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 14px; background: none;
  border: none; border-radius: var(--radius-sm);
  color: var(--text3); font-size: 10.5px; font-weight: 700;
  letter-spacing: .04em;
  white-space: nowrap; cursor: pointer;
  transition: color .12s, background .12s;
}
.tab:hover:not(:disabled) { color: var(--text2); background: var(--bg3); }
.tab.active {
  color: var(--green);
  background: rgba(0,201,107,.1);
  border: 1px solid rgba(0,201,107,.2);
}
.tab.live { color: var(--green); }
.tab.live.active { color: var(--green); background: rgba(0,201,107,.1); }

.live-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); flex-shrink: 0; animation: lv 1s ease-in-out infinite; }
@keyframes lv { 0%,100% { opacity: 1; } 50% { opacity: .2; } }

.tbadge {
  font-size: 9px; font-weight: 800; padding: 1px 6px;
  background: var(--bg4); border: 1px solid var(--border2); border-radius: 3px;
}
.active .tbadge {
  background: rgba(0,201,107,.1); border-color: rgba(0,201,107,.25); color: var(--green);
}

.tab-gap { flex: 1; }
.tab-next { color: var(--text3); }
.tab-next:hover:not(:disabled) { color: var(--text2); }
.tab-next:disabled { opacity: .35; cursor: wait; }
.tab-add { color: var(--text3); }
.tab-add:hover { color: var(--text); }
.tab-add.active { color: var(--green); background: rgba(0,201,107,.1); }

/* ── ALERT ─────────────────────────────────────── */
.alert {
  font-size: 11px; padding: 9px 14px; margin-bottom: 16px;
  background: rgba(245,166,35,.06); color: var(--amber);
  border-left: 3px solid var(--amber); border-radius: var(--radius-sm);
  font-weight: 600;
}

/* ── CUSTOM PANEL ──────────────────────────────── */
.custom-panel {
  display: flex; flex-direction: column; gap: 16px;
  margin-bottom: 20px; padding: 18px;
}
.cp-header { display: flex; align-items: baseline; justify-content: space-between; }
.cp-title { font-size: 11px; font-weight: 800; letter-spacing: .05em; color: var(--text); }
.cp-sub { font-size: 9px; font-weight: 600; color: var(--text3); }
.cp-grid {
  display: grid; grid-template-columns: 1fr 40px 1fr;
  align-items: center; gap: 10px;
}
.team-field { display: flex; flex-direction: column; gap: 6px; }
.tf-label { font-size: 8.5px; font-weight: 800; color: var(--text3); letter-spacing: .1em; text-transform: uppercase; }
.cp-vs {
  text-align: center; font-size: 9px; font-weight: 800;
  color: var(--text3); letter-spacing: .12em; padding-top: 16px;
}

select, input {
  padding: 8px 11px; background: var(--bg3); border: 1px solid var(--border);
  color: var(--text); font-size: 12px; font-family: inherit;
  outline: none; border-radius: var(--radius-sm);
  transition: border-color .12s; width: 100%;
}
select:focus, input:focus {
  border-color: var(--green2);
  box-shadow: 0 0 0 2px rgba(0,166,87,.12);
}

.odds-box {
  border: 1px solid var(--border); padding: 10px 13px; border-radius: var(--radius-sm);
}
.odds-box summary {
  cursor: pointer; font-size: 9.5px; font-weight: 700; color: var(--text2);
  letter-spacing: .06em; list-style: none; user-select: none;
}
.odds-box summary::-webkit-details-marker { display: none; }
.opt-label { color: var(--text3); font-size: 8.5px; margin-left: 6px; }
.odds-cols { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-top: 10px; }
.odd-f { display: flex; flex-direction: column; gap: 4px; }
.odd-f label {
  font-size: 9px; font-weight: 700; color: var(--text2); letter-spacing: .06em;
  text-transform: uppercase;
}
.cp-error { font-size: 10.5px; color: var(--red); font-weight: 700; }

.predict-btn {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 13px; border: none; border-radius: var(--radius-sm);
  background: var(--green2);
  color: white;
  font-size: 11px; font-weight: 800; letter-spacing: .07em;
  transition: background .12s, transform .1s, box-shadow .12s;
  box-shadow: 0 3px 12px rgba(0,166,87,.3);
}
.predict-btn:hover:not(:disabled) {
  background: var(--green);
  box-shadow: 0 5px 18px rgba(0,201,107,.4);
  transform: translateY(-1px);
}
.predict-btn:disabled { opacity: .35; cursor: not-allowed; }
.btn-spin {
  width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.3);
  border-top-color: white; border-radius: 50%; animation: spin .7s linear infinite;
}

/* ── SORT ROW ──────────────────────────────────── */
.sort-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 16px; flex-wrap: wrap;
}
.sr-stats { display: flex; align-items: center; gap: 6px; }
.sr-chip {
  font-size: 9px; font-weight: 700; padding: 3px 9px;
  border: 1px solid var(--border2); color: var(--text3);
  letter-spacing: .05em; background: var(--bg2); border-radius: 3px;
}
.sr-chip.value {
  background: rgba(0,201,107,.06); border-color: rgba(0,201,107,.25); color: var(--green);
}
.sr-sort { display: flex; align-items: center; gap: 5px; }
.sr-lbl { font-size: 8.5px; font-weight: 800; color: var(--text3); letter-spacing: .1em; margin-right: 4px; }
.sb {
  padding: 4px 12px; border: 1px solid var(--border);
  background: none; color: var(--text3); font-size: 9.5px; font-weight: 800;
  letter-spacing: .07em; text-transform: uppercase;
  transition: all .15s; cursor: pointer; border-radius: 99px;
}
.sb:hover { color: var(--text2); border-color: var(--border2); background: rgba(99,102,241,.05); }
.sb.on {
  color: var(--accent); border-color: rgba(129,140,248,.4);
  background: rgba(129,140,248,.1);
  box-shadow: 0 0 10px rgba(129,140,248,.1);
}

/* ── GRID ──────────────────────────────────────── */
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 16px; }

/* ── SKELETON ──────────────────────────────────── */
.skel-card {
  height: 460px; background: var(--bg2); border: 1px solid var(--border);
  border-radius: var(--radius);
  animation: sk 1.5s ease-in-out infinite;
}
@keyframes sk { 0%,100% { opacity: .12; } 50% { opacity: .45; } }

/* ── EMPTY ─────────────────────────────────────── */
.empty {
  display: flex; flex-direction: column; align-items: center;
  gap: 10px; padding: 80px 20px; color: var(--text3);
}
.empty-num {
  font-size: 60px; font-weight: 900; opacity: .1;
  background: linear-gradient(135deg, var(--accent), var(--cyan));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.empty p { font-size: 10px; font-weight: 800; letter-spacing: .12em; }

/* ── ERROR CARD ────────────────────────────────── */
.err-card { padding: 16px; opacity: .4; display: flex; flex-direction: column; gap: 4px; }
.err-match { font-size: 12px; font-weight: 900; letter-spacing: .04em; text-transform: uppercase; }
.err-msg { font-size: 9px; font-weight: 700; color: var(--red); letter-spacing: .08em; }

/* ── LEGEND ────────────────────────────────────── */
.legend { padding: 0; display: flex; flex-direction: column; overflow: hidden; }
.lg-hdr {
  font-size: 9px; font-weight: 800; color: var(--text2);
  letter-spacing: .1em; padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(99,102,241,.05) 0%, transparent 100%);
}
.lg-rows { display: flex; flex-direction: column; padding: 10px 16px; gap: 8px; }
.lg-row { display: flex; align-items: center; gap: 8px; font-size: 10.5px; color: var(--text2); }
.lg-tag {
  font-size: 8.5px; font-weight: 900; padding: 2px 8px;
  border-radius: 99px; flex-shrink: 0; letter-spacing: .06em; text-transform: uppercase;
}
.lg-tag.ml { background: rgba(96,165,250,.1);  color: var(--home);   border: 1px solid rgba(96,165,250,.25); }
.lg-tag.bk { background: rgba(52,211,153,.1);  color: var(--green);  border: 1px solid rgba(52,211,153,.25); }
.lg-tag.pm { background: rgba(192,132,252,.1); color: var(--away);   border: 1px solid rgba(192,132,252,.25); }
.lg-tag.mc { background: rgba(129,140,248,.1); color: var(--accent); border: 1px solid rgba(129,140,248,.25); }
.lg-note {
  font-size: 9.5px; color: var(--text3); line-height: 1.65; padding: 10px 16px;
  border-top: 1px solid var(--border);
}

/* ── RESPONSIVE ────────────────────────────────── */
@media (max-width: 1040px) {
  .layout { grid-template-columns: 1fr; }
  .col-side { position: static; flex-direction: row; flex-wrap: wrap; }
  .col-side > :global(.card) { flex: 1; min-width: 240px; }
}
@media (max-width: 660px) {
  .grid { grid-template-columns: 1fr; }
  main { padding: 14px; }
  .hdr-inner { padding: 12px 14px; }
}
</style>
