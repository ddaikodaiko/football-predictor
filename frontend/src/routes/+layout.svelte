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
    <a href="{base}/" class="brand" aria-label="Football Predictor, inicio">
      <!-- La marca es la barra 1X2 de la web: local, empate, visitante. -->
      <svg class="mark" viewBox="0 0 22 14" aria-hidden="true">
        <rect x="0" y="0" width="10" height="14" rx="1.5" fill="var(--home)" />
        <rect x="11.5" y="0" width="4" height="14" rx="1.5" fill="var(--draw)" />
        <rect x="17" y="0" width="5" height="14" rx="1.5" fill="var(--away)" />
      </svg>
      <span>Football Predictor</span>
    </a>
    <div class="links">
      {#each links as l}
        <a href="{base}{l.href}" class:on={active(l)} aria-current={active(l) ? 'page' : undefined}>{l.label}</a>
      {/each}
    </div>
  </nav>
</header>

<main>{@render children()}</main>

<footer>
  Datos: football-data.co.uk (resultados y cuotas) y Understat. Modelo Dixon-Coles sobre los precios de los
  partidos ya jugados, medido contra el mercado en
  <a href="{base}/modelo">El modelo</a>. No es consejo de apuestas: el modelo no le gana a las casas.
</footer>

<style>
  header {
    position: sticky; top: env(safe-area-inset-top, 0px); z-index: 10;
    background: color-mix(in srgb, var(--bg) 86%, transparent); backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border);
  }
  nav { max-width: 1180px; margin: 0 auto; padding: 0 16px; min-height: 58px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .brand { display: inline-flex; align-items: center; gap: 10px; white-space: nowrap; }
  .brand span { font-family: var(--display); font-weight: 800; font-size: 21px; text-transform: uppercase; letter-spacing: .02em; line-height: 1; }
  .mark { width: 22px; height: 14px; flex: none; }
  .links { display: flex; gap: 2px; min-width: 0; overflow-x: auto; scrollbar-width: none; }
  .links::-webkit-scrollbar { display: none; }
  .links a { position: relative; padding: 18px 12px; color: var(--text2); font-weight: 500; font-size: 13.5px; white-space: nowrap; }
  .links a:hover { color: var(--text); }
  .links a.on { color: var(--text); }
  .links a.on::after { content: ''; position: absolute; left: 12px; right: 12px; bottom: -1px; height: 2px; background: var(--accent); }
  /* Móvil: la marca arriba y los enlaces en su propia fila, desplazable si no caben. */
  @media (max-width: 640px) {
    nav { flex-direction: column; align-items: stretch; gap: 0; padding-top: 12px; }
    .links { margin: 0 -16px; padding: 0 4px; mask-image: linear-gradient(90deg, #000 85%, transparent); }
    .links a { padding: 12px 12px 14px; }
  }
  main { min-height: calc(100vh - 140px); }
  footer { max-width: 1180px; margin: 0 auto; padding: 24px 16px 40px; color: var(--text3); font-size: 12px; line-height: 1.6; border-top: 1px solid var(--border); }
  footer a { color: var(--text2); text-decoration: underline; text-underline-offset: 2px; }
</style>
