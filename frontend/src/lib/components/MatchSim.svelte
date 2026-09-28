<script lang="ts">
  import { api, type Timeline } from '$lib/api';

  let { league, home, away }: { league: string; home: string; away: string } = $props();

  const DURATION_MS = 9000;
  let timeline = $state<Timeline | null>(null);
  let minute = $state(0);
  let running = $state(false);
  let error = $state('');
  let history = $state<[number, number][]>([]);
  let frame = 0;

  const shown = $derived(timeline ? timeline.goals.filter((g) => g.minute <= minute) : []);
  const score = $derived([
    shown.filter((g) => g.side === 'home').length,
    shown.filter((g) => g.side === 'away').length,
  ]);

  async function play() {
    cancelAnimationFrame(frame);
    error = '';
    try {
      timeline = await api.timeline(league, home, away);
    } catch (e) {
      error = (e as Error).message;
      return;
    }
    running = true;
    minute = 0;
    const start = performance.now();
    const tick = (now: number) => {
      minute = Math.min(90, Math.floor(((now - start) / DURATION_MS) * 90));
      if (minute < 90) frame = requestAnimationFrame(tick);
      else {
        running = false;
        history = [[timeline!.score[0], timeline!.score[1]] as [number, number], ...history].slice(0, 8);
      }
    };
    frame = requestAnimationFrame(tick);
  }

  function skip() {
    cancelAnimationFrame(frame);
    if (timeline && running) {
      minute = 90;
      running = false;
      history = [[timeline.score[0], timeline.score[1]] as [number, number], ...history].slice(0, 8);
    }
  }

  // Effects only run in the browser (onDestroy also runs during SSR, without rAF).
  $effect(() => () => cancelAnimationFrame(frame));
</script>

<div class="sim">
  <div class="board">
    <span class="team">{home}</span>
    <span class="score num">{score[0]} – {score[1]}</span>
    <span class="team">{away}</span>
  </div>
  <div class="clock">
    <div class="track"><div class="fill" style="width: {(minute / 90) * 100}%"></div>
      {#each timeline?.goals ?? [] as g}
        {#if g.minute <= minute}
          <span class="mark {g.side}" style="left: {(g.minute / 90) * 100}%" title="{g.minute}'"></span>
        {/if}
      {/each}
    </div>
    <span class="min num">{timeline ? `${minute}'` : ''}</span>
  </div>
  <ol class="events">
    {#each shown as g}
      <li class={g.side}><span class="num">{g.minute}'</span> ⚽ Gol de {g.side === 'home' ? home : away}</li>
    {/each}
  </ol>
  <div class="actions">
    <button class="btn btn-primary" onclick={play}>{timeline ? 'Simular otro' : 'Simular partido'}</button>
    {#if running}<button class="btn" onclick={skip}>Ir al final</button>{/if}
  </div>
  {#if history.length}
    <p class="faint hist">Resultados simulados: {history.map(([a, b]) => `${a}-${b}`).join(' · ')}</p>
  {/if}
  {#if error}<p class="error">{error}</p>{/if}
  <p class="note">Cada simulación saca un marcador de la distribución del modelo y reparte los goles
    por minuto según cuándo se marcan en las grandes ligas (menos al principio, más al final de cada parte).
    Es un partido posible, no una predicción.</p>
</div>

<style>
  .sim { display: grid; gap: 14px; }
  .board { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 12px; }
  .team { font-weight: 700; font-size: 15px; }
  .team:first-child { text-align: right; }
  .score { font-size: 34px; font-weight: 800; letter-spacing: 0.02em; }
  .clock { display: flex; align-items: center; gap: 10px; }
  .track { position: relative; flex: 1; height: 8px; background: var(--bg4); border-radius: 4px; }
  .fill { height: 100%; background: var(--text3); border-radius: 4px; }
  .mark { position: absolute; top: -4px; width: 4px; height: 16px; border-radius: 2px; transform: translateX(-2px); }
  .mark.home { background: var(--home); }
  .mark.away { background: var(--away); }
  .min { width: 36px; text-align: right; color: var(--text2); font-weight: 700; }
  .events { list-style: none; display: grid; gap: 4px; min-height: 24px; }
  .events li { font-size: 13px; }
  .events li.home { color: var(--home); }
  .events li.away { color: var(--away); text-align: right; }
  .actions { display: flex; gap: 8px; }
  .hist { font-size: 12px; }
</style>
