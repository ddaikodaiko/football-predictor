# Roadmap

## Estado (28-09-2026)

| Fase | Qué | Estado |
|------|-----|--------|
| 1. Datos | SQLite local (`backend/store.py`) + ingesta (`backend/ingest.py`) | **hecho** |
| 2. Modelo honesto | Dixon-Coles por máxima verosimilitud (`ratings.py`) + backtest walk-forward contra el mercado (`backtest.py`) | **hecho** |
| 3. Simuladores | temporada, partido minuto a minuto y apuestas (`simulate.py`) | **hecho** (falta torneos) |
| 4. API | `api.py` + `engine.py` sobre la base local; arranca en ~2,5 s | **hecho** |
| 5. UI | partidos, liga (pronóstico, clasificación, fuerzas), partido (simulador y directo), modelo, directo | **hecho** |
| 6. Publicar | README con resultados hecho; faltan capturas y despliegue | pendiente |

## Datos

95.341 partidos: 12 ligas (las 5 grandes + sus segundas + Eredivisie + Primeira) desde
2005/06, con tiros, córners, tarjetas y cuotas (Bet365, media del mercado, Pinnacle y
cierre). xG por partido de Understat en las 5 grandes desde 2014/15 (~22.000 partidos) y
de football-data.co.uk en todas desde 2026/27. Calendario pendiente de las 5 grandes.

Los nombres de equipo de Understat se cruzan con los de football-data **aprendiendo el
emparejamiento de los propios partidos** (mismo día, mismo marcador): 100 % de cruce en
todas las temporadas probadas.

## Resultado del backtest (lo importante)

Walk-forward 2016/17-2025/26, 5 grandes ligas, 17.937 partidos. El modelo se reajusta cada
semana solo con el pasado. Log loss, menos es mejor:

| | log loss | RPS |
|---|---|---|
| Base (frecuencias 1X2) | 1,0700 | — |
| Dixon-Coles, solo goles | 0,9832 | 0,2000 |
| **Dixon-Coles, 50 % goles + 50 % xG** | **0,9793** | **0,1986** |
| Dixon-Coles, solo xG | 0,9824 | 0,1996 |
| Pinnacle, cuota de cierre | 0,9626 | 0,1937 |

- El modelo cubre el ~84 % de la distancia entre no saber nada y el mercado más afinado.
  **No gana al mercado**, y la diferencia es uniforme (no se concentra en ascendidos ni en
  principio de temporada): es lo que sabe el mercado y el modelo no (bajas, alineaciones,
  fichajes).
- **Está bien calibrado**: agrupado por su propia probabilidad, lo que dice que pasa el 25 %
  pasa el 25,5 %, y así en todo el rango. Una capa de calibración walk-forward empeoraba
  el resultado y se quitó. (Agrupar por la cuota del mercado parece mostrar que
  infravalora a los favoritos, pero es sesgo de selección.)
- Parámetros medidos: decaimiento temporal ξ = 0,003/día (probados 0,001-0,005), prior
  σ = 1 (probados 0,5-2). Las diferencias son del orden del ruido.

## Apuestas: no hay ventaja

`simulate.py betting` repite las 10 temporadas apostando cuando modelo × cuota > 1 + margen,
con la cuota media previa al partido (no la de cierre, que no se puede coger):

- Margen 2-20 %: **ROI entre −11 % y −16 %**, y solo el 31 % de las apuestas bate la cuota
  de cierre (CLV medio −3,6 a −4 %).
- Apostar a todo pierde −6,4 % (el margen de la casa es 4,9 %): el simulador está bien.
- El modelo ve "valor" sobre todo en cuotas altas (5-7), justo donde el sesgo favorito-
  tapado hace perder más.

**Consecuencia para el módulo de ejecución de abajo:** la premisa (detectar edge contra
Polymarket o las casas) no se sostiene con este modelo. No tiene sentido construir alertas
de apuestas sobre él. Si algún día el modelo incorpora bajas y alineaciones, se vuelve a
medir con el mismo backtest antes de nada.

## ¿Se puede batir a las casas? (28-09-2026, `backend/edge.py`)

Objetivo del proyecto: competir con los modelos de las casas. Medido en 12 ligas desde
2019/20 (30.973 partidos), tres mercados, con la métrica profesional: **valor esperado de
cada apuesta bajo la probabilidad justa de cierre** (CLV), que no depende de la suerte.

**El modelo no tiene ventaja en ningún sitio.**

| Mercado | EV vs cierre (todas las ligas) | t | Ganancia de información sobre el mercado previo |
|---|---|---|---|
| 1X2 | −6,5 % | −99 | +0,0002 (nula) |
| Más/menos 2,5 | −5,2 % | −100 | +0,0002 (nula) |
| Hándicap asiático | −3,6 % | −35 | — |

- Negativo en las 12 ligas y los 3 mercados. Las segundas divisiones **no** son más blandas
  para este modelo (peores, de hecho).
- Combinar modelo + cuota previa predice igual que la cuota previa sola (0,9678 contra
  0,9674): el mercado ya incorpora todo lo que sabe el modelo.
- Mejoras del modelo medidas: ajuste conjunto con la segunda división 0,9793 → **0,9786**
  (activado); ventana de 2 o 5 años y ξ entre 0,001 y 0,005, dentro del ruido.

**Casa afilada contra blandas** (la probabilidad de Pinnacle como verdad, apostar donde
otra casa paga más):

- 2019-2026: contra la cuota máxima, EV vs cierre +4 % (t = +33) pero **ROI real −1 %**;
  contra Bet365, EV +1,8 % (t = +6) y ROI +9,5 % en 1.836 apuestas.
- 2024-2026: contra Bet365, EV +0,6 % (t = 0,8): ya no hay nada. Contra la máxima, ROI de
  −5 % a −24 %: esas cuotas máximas no se pueden coger de verdad.
- Pinnacle ya no aparece en football-data desde 2026/27; Betfair exchange como referencia
  no da ventaja contra Bet365 (EV −6 %).

**Qué haría falta para competir de verdad** (ninguna es gratis y sin cuenta):
cuotas en tiempo real de muchas casas para comprar el mejor precio al momento, alineaciones y
bajas antes que el mercado, y cuotas de apertura (las que se corrigen después). Con datos
públicos, el techo realista es lo que hay: probabilidades al ~85 % del mercado y bien
calibradas.

## Pendiente

- [ ] **Capturas** para el README y **despliegue** (necesita un sitio para la API Python y la base de ~90 MB).
- [ ] **Torneos** (Champions): necesita un rating común entre ligas. ClubElo
      (api.clubelo.com) lo da gratis, pero el 28-09-2026 devolvía 502.
- [ ] **Bajas y alineaciones**: no hay fuente gratuita fiable sin clave. API-Football
      (100 peticiones/día gratis) es la opción; hace falta registrarse.
- [ ] Puntuar las predicciones guardadas (tabla `predictions`, se llenan al pedir próximos
      partidos) cuando se jueguen, y enseñarlo en la web: el modelo medido en vivo.

## Módulo de ejecución (idea de 2026-06-10, en suspenso)

Idea fusionada de polymarket-empire: alertas cuando el modelo detecte edge contra
Polymarket, tracker de posiciones hipotéticas y, si hubiera edge sostenido, ejecución.
**En suspenso por el resultado del backtest de arriba.**
