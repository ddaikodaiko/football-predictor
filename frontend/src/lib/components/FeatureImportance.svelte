<script lang="ts">
  import { onMount } from 'svelte';
  import { getFeatureImportance } from '$lib/api';
  import type { FeatureImportanceEntry } from '$lib/api';

  let features = $state<FeatureImportanceEntry[]>([]);
  let loading  = $state(true);
  let animated = $state(false);

  const LABELS: Record<string, string> = {
    norm_pH: 'Odds local',        norm_pD: 'Odds empate',       norm_pA: 'Odds visit.',
    odds_spread: 'Spread cuotas', elo_diff: 'Δ ELO',            elo_exp_home: 'ELO prob. local',
    elo_home: 'ELO local',        elo_away: 'ELO visitante',
    diff_avg_Pts: 'Δ Pts/j',      diff_avg_GF: 'Δ Goles',       diff_avg_GA: 'Δ G.enc.',
    diff_avg_GD: 'Δ GD',          diff_avg_SoT: 'Δ SoT',        diff_avg_shots: 'Δ Tiros',
    diff_avg_corners: 'Δ Corners',
    home_avg_Pts: 'Pts local',    away_avg_Pts: 'Pts visit.',
    home_avg_GF: 'Gol loc.',      away_avg_GF: 'Gol vis.',
    home_avg_GF_h: 'Gol loc.(H)', away_avg_GF_a: 'Gol vis.(A)',
    h2h_home_win_pct: 'H2H loc.', h2h_away_win_pct: 'H2H vis.',
    home_streak: 'Racha loc.',    away_streak: 'Racha vis.',
    home_win_rate_5: 'WR5 loc.',  away_win_rate_5: 'WR5 vis.',
    home_shot_eff: 'ShotEff loc.',away_shot_eff: 'ShotEff vis.',
    home_avg_xG_proxy: 'xG loc.', away_avg_xG_proxy: 'xG vis.',
    diff_avg_xG_proxy: 'Δ xG',
    rest_home: 'Descanso loc.',   rest_away: 'Descanso vis.',   rest_diff: 'Δ Descanso',
  };

  onMount(async () => {
    try { features = await getFeatureImportance(10); }
    catch { /* not ready */ }
    finally {
      loading = false;
      setTimeout(() => { animated = true; }, 80);
    }
  });

  const maxImp = $derived(features.length > 0 ? features[0].importance : 1);
</script>

<div class="card fi">
  <div class="hdr">
    <span class="title">IMPORTANCIA FEATURES</span>
    <span class="badge">XGBoost</span>
  </div>

  {#if loading}
    <div class="skels">
      {#each { length: 8 } as _}<div class="skel"></div>{/each}
    </div>
  {:else if features.length === 0}
    <p class="empty">No disponible</p>
  {:else}
    <div class="list">
      {#each features as f, i}
        {@const pct = (f.importance / maxImp * 100).toFixed(1)}
        {@const isTop = i === 0}
        <div class="row" class:top-feat={isTop}>
          <span class="num" class:num-top={isTop}>{i + 1}</span>
          <div class="info">
            <div class="top">
              <span class="name" class:name-top={isTop}>{LABELS[f.feature] ?? f.feature}</span>
              <span class="val" class:val-top={isTop}>{(f.importance * 100).toFixed(1)}</span>
            </div>
            <div class="track">
              <div
                class="fill"
                class:fill-vis={animated}
                class:fill-top={isTop}
                style="--target-w:{pct}%; --delay:{i * 45}ms; opacity:{1 - i * 0.07}"
              ></div>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
.fi { padding: 0; display: flex; flex-direction: column; overflow: hidden; }
.hdr {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(0,201,107,.04) 0%, transparent 100%);
}
.title {
  font-size: 9px; font-weight: 800; color: var(--text2);
  text-transform: uppercase; letter-spacing: .1em;
}
.badge {
  font-size: 9px; font-weight: 700; color: var(--amber);
  padding: 2px 8px; border: 1px solid rgba(245,166,35,.25); border-radius: 99px;
  background: rgba(245,166,35,.08); letter-spacing: .05em;
}
.empty { font-size: 11px; color: var(--text3); padding: 14px; }
.skels { display: flex; flex-direction: column; gap: 0; padding: 10px 14px; }
.skel { height: 20px; background: var(--bg3); margin-bottom: 6px; border-radius: var(--radius-xs); animation: sk 1.5s ease-in-out infinite; }
@keyframes sk { 0%,100% { opacity: .2; } 50% { opacity: .5; } }

.list { display: flex; flex-direction: column; padding: 10px 14px; gap: 7px; }
.row { display: grid; grid-template-columns: 18px 1fr; align-items: center; gap: 7px; }
.row.top-feat { background: rgba(0,201,107,.04); border-radius: var(--radius-sm); padding: 4px; margin: -4px; }
.num { font-size: 9px; color: var(--text3); text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }
.num.num-top { color: var(--accent); }
.info { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.top { display: flex; justify-content: space-between; align-items: baseline; }
.name { font-size: 10.5px; font-weight: 600; color: var(--text2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0; }
.name.name-top { color: var(--text); font-weight: 700; }
.val { font-size: 10px; font-weight: 800; color: var(--text3); font-variant-numeric: tabular-nums; flex-shrink: 0; padding-left: 6px; }
.val.val-top {
  background: linear-gradient(135deg, var(--green), var(--amber));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.track { height: 3px; background: var(--bg5); border-radius: 99px; overflow: hidden; }
.fill {
  height: 100%; width: 0; border-radius: 99px;
  background: linear-gradient(90deg, var(--green2), var(--amber));
  transition: width .6s cubic-bezier(.4,0,.2,1);
  transition-delay: var(--delay, 0ms);
}
.fill.fill-vis { width: var(--target-w); }
.fill.fill-top {
  background: linear-gradient(90deg, var(--green), var(--amber));
  box-shadow: 0 0 6px rgba(0,201,107,.4);
}
</style>
