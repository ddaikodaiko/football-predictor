<script lang="ts">
  import type { Prediction, LiveMatch } from '$lib/api';
  import { predictInplay } from '$lib/api';
  import { onMount } from 'svelte';

  let { pred, liveData = null }: { pred: Prediction; liveData?: LiveMatch | null } = $props();

  type Tab = 'sim' | 'htft' | 'form' | 'h2h' | 'factors';
  let tab = $state<Tab>('sim');

  const bk   = $derived(pred.bookmaker);
  const poly  = $derived(pred.polymarket);
  const sim   = $derived(pred.simulation);
  const h2h   = $derived(pred.h2h);
  const an    = $derived(pred.analysis);

  const polyH = $derived(poly?.prices[0] ?? null);
  const polyD = $derived(poly?.prices.length === 3 ? poly.prices[1] : null);
  const polyA = $derived(poly?.prices.length === 3 ? poly.prices[2] : (poly?.prices[1] ?? null));

  type Col = { verdict: string; label: string; ml: number; bk: number|null; poly: number|null };
  const cols = $derived<Col[]>([
    { verdict: '1', label: pred.home,  ml: pred.p_home, bk: bk?.p_home ?? null, poly: polyH },
    { verdict: 'X', label: 'Empate',   ml: pred.p_draw, bk: bk?.p_draw ?? null, poly: polyD },
    { verdict: '2', label: pred.away,  ml: pred.p_away, bk: bk?.p_away ?? null, poly: polyA },
  ]);

  const h2hHasData = $derived(!!(h2h && h2h.h2h_home_win_pct + h2h.h2h_away_win_pct > 0));
  const h2hTotal   = $derived(h2h ? h2h.h2h_home_win_pct + h2h.h2h_draw_pct + h2h.h2h_away_win_pct : 1);
  const hasFactors = $derived(!!(an.key_factors?.length || pred.claude_analysis));
  const eloPctH    = $derived(pred.elo_home / (pred.elo_home + pred.elo_away) * 100);

  function pct(n: number) { return (n * 100).toFixed(1) + '%'; }
  function bigPct(n: number) { return (n * 100).toFixed(0); }

  const statRows = $derived([
    { label: 'Goles marc.',    h: pred.home_stats.avg_GF,  a: pred.away_stats.avg_GF,  inv: false },
    { label: 'Goles encaj.',   h: pred.home_stats.avg_GA,  a: pred.away_stats.avg_GA,  inv: true  },
    { label: 'Tiros a puerta', h: pred.home_stats.avg_SoT, a: pred.away_stats.avg_SoT, inv: false },
    { label: 'Pts / jornada',  h: pred.home_stats.avg_Pts, a: pred.away_stats.avg_Pts, inv: false },
  ]);

  const confCls = $derived(
    an.confidence === 'alta' ? 'cf-green' : an.confidence === 'media' ? 'cf-amber' : 'cf-red'
  );
  const verdictName = $derived(
    an.verdict === 'X' ? 'Empate' : an.verdict === '1' ? pred.home : pred.away
  );

  // ── ANIMATIONS ──────────────────────────────────────────────
  let oddsVisible = $state(false);
  let simVisible  = $state(false);
  let mcCount     = $state(0);
  const MC_TOTAL  = 50000;

  // Pitch
  interface Shot { id: number; x: number; y: number; team: 'home'|'away'; goal: boolean }
  let shots      = $state<Shot[]>([]);
  let liveH      = $state(0);
  let liveA      = $state(0);
  let shotSeq    = 0;

  // Live match
  type Phase = 'pre' | 'playing' | 'ht' | 'second' | 'ft';
  interface LiveEvent { id: number; minute: number; type: 'goal'|'shot'|'save'; team: 'home'|'away' }
  let matchClock  = $state(0);
  let matchPhase  = $state<Phase>('pre');
  let liveEvents  = $state<LiveEvent[]>([]);
  let goalFlash   = $state(false);
  let evSeq       = 0;

  const MATCH_MS = 10000;   // 10 s real = 90 match minutes
  const HALF_MS  = MATCH_MS / 2;
  const HT_MS    = 700;     // halftime pause

  onMount(() => {
    const t = setTimeout(() => { oddsVisible = true; }, 100);
    return () => clearTimeout(t);
  });

  $effect(() => {
    if (tab === 'sim' && sim) {
      simVisible = false; mcCount = 0;
      shots = []; liveH = 0; liveA = 0;
      matchClock = 0; matchPhase = 'pre';
      liveEvents = []; goalFlash = false;

      const timers: ReturnType<typeof setTimeout>[] = [];
      const intervals: ReturnType<typeof setInterval>[] = [];

      const t0 = setTimeout(() => {
        simVisible = true;
        matchPhase = 'playing';

        // MC counter (cubic ease, 2 s)
        const mc0 = performance.now();
        const countMC = (now: number) => {
          const p = Math.min((now - mc0) / 2000, 1);
          mcCount = Math.round((1 - Math.pow(1 - p, 3)) * MC_TOTAL);
          if (p < 1) requestAnimationFrame(countMC);
          else mcCount = MC_TOTAL;
        };
        requestAnimationFrame(countMC);

        // ── Match clock ─────────────────────────────────────
        const realStart = Date.now();
        const clockInterval = setInterval(() => {
          const elapsed = Date.now() - realStart;
          if (elapsed < HALF_MS) {
            matchClock = Math.round((elapsed / HALF_MS) * 45);
          } else if (elapsed < HALF_MS + HT_MS) {
            matchClock = 45;
            matchPhase = 'ht';
          } else {
            const second = elapsed - HALF_MS - HT_MS;
            matchClock = Math.min(90, 45 + Math.round((second / HALF_MS) * 45));
            if (matchPhase !== 'second' && matchPhase !== 'ft') matchPhase = 'second';
            if (matchClock >= 90) { matchPhase = 'ft'; clearInterval(clockInterval); }
          }
        }, 90);
        intervals.push(clockInterval);

        // ── Generate shot events with match minutes ──────────
        const lh = sim.lambda_home, la = sim.lambda_away;
        const nHome = Math.max(3, Math.round(lh * 6));
        const nAway = Math.max(3, Math.round(la * 6));

        interface Ev { team: 'home'|'away'; goalP: number; minute: number }
        const evList: Ev[] = [];
        for (let i = 0; i < nHome; i++)
          evList.push({ team: 'home', goalP: lh / nHome, minute: 1 + Math.floor(Math.random() * 89) });
        for (let i = 0; i < nAway; i++)
          evList.push({ team: 'away', goalP: la / nAway, minute: 1 + Math.floor(Math.random() * 89) });
        evList.sort((a, b) => a.minute - b.minute);

        evList.forEach(ev => {
          // Map match minute → real ms (accounting for HT pause)
          const realDelay = ev.minute <= 45
            ? (ev.minute / 45) * HALF_MS
            : HALF_MS + HT_MS + ((ev.minute - 45) / 45) * HALF_MS;

          const evTid = setTimeout(() => {
            const isGoal = Math.random() < ev.goalP;
            const shotId = shotSeq++;
            const xBase = ev.team === 'home' ? 52 : 4;
            const x = xBase + Math.random() * 38;
            const y = 10 + Math.random() * 80;
            shots = [...shots, { id: shotId, x, y, team: ev.team, goal: isGoal }];
            setTimeout(() => { shots = shots.filter(s => s.id !== shotId); }, 2800);

            if (isGoal) {
              if (ev.team === 'home') liveH += 1; else liveA += 1;
              goalFlash = true;
              setTimeout(() => { goalFlash = false; }, 700);
            }

            const type: 'goal'|'shot'|'save' = isGoal ? 'goal' : Math.random() > 0.42 ? 'shot' : 'save';
            const evId = evSeq++;
            liveEvents = [{ id: evId, minute: ev.minute, type, team: ev.team }, ...liveEvents].slice(0, 6);
          }, realDelay);
          timers.push(evTid);
        });
      }, 80);
      timers.push(t0);

      return () => {
        timers.forEach(clearTimeout);
        intervals.forEach(clearInterval);
      };
    }
  });

  function scoreType(score: string): 'home'|'draw'|'away' {
    const p = score.split('-');
    if (p.length !== 2) return 'draw';
    const h = parseInt(p[0]), a = parseInt(p[1]);
    return h > a ? 'home' : a > h ? 'away' : 'draw';
  }

  // ── LIVE DATA OVERLAY ──────────────────────────────────────
  const isLive = $derived(liveData != null);

  // When live data is present, real score replaces animated score
  const displayH = $derived(isLive ? liveData!.score_home : liveH);
  const displayA = $derived(isLive ? liveData!.score_away : liveA);

  const livePhase = $derived(
    !liveData ? matchPhase :
    liveData.status === 'HALFTIME' ? 'ht' :
    liveData.status === 'FINISHED' ? 'ft' :
    'playing'
  );
  const liveMinute = $derived(isLive ? (liveData!.minute ?? null) : (matchPhase !== 'pre' ? matchClock : null));

  // ── IN-PLAY PREDICTION ────────────────────────────────────
  const canInplay = $derived(
    isLive && liveData!.status === 'IN_PLAY' && liveData!.minute != null
  );

  let inplayPred = $state<Prediction | null>(null);
  let inplayLoading = $state(false);
  let inplayError = $state('');

  async function fetchInplay() {
    if (!liveData || !canInplay) return;
    inplayLoading = true; inplayError = '';
    try {
      inplayPred = await predictInplay({
        home: pred.home, away: pred.away,
        home_league: pred.home_league, away_league: pred.away_league,
        score_home: liveData!.score_home,
        score_away: liveData!.score_away,
        minute: liveData!.minute!,
      });
    } catch { inplayError = 'Error en predicción live'; }
    finally { inplayLoading = false; }
  }

  const inplaySim = $derived(inplayPred?.inplay_simulation ?? null);
