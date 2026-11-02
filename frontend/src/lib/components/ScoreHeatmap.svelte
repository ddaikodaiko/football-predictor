<script lang="ts">
  import { heat } from '$lib/format';

  let { matrix, home, away }: { matrix: number[][]; home: string; away: string } = $props();
  const max = $derived(Math.max(...matrix.flat()));
</script>

<div class="wrap">
  <div class="axis-top">{away} marca →</div>
  <div class="axis-left">{home} marca →</div>
  <table>
    <thead>
      <tr><th></th>{#each matrix[0] as _, j}<th>{j}</th>{/each}</tr>
    </thead>
    <tbody>
      {#each matrix as row, i}
        <tr>
          <th>{i}</th>
          {#each row as p, j}
            <td style={heat(p, max, i > j ? 'home' : i < j ? 'away' : 'draw')}
                title="{home} {i}-{j} {away}: {(p * 100).toFixed(1)}%">
              {(p * 100).toFixed(p >= 0.1 ? 0 : 1)}
            </td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .wrap { display: grid; grid-template-columns: auto 1fr; grid-template-rows: auto 1fr; gap: 4px 6px; }
  .axis-top { grid-column: 2; font-size: 11px; color: var(--text3); text-align: center; }
  .axis-left { grid-row: 2; writing-mode: vertical-rl; transform: rotate(180deg); font-size: 11px; color: var(--text3); text-align: center; }
  table { border-collapse: separate; border-spacing: 3px; width: 100%; font-variant-numeric: tabular-nums; }
  th { font-size: 11px; color: var(--text3); font-weight: 700; }
  td { text-align: center; font-size: 12px; font-weight: 600; padding: 8px 0; border-radius: 3px; }
</style>
