<script lang="ts">
  import { onMount } from 'svelte';
  import type { EloEntry } from '$lib/api';
  let { entries }: { entries: EloEntry[] } = $props();

  const max = $derived(entries.length > 0 ? Math.max(...entries.map(e => e.elo)) : 1600);
  const min = $derived(entries.length > 0 ? Math.min(...entries.map(e => e.elo)) : 1400);

  let animated = $state(false);
  onMount(() => {
    const t = setTimeout(() => { animated = true; }, 80);
    return () => clearTimeout(t);
  });
</script>

<div class="card elo">
  <div class="hdr">
    <span class="title">CLASIFICACIÓN ELO</span>
    <span class="badge">TOP {entries.length}</span>
  </div>
  <div class="list">
    {#each entries as e, i}
      {@const pct = (e.elo - min) / Math.max(max - min, 1) * 100}
      {@const isTop = i < 3}
      <div class="row" class:top={isTop}>
        <span class="rank" class:r1={i===0} class:r2={i===1} class:r3={i===2}>{i + 1}</span>
        <div class="info">
          <div class="top-row">
            <span class="team">{e.team}</span>
            <span class="elo-val" class:elo-hi={isTop}>{e.elo}</span>
          </div>
          <div class="track">
            <div
              class="fill"
              class:fill-vis={animated}
              style="--target-w:{pct.toFixed(1)}%; --delay:{i * 35}ms"
            ></div>
          </div>
        </div>
      </div>
    {/each}
  </div>
</div>

<style>
.elo { padding: 0; display: flex; flex-direction: column; overflow: hidden; }
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
  font-size: 9px; font-weight: 700; color: var(--green);
  padding: 2px 8px; border: 1px solid rgba(0,201,107,.25); border-radius: 99px;
  background: rgba(0,201,107,.08); letter-spacing: .05em;
}

.list { display: flex; flex-direction: column; }
.row {
  display: grid; grid-template-columns: 28px 1fr;
  align-items: center; gap: 8px;
  padding: 8px 16px; border-bottom: 1px solid var(--border);
  transition: background .15s;
}
.row:last-child { border-bottom: none; }
.row:hover { background: rgba(0,201,107,.04); }
.row.top { background: rgba(0,201,107,.03); }

.rank {
  font-size: 11px; font-weight: 800; text-align: center;
  color: var(--text3); font-variant-numeric: tabular-nums;
}
.rank.r1 { color: var(--amber); text-shadow: 0 0 8px rgba(251,191,36,.5); }
.rank.r2 { color: var(--text2); }
.rank.r3 { color: var(--text3); }

.info { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.top-row { display: flex; align-items: baseline; justify-content: space-between; gap: 6px; }
.team {
  font-size: 11.5px; font-weight: 700;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1;
}
.elo-val {
  font-size: 11px; font-weight: 800; color: var(--text2);
  font-variant-numeric: tabular-nums; flex-shrink: 0;
}
.elo-val.elo-hi {
  background: linear-gradient(135deg, var(--green), var(--blue));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.track { height: 3px; background: var(--bg5); border-radius: 99px; overflow: hidden; }
.fill {
  height: 100%; width: 0; border-radius: 99px;
  background: linear-gradient(90deg, var(--green2), var(--blue));
  transition: width .6s cubic-bezier(.4,0,.2,1);
  transition-delay: var(--delay, 0ms);
}
.fill.fill-vis { width: var(--target-w); }
.row.top .fill {
  background: linear-gradient(90deg, var(--green), var(--blue));
  box-shadow: 0 0 8px rgba(0,201,107,.4);
}
</style>