</script>

<article class="mc" class:mc-val={an?.has_value} class:mc-live={isLive}>

  <!-- ── HEADER ───────────────────────────────────────────── -->
  <div class="mc-head">
    <div class="head-left">
      <span class="league-chip">{pred.home_league}{pred.cross_league ? ` / ${pred.away_league}` : ''}</span>
      {#if pred.cross_league}<span class="cross-chip">CROSS-LEAGUE</span>{/if}
      {#if isLive}
        <span class="live-badge">
          <span class="live-dot-hd"></span>
          {liveData!.status === 'FINISHED' ? 'FINAL' : liveData!.status === 'HALFTIME' ? 'DESCANSO' : 'EN VIVO'}
          {#if liveData!.minute && liveData!.status !== 'HALFTIME' && liveData!.status !== 'FINISHED'}
            · {liveData!.minute}'
          {/if}
        </span>
      {/if}
    </div>
    <div class="head-right">
      {#if canInplay}
        <button class="inplay-btn" onclick={fetchInplay} disabled={inplayLoading}>
          {inplayLoading ? '…' : '↺'} LIVE
        </button>
      {/if}
      <span class="conf-chip {confCls}">{an.confidence} · {(an.confidence_pct*100).toFixed(0)}%</span>
    </div>
  </div>

  <!-- ── TEAMS ─────────────────────────────────────────────── -->
  <div class="teams-row">
    <div class="team home">
      <div class="t-name">{pred.home}</div>
      <div class="t-elo">{pred.elo_home} ELO</div>
      {#if pred.home_stats.form?.length}
        <div class="form-dots">
          {#each pred.home_stats.form as r}<span class="fd fd-{r.toLowerCase()}">{r}</span>{/each}
          {#if pred.home_stats.streak && Math.abs(pred.home_stats.streak)>=2}
            <span class="streak" class:sk-w={pred.home_stats.streak>0} class:sk-l={pred.home_stats.streak<0}>{pred.home_stats.streak>0?'+':''}{pred.home_stats.streak}</span>
          {/if}
        </div>
      {/if}
    </div>
    <div class="vs-col">
      <span class="vs">VS</span>
    </div>
    <div class="team away">
      <div class="t-name">{pred.away}</div>
      <div class="t-elo">{pred.elo_away} ELO</div>
      {#if pred.away_stats.form?.length}
        <div class="form-dots right">
          {#if pred.away_stats.streak && Math.abs(pred.away_stats.streak)>=2}
            <span class="streak" class:sk-w={pred.away_stats.streak>0} class:sk-l={pred.away_stats.streak<0}>{pred.away_stats.streak>0?'+':''}{pred.away_stats.streak}</span>
          {/if}
          {#each pred.away_stats.form as r}<span class="fd fd-{r.toLowerCase()}">{r}</span>{/each}
        </div>
      {/if}
    </div>
  </div>

  <!-- ELO bar -->
  <div class="elo-bar">
    <div class="eb-home" style="width:{eloPctH.toFixed(0)}%"></div>
    <div class="eb-away"></div>
  </div>

  <!-- ── ODDS BOXES ─────────────────────────────────────────── -->
  <div class="odds-row" class:odds-vis={oddsVisible}>
    {#each cols as col, ci}
      {@const win = col.verdict === an.verdict}
      <div class="odds-box" class:odds-win={win} style="--delay:{ci*90}ms">
        <span class="odds-label">{col.verdict === '1' ? 'LOCAL' : col.verdict === 'X' ? 'EMPATE' : 'VISITA'}</span>
        <span class="odds-pct">{bigPct(col.ml)}<sup>%</sup></span>
        <span class="odds-name">{col.label}</span>
        {#if col.bk != null || col.poly != null}
          <div class="odds-subs">
            {#if col.bk != null}
              {@const d = col.ml - col.bk}
              <span class="osub">BK {(col.bk*100).toFixed(0)}%{#if Math.abs(d)>.04}<em class:ep={d>0} class:en={d<0}>{d>0?'+':''}{(d*100).toFixed(0)}</em>{/if}</span>
            {/if}
            {#if col.poly != null}
              {@const d = col.ml - col.poly}
              <span class="osub">PM {(col.poly*100).toFixed(0)}%{#if Math.abs(d)>.04}<em class:ep={d>0} class:en={d<0}>{d>0?'+':''}{(d*100).toFixed(0)}</em>{/if}</span>
            {/if}
          </div>
        {/if}
      </div>
    {/each}
  </div>

  <!-- Prob bar -->
  <div class="prob-bar">
    <div class="pb-h" style="width:{(pred.p_home*100).toFixed(0)}%"><span>{bigPct(pred.p_home)}%</span></div>
    <div class="pb-d" style="width:{(pred.p_draw*100).toFixed(0)}%">{#if pred.p_draw>.14}<span>{bigPct(pred.p_draw)}%</span>{/if}</div>
    <div class="pb-a" style="flex:1"><span>{bigPct(pred.p_away)}%</span></div>
  </div>

  <!-- ── VERDICT ────────────────────────────────────────────── -->
  <div class="verdict-row">
    <div class="vrd">
      <span class="vrd-lbl">PREDICCIÓN</span>
      <span class="vrd-val">{verdictName}</span>
    </div>
    <div class="vrd-right">
      {#if an.value_bets?.length}
        {#each an.value_bets as vb}
          <span class="vbet">VALUE +{(vb.edge*100).toFixed(0)}%</span>
        {/each}
      {/if}
      {#if sim}
        <div class="qstats">
          <span class:hot={sim.over25>.6} class:cold={sim.over25<.4}>O2.5 {pct(sim.over25)}</span>
          <span class="qs-sep">·</span>
          <span class:hot={sim.btts>.6} class:cold={sim.btts<.38}>BTTS {pct(sim.btts)}</span>
          <span class="qs-sep">·</span>
          <span class="xg-val">xG {sim.lambda_home.toFixed(1)}–{sim.lambda_away.toFixed(1)}</span>
        </div>
      {/if}
    </div>
  </div>

  <!-- ── TABS ───────────────────────────────────────────────── -->
  <div class="tabs">
    {#if sim}<button class="tab" class:ta={tab==='sim'} onclick={() => tab='sim'}>Simulación</button>{/if}
    {#if sim?.htft_top?.length}<button class="tab" class:ta={tab==='htft'} onclick={() => tab='htft'}>HT/FT</button>{/if}
    <button class="tab" class:ta={tab==='form'} onclick={() => tab='form'}>Forma</button>
    {#if h2hHasData}<button class="tab" class:ta={tab==='h2h'} onclick={() => tab='h2h'}>H2H</button>{/if}
    {#if hasFactors}<button class="tab" class:ta={tab==='factors'} onclick={() => tab='factors'}>Factores</button>{/if}
  </div>

  <!-- ── TAB BODY ───────────────────────────────────────────── -->
  <div class="tbody">

    <!-- ── SIMULACIÓN ──────────────────────────────────── -->
    {#if tab === 'sim' && sim}
      <div class="sim-pane" class:sim-vis={simVisible}>

        <!-- PITCH -->
        <div class="pitch-wrap">

          <!-- Goal flash -->
          {#if goalFlash}<div class="goal-flash"></div>{/if}

          <!-- Live score bar -->
          <div class="live-score">
            <span class="ls-team home">{pred.home}</span>
            <span class="ls-num" class:ls-real={isLive}>{displayH}</span>
            <span class="ls-dash">–</span>
            <span class="ls-num" class:ls-real={isLive}>{displayA}</span>
            <span class="ls-team away">{pred.away}</span>
            {#if livePhase !== 'pre'}
              <div class="match-clock">
                {#if livePhase === 'ht'}
                  <span class="phase-badge ph-ht">HT</span>
                {:else if livePhase === 'ft'}
                  <span class="phase-badge ph-ft">FT</span>
                {:else}
                  <span class="phase-badge ph-live">{isLive ? '● VIVO' : 'EN VIVO'}</span>
                  {#if liveMinute !== null}<span class="clock-min">{liveMinute}'</span>{/if}
                {/if}
              </div>
            {/if}
          </div>
          {#if isLive && liveData!.ht_home != null}
            <div class="ht-score">HT {liveData!.ht_home}–{liveData!.ht_away}</div>
          {/if}

          <!-- The pitch -->
          <div class="pitch">
            <div class="pitch-stripes"></div>
            <div class="pitch-halfway"></div>
            <div class="pitch-center-circle"></div>
            <div class="pitch-center-dot"></div>
            <div class="pitch-box left"></div>
            <div class="pitch-box right"></div>
            <div class="pitch-goal left"></div>
            <div class="pitch-goal right"></div>
            {#each shots as s (s.id)}
              <div
                class="shot {s.team}"
                class:is-goal={s.goal}
                style="left:{s.x}%;top:{s.y}%"
              ></div>
            {/each}
          </div>

          <!-- Team labels + event feed -->
          <div class="pitch-bottom">
            <div class="pitch-labels">
              <span class="pl home">{pred.home}</span>
              <span class="pl away">{pred.away}</span>
            </div>
            {#if liveEvents.length > 0}
              <div class="event-feed">
                {#each liveEvents as ev (ev.id)}
                  <div class="ev-item ev-{ev.type}">
                    <span class="ev-min">{ev.minute}'</span>
                    {#if ev.type === 'goal'}
                      <span class="ev-icon">⚽</span>
                      <span class="ev-text">GOOOL — {ev.team === 'home' ? pred.home : pred.away}</span>
                    {:else if ev.type === 'shot'}
                      <span class="ev-icon ev-arrow">›</span>
                      <span class="ev-text">Disparo — {ev.team === 'home' ? pred.home : pred.away}</span>
                    {:else}
                      <span class="ev-icon ev-save">✋</span>
                      <span class="ev-text">Parada — {ev.team === 'home' ? pred.away : pred.home}</span>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        </div>

        <!-- MC counter -->
        <div class="mc-counter">
          <span class="mc-num">{mcCount.toLocaleString()}</span>
          <span class="mc-label">/ {MC_TOTAL.toLocaleString()} simulaciones Monte Carlo</span>
        </div>

        <!-- Score bars -->
        <div class="score-bars">
          {#each sim.top_scores as s, i}
            {@const type = scoreType(s.score)}
            {@const relW = (s.prob / (sim.top_scores[0]?.prob||1) * 100).toFixed(0)}
            <div class="sbar">
              <span class="sbar-score" class:sb-top={i===0}>{s.score}</span>
              <div class="sbar-track">
                <div class="sbar-fill sbar-{type}" style="--w:{relW}%; --d:{i*60}ms"></div>
              </div>
              <span class="sbar-pct">{(s.prob*100).toFixed(1)}%</span>
              {#if i===0}<span class="sbar-star">★</span>{/if}
            </div>
          {/each}
        </div>

        <!-- MC stats grid -->
        <div class="mc-stats">
          <div class="mcs"><span>Over 1.5</span><b>{pct(sim.over15)}</b></div>
          <div class="mcs"><span>1 (MC)</span><b class="b-home">{pct(sim.p_home)}</b></div>
          <div class="mcs"><span>X (MC)</span><b class="b-draw">{pct(sim.p_draw)}</b></div>
          <div class="mcs"><span>2 (MC)</span><b class="b-away">{pct(sim.p_away)}</b></div>
        </div>

        <!-- Extended markets -->
        {#if sim.over35 != null}
          <div class="ext-markets">
            <div class="em-row">
              <div class="em"><span class="em-l">Over 3.5</span><b class:hot={sim.over35>.35} class:cold={sim.over35<.18}>{pct(sim.over35)}</b></div>
              <div class="em"><span class="em-l">CS Local</span><b>{pct(sim.cs_home)}</b></div>
              <div class="em"><span class="em-l">CS Visita</span><b>{pct(sim.cs_away)}</b></div>
              <div class="em"><span class="em-l">DNB 1</span><b class="b-home">{pct(sim.dnb_home)}</b></div>
              <div class="em"><span class="em-l">DNB 2</span><b class="b-away">{pct(sim.dnb_away)}</b></div>
              <div class="em"><span class="em-l">AH +0.5 1</span><b class="b-home">{pct(sim.ah_plus_half_home)}</b></div>
            </div>
          </div>
        {/if}

        <!-- In-play panel -->
        {#if inplaySim}
          <div class="inplay-panel">
            <div class="ip-hdr">
              <span class="ip-title">⚡ PREDICCIÓN EN VIVO</span>
              <span class="ip-sub">{inplaySim.current_score} · min {inplaySim.minute} · {inplaySim.remaining_minutes}' restantes</span>
            </div>
            <div class="ip-bars">
              <div class="ip-bar-row">
                <span class="ip-team home">{pred.home}</span>
                <div class="ip-track">
                  <div class="ip-fill b-home-bg" style="width:{(inplaySim.p_home*100).toFixed(0)}%"></div>
                </div>
                <span class="ip-pct b-home">{pct(inplaySim.p_home)}</span>
              </div>
              <div class="ip-bar-row">
                <span class="ip-team">Empate</span>
                <div class="ip-track">
                  <div class="ip-fill b-draw-bg" style="width:{(inplaySim.p_draw*100).toFixed(0)}%"></div>
                </div>
                <span class="ip-pct b-draw">{pct(inplaySim.p_draw)}</span>
              </div>
              <div class="ip-bar-row">
                <span class="ip-team away">{pred.away}</span>
                <div class="ip-track">
                  <div class="ip-fill b-away-bg" style="width:{(inplaySim.p_away*100).toFixed(0)}%"></div>
                </div>
                <span class="ip-pct b-away">{pct(inplaySim.p_away)}</span>
              </div>
            </div>
            <div class="ip-minis">
              <span>O2.5 {pct(inplaySim.over25)}</span>
              <span>BTTS {pct(inplaySim.btts)}</span>
              <span>CS Local {pct(inplaySim.cs_home)}</span>
              <span>DNB 1 {pct(inplaySim.dnb_home)}</span>
              <span>DNB 2 {pct(inplaySim.dnb_away)}</span>
            </div>
            <div class="ip-top">
              {#each inplaySim.top_scores.slice(0,3) as s}
                <span class="ip-score">{s.score} <em>{(s.prob*100).toFixed(1)}%</em></span>
              {/each}
            </div>
          </div>
        {:else if canInplay && inplayError}
          <p class="ip-err">{inplayError}</p>
        {/if}

        {#if poly?.question}
          <p class="poly-q">Polymarket: "{poly.question}"</p>
        {/if}
      </div>
    {/if}

    <!-- ── HT/FT ──────────────────────────────────────── -->
    {#if tab === 'htft' && sim?.htft_top}
      <div class="htft-pane">
        <div class="htft-grid">
          {#each Object.entries(sim.htft ?? {}) as [code, prob]}
            {@const label = { HH:'1/1',HD:'1/X',HA:'1/2',DH:'X/1',DD:'X/X',DA:'X/2',AH:'2/1',AD:'2/X',AA:'2/2' }[code] ?? code}
            {@const isTop = sim.htft_top[0]?.combo === code}
            <div class="htft-cell" class:htft-top={isTop}>
              <span class="htft-lbl">{label}</span>
              <span class="htft-pct">{pct(prob as number)}</span>
            </div>
          {/each}
        </div>
        <div class="htft-bars">
          {#each sim.htft_top.slice(0, 5) as entry}
            {@const relW = (entry.prob / (sim.htft_top[0]?.prob || 1) * 100).toFixed(0)}
            <div class="htft-bar-row">
              <span class="htft-bar-lbl">{entry.label}</span>
              <div class="htft-track">
                <div class="htft-fill" style="width:{relW}%"></div>
              </div>
              <span class="htft-bar-pct">{pct(entry.prob)}</span>
            </div>
          {/each}
        </div>
        <p class="htft-note">HT/FT = resultado al descanso / resultado final. Simulación Monte Carlo 50k iter.</p>
      </div>
    {/if}

    <!-- ── FORMA ─────────────────────────────────────── -->
    {#if tab === 'form'}
      <div class="form-pane">
        {#each statRows as s}
          {@const total = s.h + s.a || 1}
          {@const pw = s.inv ? s.a/total*100 : s.h/total*100}
          <div class="stat-row">
            <span class="sv sv-h">{s.h.toFixed(1)}</span>
            <div class="st-track">
              <div class="st-h" style="width:{pw.toFixed(0)}%"></div>
              <div class="st-a" style="width:{(100-pw).toFixed(0)}%"></div>
            </div>
            <span class="sv sv-a">{s.a.toFixed(1)}</span>
          </div>
          <div class="st-label">{s.label}</div>
        {/each}
      </div>
    {/if}

    <!-- ── H2H ───────────────────────────────────────── -->
    {#if tab === 'h2h' && h2hHasData}
      <div class="h2h-pane">
        <div class="h2h-nums">
          <div class="hn hn-h">
            <span class="hn-pct">{(h2h.h2h_home_win_pct*100).toFixed(0)}%</span>
            <span class="hn-name">{pred.home}</span>
          </div>
          <div class="hn hn-d">
            <span class="hn-pct">{(h2h.h2h_draw_pct*100).toFixed(0)}%</span>
            <span class="hn-name">Empate</span>
          </div>
          <div class="hn hn-a">
            <span class="hn-pct">{(h2h.h2h_away_win_pct*100).toFixed(0)}%</span>
            <span class="hn-name">{pred.away}</span>
          </div>
        </div>
        <div class="h2h-bar">
          <div class="h2b h2b-h" style="width:{(h2h.h2h_home_win_pct/h2hTotal*100).toFixed(0)}%"></div>
          <div class="h2b h2b-d" style="width:{(h2h.h2h_draw_pct/h2hTotal*100).toFixed(0)}%"></div>
          <div class="h2b h2b-a" style="flex:1"></div>
        </div>
        <div class="h2h-goals">
          <span class="hg-h">{h2h.h2h_avg_goals_home.toFixed(1)} gol/p</span>
          <span class="hg-sep">vs</span>
          <span class="hg-a">{h2h.h2h_avg_goals_away.toFixed(1)} gol/p</span>
        </div>
      </div>
    {/if}

    <!-- ── FACTORES ──────────────────────────────────── -->
    {#if tab === 'factors' && hasFactors}
      <div class="factors-pane">
        {#if pred.claude_analysis}
          <div class="claude-blk">
            <span class="cl-hdr">✦ Análisis Claude</span>
            <p class="cl-body">{pred.claude_analysis}</p>
          </div>
        {/if}
        {#if an.key_factors?.length}
          <ul class="flist">
            {#each an.key_factors as f}
              <li><span class="fa">›</span>{f}</li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}

  </div>
</article>

<style>
/* ── CARD ──────────────────────────────────────────────── */
.mc {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  display: flex; flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow);
  transition: border-color .15s, box-shadow .15s;
}
.mc:hover { border-color: var(--border2); }
.mc.mc-val { border-left: 3px solid var(--green); }
.mc.mc-live { border-left: 3px solid var(--red); box-shadow: var(--shadow), 0 0 0 1px rgba(232,69,69,.15); }

/* ── HEAD ─────────────────────────────────────────────── */
.mc-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 14px;
  background: var(--bg3);
  border-bottom: 1px solid var(--border);
}
.league-chip {
  font-size: 9px; font-weight: 800; color: var(--text3);
  text-transform: uppercase; letter-spacing: .09em;
}
.cross-chip {
  font-size: 8px; font-weight: 800; padding: 1px 6px;
  background: rgba(0,201,107,.12); color: var(--green);
  border: 1px solid rgba(0,201,107,.25); border-radius: 3px;
  margin-left: 7px; letter-spacing: .05em;
}
.live-badge {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 8px; font-weight: 900; padding: 2px 8px;
  background: rgba(232,69,69,.15); color: var(--red);
  border: 1px solid rgba(232,69,69,.35); border-radius: 3px;
  margin-left: 7px; letter-spacing: .07em;
  animation: live-pulse 2s ease-in-out infinite;
}
@keyframes live-pulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(232,69,69,.0); }
  50% { box-shadow: 0 0 8px 2px rgba(232,69,69,.2); }
}
.live-dot-hd {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--red); flex-shrink: 0;
  animation: blink-live 1s ease-in-out infinite;
}
.conf-chip {
  font-size: 9px; font-weight: 800; padding: 2px 8px;
  border-radius: 3px; letter-spacing: .06em;
}
.cf-green { background: rgba(0,201,107,.12); color: var(--green); border: 1px solid rgba(0,201,107,.25); }
.cf-amber { background: rgba(245,166,35,.12); color: var(--amber); border: 1px solid rgba(245,166,35,.25); }
.cf-red   { background: rgba(232,69,69,.12); color: var(--red); border: 1px solid rgba(232,69,69,.25); }

/* ── TEAMS ─────────────────────────────────────────────── */
.teams-row {
  display: grid; grid-template-columns: 1fr 50px 1fr;
  align-items: center; padding: 14px 14px 10px;
}
.team { display: flex; flex-direction: column; gap: 4px; }
.team.away { align-items: flex-end; }
.t-name { font-size: 17px; font-weight: 900; letter-spacing: -.02em; line-height: 1.1; }
.home .t-name { color: var(--home); }
.away .t-name { color: var(--away); }
.t-elo { font-size: 9px; color: var(--text3); font-weight: 700; letter-spacing: .05em; }

.form-dots { display: flex; align-items: center; gap: 2px; }
.form-dots.right { flex-direction: row-reverse; }
.fd { font-size: 8px; font-weight: 900; padding: 1.5px 4px; border-radius: 2px; }
.fd-w { background: rgba(0,201,107,.15); color: var(--green); }
.fd-d { background: rgba(245,166,35,.15); color: var(--amber); }
.fd-l { background: rgba(232,69,69,.15); color: var(--red); }
.streak { font-size: 8px; font-weight: 900; padding: 1.5px 5px; border-radius: 2px; }
.sk-w { background: rgba(0,201,107,.12); color: var(--green); }
.sk-l { background: rgba(232,69,69,.12); color: var(--red); }

.vs-col { display: flex; align-items: center; justify-content: center; }
.vs { font-size: 9.5px; font-weight: 900; color: var(--text3); letter-spacing: .15em; }

/* ELO bar */
.elo-bar { display: flex; height: 3px; }
.eb-home { background: var(--home); transition: width .5s; }
.eb-away { background: var(--away); flex: 1; }

/* ── ODDS BOXES ────────────────────────────────────────── */
.odds-row {
  display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px;
  padding: 12px 14px;
  border-top: 1px solid var(--border);
}
.odds-box {
  display: flex; flex-direction: column; align-items: center; gap: 3px;
  padding: 10px 6px;
  background: var(--bg3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: default; position: relative;
  opacity: 0; transform: translateY(6px);
  transition: opacity .4s ease, transform .4s ease, background .15s, border-color .15s;
  transition-delay: var(--delay, 0ms);
}
.odds-vis .odds-box { opacity: 1; transform: translateY(0); }
.odds-box:hover { background: var(--bg4); border-color: var(--border2); }
.odds-box.odds-win {
  background: rgba(245,166,35,.1);
  border-color: rgba(245,166,35,.4);
  box-shadow: 0 0 14px rgba(245,166,35,.12), inset 0 1px 0 rgba(245,166,35,.08);
}
.odds-win::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: var(--amber);
  box-shadow: 0 0 8px rgba(245,166,35,.6);
}

.odds-label { font-size: 8.5px; font-weight: 800; color: var(--text3); letter-spacing: .1em; }
.odds-win .odds-label { color: var(--amber); }
.odds-pct {
  font-size: 30px; font-weight: 900; letter-spacing: -.03em;
  font-variant-numeric: tabular-nums; line-height: 1; color: var(--text2);
}
.odds-pct sup { font-size: 13px; font-weight: 700; vertical-align: super; letter-spacing: 0; }
.odds-win .odds-pct { color: var(--text); }
.odds-name {
  font-size: 9px; font-weight: 700; color: var(--text3); text-transform: uppercase;
  letter-spacing: .04em; text-align: center; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; max-width: 100%;
}
.odds-win .odds-name { color: var(--text2); }

.odds-subs { display: flex; flex-direction: column; align-items: center; gap: 1px; margin-top: 3px; }
.osub { font-size: 8.5px; color: var(--text3); font-weight: 600; font-variant-numeric: tabular-nums; }
.osub em { font-style: normal; font-size: 8px; font-weight: 800; padding: 0 3px; border-radius: 2px; margin-left: 2px; }
.ep { background: rgba(0,201,107,.12); color: var(--green); }
.en { background: rgba(232,69,69,.12); color: var(--red); }

/* Prob bar */
.prob-bar { display: flex; height: 28px; }
.pb-h {
  background: var(--home); display: flex; align-items: center;
  padding-left: 7px; min-width: 0; overflow: hidden;
}
.pb-d {
  background: rgba(255,255,255,.1); display: flex; align-items: center;
  justify-content: center; min-width: 0; overflow: hidden;
}
.pb-a {
  background: var(--away); display: flex; align-items: center;
  justify-content: flex-end; padding-right: 7px; overflow: hidden;
}
.pb-h span, .pb-d span, .pb-a span {
  font-size: 10px; font-weight: 900; color: rgba(255,255,255,.95);
  font-variant-numeric: tabular-nums; white-space: nowrap;
}

/* ── VERDICT ───────────────────────────────────────────── */
.verdict-row {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  padding: 10px 14px; border-top: 1px solid var(--border);
  flex-wrap: wrap; gap: 8px;
}
.vrd { display: flex; flex-direction: column; gap: 1px; }
.vrd-lbl { font-size: 8.5px; font-weight: 800; color: var(--text3); letter-spacing: .1em; }
.vrd-val { font-size: 18px; font-weight: 900; letter-spacing: -.02em; color: var(--text); }
.vrd-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.vbet {
  font-size: 8.5px; font-weight: 900; padding: 3px 9px;
  background: rgba(0,201,107,.1); color: var(--green);
  border: 1px solid rgba(0,201,107,.3); border-radius: 3px;
  letter-spacing: .06em; box-shadow: 0 0 8px rgba(0,201,107,.1);
}
.qstats { display: flex; align-items: center; gap: 6px; font-size: 10px; font-weight: 700; color: var(--text3); }
.qstats .hot { color: var(--green); }
.qstats .cold { color: var(--red); }
.qs-sep { color: var(--border2); }
.xg-val { color: var(--blue); }

/* ── TABS ──────────────────────────────────────────────── */
.tabs {
  display: flex; border-top: 1px solid var(--border);
  background: var(--bg3); padding: 4px 8px; gap: 2px;
}
.tab {
  padding: 6px 12px; border: none; border-radius: var(--radius-sm);
  font-size: 10px; font-weight: 700; color: var(--text3);
  background: none; cursor: pointer; letter-spacing: .04em;
  transition: color .12s, background .12s;
}
.tab:hover { color: var(--text2); background: var(--bg4); }
.tab.ta { background: var(--green3); color: var(--green); border: 1px solid rgba(0,201,107,.25); }

/* ── TAB BODY ──────────────────────────────────────────── */
.tbody { padding: 12px 14px 14px; background: var(--bg3); }

/* ── SIMULATION ────────────────────────────────────────── */
.sim-pane { display: flex; flex-direction: column; gap: 12px; }

/* PITCH WRAPPER */
.pitch-wrap {
  position: relative; border-radius: 6px; overflow: hidden;
  border: 1px solid rgba(255,255,255,.08);
}

/* Goal flash overlay */
.goal-flash {
  position: absolute; inset: 0; z-index: 20; pointer-events: none;
  background: radial-gradient(ellipse at center, rgba(0,201,107,.35) 0%, transparent 70%);
  animation: gflash .7s ease forwards;
}
@keyframes gflash {
  0%   { opacity: 0; }
  15%  { opacity: 1; }
  100% { opacity: 0; }
}

/* Live score bar */
.live-score {
  position: absolute; top: 0; left: 0; right: 0; z-index: 10;
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 5px 10px;
  background: linear-gradient(180deg, rgba(0,0,0,.75) 0%, transparent 100%);
  pointer-events: none;
}
.ls-team { font-size: 9.5px; font-weight: 800; letter-spacing: .03em; }
.ls-team.home { color: var(--home); }
.ls-team.away { color: var(--away); }
.ls-num { font-size: 20px; font-weight: 900; color: white; font-variant-numeric: tabular-nums; line-height: 1; }
.ls-num.ls-real { font-size: 26px; text-shadow: 0 0 20px rgba(255,255,255,.4); }
.ls-dash { font-size: 14px; font-weight: 400; color: rgba(255,255,255,.4); }

/* HT score mini badge inside pitch */
.ht-score {
  position: absolute; bottom: 36px; left: 50%; transform: translateX(-50%);
  font-size: 8.5px; font-weight: 800; color: rgba(255,255,255,.6);
  background: rgba(0,0,0,.5); padding: 2px 7px; border-radius: 3px;
  letter-spacing: .06em; pointer-events: none; z-index: 8;
}

/* Clock / phase badges */
.match-clock {
  display: flex; align-items: center; gap: 5px;
  position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
}
.phase-badge {
  font-size: 8px; font-weight: 900; padding: 2px 6px; border-radius: 3px;
  letter-spacing: .1em; text-transform: uppercase;
}
.ph-live {
  background: rgba(232,69,69,.9); color: white;
  animation: blink-live 1.2s ease-in-out infinite;
}
@keyframes blink-live {
  0%,100% { opacity: 1; } 50% { opacity: .55; }
}
.ph-ht { background: rgba(245,166,35,.85); color: #000; }
.ph-ft { background: rgba(0,201,107,.85); color: #000; }
.clock-min {
  font-size: 11px; font-weight: 900; color: rgba(255,255,255,.9);
  font-variant-numeric: tabular-nums; min-width: 26px;
}

/* The pitch */
.pitch {
  position: relative; height: 130px;
  background: #1a5230;
  overflow: hidden;
}
.pitch-stripes {
  position: absolute; inset: 0;
  background: repeating-linear-gradient(
    90deg,
    transparent 0px, transparent 20px,
    rgba(0,0,0,.08) 20px, rgba(0,0,0,.08) 40px
  );
}
.pitch-halfway {
  position: absolute; left: 50%; top: 0; bottom: 0; width: 1px;
  background: rgba(255,255,255,.3); transform: translateX(-50%);
}
.pitch-center-circle {
  position: absolute; left: 50%; top: 50%;
  transform: translate(-50%,-50%);
  width: 52px; height: 52px; border-radius: 50%;
  border: 1px solid rgba(255,255,255,.25);
  pointer-events: none;
}
.pitch-center-dot {
  position: absolute; left: 50%; top: 50%;
  transform: translate(-50%,-50%);
  width: 5px; height: 5px; border-radius: 50%;
  background: rgba(255,255,255,.4);
}
.pitch-box {
  position: absolute; top: 50%; transform: translateY(-50%);
  width: 18%; height: 56%;
  border: 1px solid rgba(255,255,255,.25);
}
.pitch-box.left { left: 0; border-left: none; border-radius: 0 4px 4px 0; }
.pitch-box.right { right: 0; border-right: none; border-radius: 4px 0 0 4px; }
.pitch-goal {
  position: absolute; top: 50%; transform: translateY(-50%);
  width: 4%; height: 30%;
  border: 1px solid rgba(255,255,255,.35);
  background: rgba(255,255,255,.04);
}
.pitch-goal.left { left: 0; border-left: none; }
.pitch-goal.right { right: 0; border-right: none; }

/* Shot dots */
.shot {
  position: absolute; border-radius: 50%;
  transform: translate(-50%,-50%);
  animation: shot-pop .2s ease forwards, shot-fade 2.8s ease forwards;
  pointer-events: none; z-index: 5;
}
.shot.home { width: 7px; height: 7px; background: var(--home); box-shadow: 0 0 6px var(--home); }
.shot.away { width: 7px; height: 7px; background: var(--away); box-shadow: 0 0 6px var(--away); }
.shot.is-goal { width: 12px; height: 12px; }
.shot.home.is-goal { background: var(--green); box-shadow: 0 0 16px var(--green), 0 0 28px rgba(0,201,107,.4); }
.shot.away.is-goal { background: #fff06e; box-shadow: 0 0 16px #fff06e, 0 0 28px rgba(255,240,110,.4); }
@keyframes shot-pop {
  from { transform: translate(-50%,-50%) scale(0); opacity: 0; }
  60%  { transform: translate(-50%,-50%) scale(1.4); opacity: 1; }
  to   { transform: translate(-50%,-50%) scale(1); opacity: 1; }
}
@keyframes shot-fade {
  0%, 50% { opacity: 1; }
  100%    { opacity: 0; }
}

/* Pitch bottom: labels + event feed */
.pitch-bottom {
  background: rgba(0,0,0,.4);
  border-top: 1px solid rgba(255,255,255,.06);
}
.pitch-labels {
  display: flex; justify-content: space-between;
  padding: 3px 8px;
}
.pl { font-size: 8.5px; font-weight: 800; letter-spacing: .04em; }
.pl.home { color: var(--home); }
.pl.away { color: var(--away); }

/* Event feed */
.event-feed {
  display: flex; flex-direction: column; gap: 0;
  border-top: 1px solid rgba(255,255,255,.05);
  max-height: 90px; overflow: hidden;
}
.ev-item {
  display: flex; align-items: center; gap: 6px;
  padding: 3px 8px;
  font-size: 9.5px; font-weight: 600;
  border-bottom: 1px solid rgba(255,255,255,.04);
  animation: ev-slide .25s ease forwards;
  color: rgba(255,255,255,.7);
}
@keyframes ev-slide {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.ev-item:last-child { border-bottom: none; }
.ev-goal { color: rgba(255,255,255,.95); font-weight: 800; background: rgba(0,201,107,.08); }
.ev-min { font-size: 9px; color: var(--text3); font-variant-numeric: tabular-nums; min-width: 22px; }
.ev-icon { font-size: 10px; }
.ev-arrow { color: var(--home); font-weight: 900; }
.ev-save { color: var(--amber); }
.ev-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* MC counter */
.mc-counter {
  display: flex; align-items: baseline; gap: 8px;
  padding: 6px 0; border-bottom: 1px solid var(--border);
}
.mc-num { font-size: 20px; font-weight: 900; color: var(--green); font-variant-numeric: tabular-nums; }
.mc-label { font-size: 10px; color: var(--text3); font-weight: 600; }

/* Score bars */
.score-bars { display: flex; flex-direction: column; gap: 5px; }
.sbar { display: grid; grid-template-columns: 36px 1fr 40px 16px; align-items: center; gap: 6px; }
.sbar-score {
  font-size: 12px; font-weight: 800; color: var(--text2);
  font-variant-numeric: tabular-nums; text-align: right;
}
.sbar-score.sb-top { color: var(--amber); }
.sbar-track { height: 8px; background: var(--bg4); border-radius: 2px; overflow: hidden; }
.sbar-fill {
  height: 100%; width: 0; border-radius: 2px;
  transition: width .65s cubic-bezier(.4,0,.2,1);
  transition-delay: var(--d, 0ms);
}
.sim-vis .sbar-fill { width: var(--w); }
.sbar-fill.sbar-home { background: linear-gradient(90deg, var(--home), rgba(59,158,255,.6)); }
.sbar-fill.sbar-draw { background: linear-gradient(90deg, rgba(255,255,255,.3), rgba(255,255,255,.15)); }
.sbar-fill.sbar-away { background: linear-gradient(90deg, var(--away), rgba(245,166,35,.6)); }
.sbar-pct { font-size: 10px; font-weight: 700; color: var(--text2); font-variant-numeric: tabular-nums; text-align: right; }
.sbar-star { font-size: 10px; color: var(--amber); }

/* MC stats */
.mc-stats {
  display: grid; grid-template-columns: repeat(4,1fr);
  background: var(--border); gap: 1px; border-radius: 3px; overflow: hidden;
}
.mcs {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 7px 4px; background: var(--bg2);
}
.mcs span { font-size: 8.5px; font-weight: 700; color: var(--text3); text-transform: uppercase; letter-spacing: .05em; }
.mcs b { font-size: 12px; font-weight: 900; font-variant-numeric: tabular-nums; }
.b-home { color: var(--home); }
.b-draw { color: var(--text2); }
.b-away { color: var(--away); }
.poly-q { font-size: 9.5px; color: var(--text3); font-style: italic; line-height: 1.5; border-top: 1px solid var(--border); padding-top: 8px; }

/* ── FORMA ─────────────────────────────────────────────── */
.form-pane { display: flex; flex-direction: column; gap: 4px; }
.stat-row { display: grid; grid-template-columns: 34px 1fr 34px; align-items: center; gap: 8px; }
.sv { font-size: 12px; font-weight: 900; font-variant-numeric: tabular-nums; }
.sv-h { text-align: right; color: var(--home); }
.sv-a { color: var(--away); }
.st-track { display: flex; height: 5px; border-radius: 2px; overflow: hidden; }
.st-h { background: var(--home); transition: width .4s; }
.st-a { background: var(--away); flex: 1; }
.st-label { font-size: 8.5px; color: var(--text3); text-transform: uppercase; letter-spacing: .07em; font-weight: 700; text-align: center; margin-bottom: 5px; }

/* ── HT/FT ─────────────────────────────────────────────── */
.htft-pane { display: flex; flex-direction: column; gap: 12px; }
.htft-grid {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 1px; background: var(--border); border-radius: var(--radius-sm); overflow: hidden;
}
.htft-cell {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 7px 4px; background: var(--bg2);
}
.htft-cell.htft-top {
  background: rgba(245,166,35,.1);
  border: 1px solid rgba(245,166,35,.3);
}
.htft-lbl {
  font-size: 9.5px; font-weight: 900; color: var(--text3);
  letter-spacing: .06em; font-variant-numeric: tabular-nums;
}
.htft-top .htft-lbl { color: var(--amber); }
.htft-pct { font-size: 13px; font-weight: 900; color: var(--text2); font-variant-numeric: tabular-nums; }
.htft-top .htft-pct { color: var(--amber); }

.htft-bars { display: flex; flex-direction: column; gap: 5px; }
.htft-bar-row { display: grid; grid-template-columns: 34px 1fr 44px; align-items: center; gap: 6px; }
.htft-bar-lbl { font-size: 10px; font-weight: 900; color: var(--text2); font-variant-numeric: tabular-nums; text-align: right; }
.htft-track { height: 7px; background: var(--bg4); border-radius: 2px; overflow: hidden; }
.htft-fill { height: 100%; background: linear-gradient(90deg, var(--accent), rgba(129,140,248,.5)); border-radius: 2px; transition: width .55s; }
.htft-bar-pct { font-size: 10px; font-weight: 700; color: var(--text2); font-variant-numeric: tabular-nums; }
.htft-note { font-size: 9px; color: var(--text3); line-height: 1.5; border-top: 1px solid var(--border); padding-top: 8px; }

/* ── H2H ───────────────────────────────────────────────── */
.h2h-pane { display: flex; flex-direction: column; gap: 10px; }
.h2h-nums { display: grid; grid-template-columns: 1fr 1fr 1fr; text-align: center; }
.hn { display: flex; flex-direction: column; gap: 2px; }
.hn-pct { font-size: 22px; font-weight: 900; line-height: 1; font-variant-numeric: tabular-nums; color: var(--text2); }
.hn-name { font-size: 9px; font-weight: 700; color: var(--text3); text-transform: uppercase; letter-spacing: .04em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hn-h .hn-pct { color: var(--home); }
.hn-a .hn-pct { color: var(--away); }
.h2h-bar { display: flex; height: 5px; gap: 1px; border-radius: 2px; overflow: hidden; }
.h2b { height: 100%; }
.h2b-h { background: var(--home); }
.h2b-d { background: var(--bg5); }
.h2b-a { background: var(--away); }
.h2h-goals { display: flex; align-items: center; justify-content: center; gap: 10px; font-size: 11px; font-weight: 700; }
.hg-h { color: var(--home); }
.hg-a { color: var(--away); }
.hg-sep { color: var(--text3); }

/* ── HEAD RIGHT ────────────────────────────────────────── */
.head-right { display: flex; align-items: center; gap: 6px; }
.inplay-btn {
  font-size: 8.5px; font-weight: 900; padding: 2px 8px; border-radius: 3px;
  background: rgba(232,69,69,.15); color: var(--red);
  border: 1px solid rgba(232,69,69,.35); cursor: pointer;
  letter-spacing: .06em; transition: background .12s;
}
.inplay-btn:hover:not(:disabled) { background: rgba(232,69,69,.25); }
.inplay-btn:disabled { opacity: .45; cursor: wait; }

/* ── EXTENDED MARKETS ──────────────────────────────────── */
.ext-markets {
  border-top: 1px solid var(--border); padding-top: 10px;
}
.em-row {
  display: grid; grid-template-columns: repeat(3,1fr);
  gap: 1px; background: var(--border); border-radius: 3px; overflow: hidden;
}
.em {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 6px 4px; background: var(--bg2);
}
.em-l { font-size: 8px; font-weight: 700; color: var(--text3); letter-spacing: .05em; text-transform: uppercase; }
.em b { font-size: 12px; font-weight: 900; font-variant-numeric: tabular-nums; color: var(--text2); }
.em b.hot { color: var(--green); }
.em b.cold { color: var(--red); }

/* ── IN-PLAY PANEL ─────────────────────────────────────── */
.inplay-panel {
  border: 1px solid rgba(232,69,69,.3);
  border-radius: var(--radius-sm);
  background: rgba(232,69,69,.04);
  display: flex; flex-direction: column; gap: 10px;
  padding: 12px;
  margin-top: 4px;
}
.ip-hdr { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.ip-title { font-size: 9px; font-weight: 900; color: var(--red); letter-spacing: .08em; }
.ip-sub { font-size: 9px; color: var(--text3); font-weight: 600; font-variant-numeric: tabular-nums; }

.ip-bars { display: flex; flex-direction: column; gap: 5px; }
.ip-bar-row { display: grid; grid-template-columns: 68px 1fr 44px; align-items: center; gap: 6px; }
.ip-team { font-size: 9.5px; font-weight: 800; color: var(--text2); letter-spacing: .02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ip-team.home { color: var(--home); }
.ip-team.away { color: var(--away); }
.ip-track { height: 6px; background: var(--bg4); border-radius: 3px; overflow: hidden; }
.ip-fill { height: 100%; border-radius: 3px; transition: width .5s; }
.b-home-bg { background: var(--home); }
.b-draw-bg { background: rgba(255,255,255,.2); }
.b-away-bg { background: var(--away); }
.ip-pct { font-size: 10px; font-weight: 900; font-variant-numeric: tabular-nums; text-align: right; }

.ip-minis {
  display: flex; flex-wrap: wrap; gap: 6px;
}
.ip-minis span {
  font-size: 9px; font-weight: 700; color: var(--text3);
  padding: 2px 7px; background: var(--bg4); border-radius: 3px;
}

.ip-top { display: flex; gap: 8px; flex-wrap: wrap; }
.ip-score {
  font-size: 11px; font-weight: 800; color: var(--text2);
  font-variant-numeric: tabular-nums;
}
.ip-score em { font-style: normal; color: var(--text3); font-size: 9.5px; }

.ip-err { font-size: 10px; color: var(--red); font-weight: 700; padding-top: 4px; }

/* ── FACTORES ──────────────────────────────────────────── */
.factors-pane { display: flex; flex-direction: column; gap: 10px; }
.claude-blk {
  padding: 11px 13px;
  background: rgba(0,201,107,.06);
  border-left: 2px solid rgba(0,201,107,.35);
  border-radius: 0 4px 4px 0;
}
.cl-hdr { display: block; font-size: 9px; font-weight: 800; text-transform: uppercase; letter-spacing: .09em; color: var(--green); margin-bottom: 6px; }
.cl-body { font-size: 11.5px; line-height: 1.65; color: var(--text2); white-space: pre-wrap; }
.flist { list-style: none; display: flex; flex-direction: column; gap: 5px; }
.flist li { display: flex; gap: 8px; font-size: 11.5px; color: var(--text2); line-height: 1.5; }
.fa { color: var(--green); font-weight: 700; flex-shrink: 0; }
</style>
