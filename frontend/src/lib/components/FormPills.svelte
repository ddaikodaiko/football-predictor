<script lang="ts">
  let { results }: { results: ('W' | 'D' | 'L')[] } = $props();
  const label = { W: 'V', D: 'E', L: 'D' } as const;
  const title = { W: 'Victoria', D: 'Empate', L: 'Derrota' } as const;
</script>

<span class="form">
  {#each results as r}
    <span class="p {r}" title={title[r]}>{label[r]}</span>
  {/each}
</span>

<style>
  .form { display: inline-flex; gap: 3px; }
  .p { width: 18px; height: 18px; border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 800; color: var(--bg); }
  .W { background: var(--good); }
  .D { background: var(--draw); }
  .L { background: var(--bad); }
</style>
