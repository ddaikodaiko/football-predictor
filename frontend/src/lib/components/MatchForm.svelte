<script lang="ts">
  import { getTeams, predictMatch } from '$lib/api';
  import type { Prediction } from '$lib/api';
  import { onMount } from 'svelte';

  let { onResult }: { onResult: (p: Prediction) => void } = $props();

  let teams: Record<string, string[]> = $state({});
  let home = $state('');
  let away = $state('');
  let homeLeague = $state('SP1');
  let awayLeague = $state('SP1');
  let b365h = $state('');
  let b365d = $state('');
  let b365a = $state('');
  let loading = $state(false);
  let error = $state('');

  const leagues = ['SP1', 'F1'];
  const leagueLabel: Record<string, string> = { SP1: 'La Liga', F1: 'Ligue 1' };

  onMount(async () => {
    try {
      teams = await getTeams();
    } catch {}
  });

  const homeTeams = $derived(teams[homeLeague] ?? []);
  const awayTeams = $derived(teams[awayLeague] ?? []);

  async function submit() {
    if (!home || !away) { error = 'Selecciona ambos equipos'; return; }
    error = '';
    loading = true;
    try {
      const pred = await predictMatch({
        home, away,
        home_league: homeLeague,
        away_league: awayLeague,
        b365h: b365h ? parseFloat(b365h) : undefined,
        b365d: b365d ? parseFloat(b365d) : undefined,
        b365a: b365a ? parseFloat(b365a) : undefined,
      });
      onResult(pred);
    } catch (e: any) {
      error = e.message ?? 'Error del servidor';
    } finally {
      loading = false;
    }
  }

  // Quick presets
  const presets = [
    { home: 'Strasbourg', away: 'Vallecano', hl: 'F1', al: 'SP1', label: '🏆 Conference — Hoy' },
    { home: 'Levante', away: 'Osasuna', hl: 'SP1', al: 'SP1', label: 'La Liga — Mañana' },
  ];

  function applyPreset(p: typeof presets[0]) {
    home = p.home; away = p.away;
    homeLeague = p.hl; awayLeague = p.al;
  }
</script>

<div class="card form-card">
  <div class="form-title">
    <span>⚽ Predecir partido</span>
    <div class="presets">
      {#each presets as p}
        <button class="preset-btn" onclick={() => applyPreset(p)}>{p.label}</button>
      {/each}
    </div>
  </div>

  <div class="form-grid">
    <!-- Home -->
    <div class="field">
      <label for="form-home-league">Local</label>
      <select id="form-home-league" bind:value={homeLeague} onchange={() => { home = ''; }}>
        {#each leagues as l}<option value={l}>{leagueLabel[l]}</option>{/each}
      </select>
      <select bind:value={home}>
        <option value="">— Seleccionar —</option>
        {#each homeTeams as t}<option value={t}>{t}</option>{/each}
      </select>
    </div>

    <div class="vs-sep">vs</div>

    <!-- Away -->
    <div class="field">
      <label for="form-away-league">Visitante</label>
      <select id="form-away-league" bind:value={awayLeague} onchange={() => { away = ''; }}>
        {#each leagues as l}<option value={l}>{leagueLabel[l]}</option>{/each}
      </select>
      <select bind:value={away}>
        <option value="">— Seleccionar —</option>
        {#each awayTeams as t}<option value={t}>{t}</option>{/each}
      </select>
    </div>
  </div>

  <!-- Bet365 odds (optional) -->
  <details class="odds-section">
    <summary>Cuotas Bet365 <span class="opt">(opcional)</span></summary>
    <div class="odds-grid">
      <div class="field"><label for="form-b365h">1 (local)</label><input id="form-b365h" type="number" step="0.01" min="1" placeholder="2.10" bind:value={b365h} /></div>
      <div class="field"><label for="form-b365d">X (empate)</label><input id="form-b365d" type="number" step="0.01" min="1" placeholder="3.40" bind:value={b365d} /></div>
      <div class="field"><label for="form-b365a">2 (visitante)</label><input id="form-b365a" type="number" step="0.01" min="1" placeholder="3.50" bind:value={b365a} /></div>
    </div>
  </details>

  {#if error}<p class="error">{error}</p>{/if}

  <button class="predict-btn" onclick={submit} disabled={loading}>
    {loading ? 'Calculando…' : 'Predecir'}
  </button>
</div>

<style>
.form-card { display: flex; flex-direction: column; gap: 16px; }

.form-title {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;
  font-weight: 700; font-size: 15px;
}
.presets { display: flex; gap: 6px; flex-wrap: wrap; }
.preset-btn {
  padding: 4px 10px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--bg3); color: var(--text2); font-size: 12px;
  transition: all 0.15s;
}
.preset-btn:hover { border-color: var(--accent); color: var(--text); }

.form-grid {
  display: grid; grid-template-columns: 1fr 32px 1fr;
  align-items: end; gap: 12px;
}
.vs-sep { text-align: center; color: var(--text2); padding-bottom: 8px; font-weight: 600; }

.field { display: flex; flex-direction: column; gap: 6px; }
label { font-size: 11px; color: var(--text2); text-transform: uppercase; letter-spacing: 0.05em; }

select, input {
  padding: 8px 10px; background: var(--bg3); border: 1px solid var(--border);
  border-radius: 8px; color: var(--text); font-size: 13px; font-family: inherit;
  outline: none; transition: border-color 0.15s;
}
select:focus, input:focus { border-color: var(--accent); }

.odds-section {
  border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
}
summary {
  cursor: pointer; font-size: 12px; color: var(--text2); user-select: none;
  list-style: none;
}
summary::-webkit-details-marker { display: none; }
.opt { color: var(--bg3 ); font-size: 10px; }
.odds-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-top: 10px; }

.error { color: var(--red); font-size: 12px; }

.predict-btn {
  padding: 12px; border-radius: 10px; border: none;
  background: var(--accent); color: white; font-size: 14px; font-weight: 700;
  transition: opacity 0.15s, transform 0.1s;
}
.predict-btn:hover:not(:disabled) { opacity: 0.85; transform: translateY(-1px); }
.predict-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
