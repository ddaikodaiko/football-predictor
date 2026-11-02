# Roadmap

## Estado (14-10-2026)

| Fase | Qué | Estado |
|------|-----|--------|
| 1. Datos | SQLite local (`backend/store.py`) + ingesta (`backend/ingest.py`) | **hecho** |
| 2. Modelo honesto | Dixon-Coles por máxima verosimilitud (`ratings.py`) sobre los precios de los partidos ya jugados (`market.py`) + backtest walk-forward contra el mercado (`backtest.py`) | **hecho** |
| 3. Simuladores | temporada, partido minuto a minuto, apuestas (`simulate.py`), córners y tiros (`props.py`) | **hecho** (falta torneos) |
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

> Desde el 14-10-2026 el modelo en producción aprende de los precios de los partidos ya
> jugados: **0,9705**, el 92,6 % del camino (ver *Precios pasados como señal*). Lo de esta
> sección es el modelo de goles y xG, que sigue siendo la referencia sin mercado.

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
calibradas. (El 14-10-2026 subió al 92,6 % aprendiendo de los precios de los partidos ya
jugados: ver *Precios pasados como señal*.)

## Con cuentas (28-09-2026): The Odds API y API-Football

**Detector de valor en vivo** (`backend/odds_live.py`, página *Valor*). The Odds API trae
~19 casas con Pinnacle y el exchange de Betfair para las 12 ligas. Cada consulta se guarda
(el camino entero de cada cuota hasta el cierre); la probabilidad justa sale de Pinnacle
sin margen por el **método de potencia** (el proporcional sobrevalora a los tapados:
medido en cierres, 13,74 % contra 13,05 % real; potencia 13,46 %). Cada precio con valor
se registra y se puntúa contra el cierre: es la única prueba de ventaja que vale. Primera
consulta: 59 precios con valor a 12 días vista. **El CLV aún no se puede medir**: hacen falta
consultas cerca del partido. Presupuesto: 15 créditos por consulta de las 5 grandes;
500 al mes dan para ~4 consultas por semana.

**Bajas** (`backend/injuries.py`). API-Football gratis solo da 2022-2024, no la temporada
actual. Experimento: importancia de cada baja con Understat de la temporada anterior
(xG + xA; minutos de defensas y porteros), ajustando los goles esperados. 65 % de las bajas
emparejadas (el resto, casi todo fichajes y canteranos). Resultado en 2024/25: log loss
0,9782 → **0,9789** (peor) y ninguna ganancia frente al mercado. La lista de bajas
anunciadas ya está en el precio: **no merece la pena pagar el plan de API-Football** para
esto. Lo que podría servir es la alineación confirmada (1 h antes), que es otra cosa.

## Precios pasados como señal (14-10-2026, `backend/market.py`)

La diferencia con el mercado era información que el modelo no tenía: bajas, alineaciones,
fichajes. Esa información está en los **precios de los partidos ya jugados**. Cada cuota
(1X2 y más/menos 2,5, sin margen por el método de potencia) se convierte en los dos goles
esperados que la reproducen con el mismo Dixon-Coles (mínimos cuadrados en una rejilla de
700×700 λ; error mediano 0,16 % en ida y vuelta), y el ajuste aprende de ellos igual que de
los goles y el xG. Un partido nunca ve su propia cuota: el ajuste solo usa partidos
anteriores al corte (`tests/test_market.py` lo comprueba alterando el último precio).

Walk-forward 2016/17-2025/26, cinco grandes, 17.937 partidos, log loss:

| | log loss | RPS |
|---|---|---|
| Goles + xG (el modelo anterior) | 0,9785 | 0,1985 |
| 25-50 % de precios dentro de ese ajuste | 0,9768-0,9770 | 0,1980 |
| Solo precios, vida media ~10 semanas, prior σ = 1 | 0,9751 | — |
| Solo precios, vida media ~3 semanas, prior σ = 2 | 0,9720 | — |
| **Solo precios, vida media ~3 semanas (ξ = 0,03), prior σ = 10** | **0,9705** | **0,1961** |
| Pinnacle, cuota de cierre | 0,9626 | 0,1937 |

- Cubre el **92,6 %** de la distancia entre no saber nada y el cierre (antes, 85,1 %).
  Mejora en las 10 temporadas y en las 5 ligas.
- Lo que más pesaba era el **prior**: con un decaimiento rápido queda poco peso de datos y
  el prior σ = 1 aplastaba los ratings. ξ entre 0,03 y 0,04 con σ ≥ 10 da 0,9704-0,9705;
  ξ = 0,1 (vida media de una semana) empeora a 0,9737.
