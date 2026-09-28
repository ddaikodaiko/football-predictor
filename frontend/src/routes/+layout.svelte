<script lang="ts">
  import { base } from '$app/paths';
  import '../app.css';
  import favicon from '$lib/assets/favicon.svg';
  import { page } from '$app/state';
  import { STATIC } from '$lib/api';

  let { children } = $props();

  // Valor and Directo need the live server (odds and scores): not in the static demo.
  const links = [
    { href: '/', label: 'Partidos' },
    { href: '/liga/SP1', label: 'Ligas', match: '/liga' },
    { href: '/valor', label: 'Valor', live: true },
    { href: '/modelo', label: 'El modelo' },
    { href: '/directo', label: 'Directo', live: true },
  ].filter((l) => !(STATIC && l.live));
  const path = $derived(page.url.pathname.slice(base.length) || '/');
  const active = (l: (typeof links)[number]) => (l.match ? path.startsWith(l.match) : path === l.href);
</script>

<svelte:head>
  <link rel="icon" href={favicon} />
  <title>Football Predictor</title>
</svelte:head>

<header>
  <nav>
    <a href="{base}/" class="brand">⚽ <span>Football Predictor</span></a>
    <div class="links">
      {#each links as l}
        <a href="{base}{l.href}" class:on={active(l)}>{l.label}</a>
      {/each}
    </div>
  </nav>
</header>

<main>{@render children()}</main>

<footer>
  Datos: football-data.co.uk y Understat. Modelo Dixon-Coles con xG, medido contra el mercado en
  <a href="{base}/modelo">El modelo</a>. No es consejo de apuestas: el modelo no le gana a las casas.
</footer>

<style>
  header { position: sticky; top: 0; z-index: 10; background: rgba(16,20,29,.85); backdrop-filter: blur(10px); border-bottom: 1px solid var(--border); }
  nav { max-width: 1180px; margin: 0 auto; padding: 0 16px; height: 56px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .brand { font-weight: 800; font-size: 16px; letter-spacing: -0.01em; white-space: nowrap; }
  .links { display: flex; gap: 2px; overflow-x: auto; }
  .links a { padding: 8px 12px; border-radius: 8px; color: var(--text2); font-weight: 600; white-space: nowrap; }
  .links a:hover { color: var(--text); }
  .links a.on { color: var(--text); background: var(--bg3); }
  @media (max-width: 560px) { .brand span { display: none; } }
  main { min-height: calc(100vh - 140px); }
  footer { max-width: 1180px; margin: 0 auto; padding: 24px 16px 40px; color: var(--text3); font-size: 12px; border-top: 1px solid var(--border); }
  footer a { color: var(--text2); text-decoration: underline; }
</style>
