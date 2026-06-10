# Roadmap

## Módulo de ejecución (idea fusionada de polymarket-empire, 2026-06-10)

El predictor ya consume la Gamma API de Polymarket como capa de odds. El antiguo
proyecto `polymarket-empire` (archivado en `Proyectos/_archive/polymarket-empire/`)
era el canal de ejecución/monetización de esa misma señal. Fusión propuesta:

1. **Alertas** — portar el Telegram alert bot (`_archive/polymarket-empire/telegram-bot/`)
   para que dispare cuando el modelo detecte edge entre su probabilidad y el
   precio de Polymarket (umbral configurable, p.ej. >5%).
2. **Tracker** — los scripts Python del toolkit sirven de base para registrar
   posiciones hipotéticas y medir el edge real del modelo a lo largo del tiempo
   (backtest vivo, sin dinero real).
3. **Decisión pendiente** — solo si el backtest vivo demuestra edge sostenido
   durante ≥1 temporada: considerar ejecución real o publicar la señal como
   producto (la dirección eBook/contenido del empire queda descartada).

## Pendiente técnico

- [ ] Persistir predicciones históricas para poder backtestear (ahora son efímeras)
- [ ] Endpoint `/api/edge` que compare prob. modelo vs precio Polymarket
- [ ] Bot de alertas conectado a ese endpoint