- **Goles y xG ya no aportan**: mezclados en el ajuste empeoran, y una media logarítmica con
  el modelo anterior (peso ajustado solo con temporadas pasadas) da 0,9744 contra 0,9743.
  El precio de la semana pasada ya contiene lo que saben.
- **Más/menos 2,5**: 0,6768 → **0,6721** (cierre: 0,6688). Invertir solo con el 1X2 da lo
  mismo en 1X2 y peor en goles (0,6752), así que se usan los dos precios.
- Contra la cuota media publicada días antes (17.079 partidos con las dos): modelo 0,9690,
  media previa 0,9638, cierre 0,9610. Lo que queda es lo que se sabe la semana del partido.
- **Sigue sin ganar dinero**: apostando con un 5 % de valor a cuota media previa, ROI
  −10,2 % (antes −12,8 %) y el 36 % de las apuestas bate el cierre (antes 32 %).
- Probado y descartado: corregir el empate según lo igualado del partido. El modelo da pocos
  empates en partidos igualados (28,2 % contra 29,3 % real) y demasiados en los
  desequilibrados (14,9 % contra 13,7 %), pero corregirlo con temporadas pasadas mejora
  0,0002 con el modelo anterior y nada con el nuevo.

- **Abierto**: dos grandes cara a cara. Con los dos goles esperados por encima de 1,4 calibra
  bien (737 partidos: modelo 3,18 goles, mercado 3,16, reales 3,20; el de goles y xG daba 3,22
  contra 3,04). Por encima de 1,7 solo hay 21 partidos (modelo 3,63, mercado 3,53, reales 3,29):
  pocos para corregir nada, pero un Madrid-Barça sale a 4,0 goles esperados, que parece alto.
- **Límite conocido: diferencias exageradas en partidos muy desequilibrados.** Para casar una
  cuota de 1,05 un Poisson necesita una diferencia de ~3 goles; en la realidad el que va
  ganando levanta el pie. Con diferencia esperada > 2,5 (360 partidos) el modelo espera 2,90,
  el cierre leído con el mismo Poisson 2,76 y la real fue 2,38; el favorito gana el 84,2 % y
  el modelo dice 88,8 %. Comprimir la diferencia manteniendo el total empeora el log loss en
  todo el rango probado (0,9705 → 0,9754), así que no se corrige. Efecto visible: la
  simulación de temporada infla la diferencia de goles de los dominantes (Barça 2026/27, tras
  8 de 8: +93 esperada, récord histórico; el modelo de goles y xG decía +76).

Reproducir: `python backtest.py --joint --xg 0 --market 1 --market-xi 0.03 --prior 10 --name dc_market`
(~2 min). Varias configuraciones se pueden lanzar en paralelo: el backtest usa un hilo de BLAS.

## Córners y tiros a puerta (29-09-2026, `backend/props.py`)

Walk-forward 2017/18-2025/26, cinco grandes, 17.935 partidos. Log loss binomial negativa por
equipo y partido (menos es mejor):

| | córners | tiros a puerta |
|---|---|---|
| Media de la liga | 2,3837 | 2,2724 |
| Desde los goles esperados (modelo de goles y xG) | 2,3353 | 2,1840 |
| Desde los goles esperados (modelo de precios, 14-10-2026) | 2,3320 | 2,1736 |
| Ratings sobre los propios córners/tiros | 2,3318 | 2,1764 |
| Combinado (modelo de goles y xG) | 2,3256 | 2,1737 |
| **Combinado (modelo de precios)** | **2,3245** | **2,1688** |

- Calibración del total (más de 8,5 / 9,5 / 10,5 córners; 7,5 / 8,5 / 9,5 tiros): desvío menor
  de 3 puntos en todos los tramos con más de 1.000 partidos.
- Prior de los ratings: 0,15-0,3 igual de buenos; 0,6 y 1,0 peores por menos de 0,001.
- **Sin medir**: el reparto por mitades (se usa el de los goles, 45,8 % en la primera) y el
  mercado (football-data no trae cuotas de córners; The Odds API sí, en `alternate_totals_corners`).
- **Selecciones**: probado a mano con el España-Croacia del 29-09-2026 usando goles esperados
  sacados de Pinnacle; la parte "desde los goles esperados" daba 10,7 córners contra la línea
  de 9 de Pinnacle. Pasar de clubes a selecciones con un favorito tan claro sobreestima.

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
