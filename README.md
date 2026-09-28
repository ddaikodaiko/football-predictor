# Football Predictor

Probabilidades de partidos de fútbol con un modelo **Dixon-Coles con xG**, simulación de
temporadas completas y un backtest honesto contra las casas de apuestas.

- **95.000 partidos** de 12 ligas europeas desde 2005/06, con xG por partido de las cinco
  grandes desde 2014.
- **Medido de verdad**: 10 temporadas, semana a semana, prediciendo cada jornada solo con el
  pasado. El modelo cubre el **85 %** de la distancia entre no saber nada y la cuota de cierre
  de Pinnacle, y está bien calibrado. **No le gana al mercado**, y el README lo dice.
- **Simuladores**: la temporada que queda (10.000 veces en medio segundo), un partido minuto
  a minuto y las probabilidades en directo según el marcador.

## Resultados

Walk-forward 2016/17 – 2025/26, cinco grandes ligas, 17.937 partidos. Log loss, menos es mejor:

| | log loss | RPS |
|---|---|---|
| Sin modelo (frecuencias 1X2) | 1,0700 | — |
| **Dixon-Coles, 50 % goles + 50 % xG** | **0,9793** | **0,1986** |
| Pinnacle, cuota de cierre | 0,9626 | 0,1937 |

- **Calibración**: agrupando por la probabilidad del modelo, lo que dice que pasa el 25 % pasa
  el 25,5 %, y así en todo el rango.
- **Apuestas**: apostar cuando el modelo ve valor, a cuota media previa al partido, pierde entre
  un 11 % y un 14 % en 10 temporadas (apostar a todo pierde el 6 %, el margen de la casa). Solo
  el 32 % de esas apuestas bate la cuota de cierre. La diferencia con el mercado es información
  que el modelo no tiene: bajas, alineaciones, fichajes.

Todo el detalle, con gráficos, en la página **El modelo** de la app.

## Cómo funciona

1. **Datos** (`backend/ingest.py`): resultados, tiros, tarjetas y cuotas (Bet365, media del
   mercado, Pinnacle y cierre) de [football-data.co.uk](https://www.football-data.co.uk), y
   xG de [Understat](https://understat.com). Los nombres de equipo de las dos fuentes se
   emparejan **aprendiendo de los propios partidos** (mismo día, mismo marcador): 100 % de cruce.
   Todo queda en una SQLite local.
2. **Modelo** (`backend/ratings.py`): cada equipo tiene ataque y defensa; los goles son
   Poisson con la corrección de Dixon & Coles (1997) para marcadores bajos. Se ajusta por máxima
   verosimilitud con gradiente analítico sobre los últimos tres años, pesando más lo reciente
   (vida media ~8 meses), mezclando goles y xG, y con un prior ridge para equipos con pocos
   partidos. Un ajuste tarda 0,02 s.
3. **Backtest** (`backend/backtest.py`): reajuste semanal solo con el pasado, comparado con las
   probabilidades del mercado sin margen. Un test comprueba que cambiar un resultado futuro no
   altera ninguna predicción anterior.
4. **Simuladores** (`backend/simulate.py`): temporada completa vectorizada con desempates por
   diferencia de goles, partido minuto a minuto y repetición de apuestas con CLV.
5. **API** (`backend/api.py` + `engine.py`, FastAPI) y **web** (`frontend/`, SvelteKit 2 +
   Svelte 5, gráficos en SVG sin librerías).

## Arrancar

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend
../.venv/bin/python ingest.py                  # ~5 min la primera vez, luego usa la caché
../.venv/bin/python backtest.py --xg 0.5       # ~1 min, alimenta la página "El modelo"
../.venv/bin/python -m uvicorn api:app --port 8000

cd ../frontend && bun install && bun run dev   # http://localhost:5173
```

Marcadores en directo: clave gratuita de [football-data.org](https://www.football-data.org) en
`backend/.env` como `FOOTBALL_DATA_KEY=...`. Actualizar datos: `python ingest.py --refresh`
y `POST /api/reload`.

Tests: `cd backend && ../.venv/bin/python -m pytest -q` (24 tests, sin red).

## API

| Método | Ruta | Qué devuelve |
|---|---|---|
| GET | `/api/leagues` | ligas disponibles |
| GET | `/api/leagues/{code}/table` | clasificación actual con forma |
| GET | `/api/leagues/{code}/ratings` | ataque, defensa y balance de cada equipo |
| GET | `/api/leagues/{code}/fixtures?limit=10` | próximos partidos con probabilidades (se guardan para medir el modelo en vivo) |
| GET | `/api/leagues/{code}/forecast` | temporada simulada: puntos esperados, campeón, top 4, descenso y probabilidad de cada puesto |
| POST | `/api/predict` | un partido: 1X2, mercados, matriz de marcadores, forma con xG, H2H |
| POST | `/api/predict/inplay` | probabilidades desde un marcador y un minuto |
| POST | `/api/simulate/match` | un partido simulado minuto a minuto |
| GET | `/api/backtest` | resumen del backtest |
| GET | `/api/live` | partidos de hoy (football-data.org) |

Lo pendiente está en [ROADMAP.md](ROADMAP.md).
