# Football Predictor

Predictor de partidos de fútbol con cuatro capas de probabilidad: modelo ML · casas de apuestas · Polymarket · simulación Monte Carlo Poisson.

## Stack

| Capa | Tech |
|------|------|
| Backend | Python · FastAPI · XGBoost |
| Datos históricos | football-data.co.uk (libre, sin auth) |
| Fixtures live | football-data.org (free tier, API key) |
| Odds live | Polymarket Gamma API (libre, sin auth) |
| Frontend | SvelteKit · Bun |

## Estructura

```
football-predictor/
├── backend/
│   ├── model.py        # Pipeline ML: datos, features, ELO, H2H, entrenamiento, simulación Poisson
│   ├── api.py          # FastAPI: endpoints REST + interpretación automática
│   └── .env            # Variables de entorno (no commitear)
├── frontend/
│   └── src/
│       ├── lib/
│       │   ├── api.ts
│       │   └── components/
│       │       ├── MatchCard.svelte     # Cuatro capas + Monte Carlo + H2H + stats
│       │       ├── EloTable.svelte      # Rankings ELO sidebar
│       │       └── ModelStatus.svelte   # Estado del modelo en header
│       └── routes/+page.svelte          # Página principal
└── .gitignore
```

## Cómo arrancar

**Terminal 1 — Backend**
```bash
cd football-predictor/backend
python3 -m uvicorn api:app --reload --port 8000
```

Primera carga: descarga ~6 temporadas de SP1 + F1 + E0 y entrena el modelo. Tarda ~90 segundos.

**Terminal 2 — Frontend**
```bash
cd football-predictor/frontend
bun dev
```

Abre [http://localhost:5173](http://localhost:5173)

## Fixtures live (football-data.org)

Para cargar jornadas próximas automáticamente desde la API:

1. Regístrate en [football-data.org](https://www.football-data.org) (free tier)
2. Crea `backend/.env` con tu key:
   ```
   FOOTBALL_DATA_KEY=tu_key_aqui
   ```
3. Pulsa **📡 Próximas** en la UI — carga La Liga, Premier y Ligue 1 de los próximos 7 días

Sin key el botón sigue funcionando: muestra un aviso y cae back a las jornadas precargadas.

## API endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/status` | Estado del modelo y métricas de entrenamiento |
| `POST` | `/api/predict` | Predicción completa de un partido |
| `POST` | `/api/predict/batch` | Predicción de múltiples partidos |
| `GET` | `/api/matchdays` | Jornadas precargadas |
| `GET` | `/api/matchdays/upcoming?days_ahead=7` | Fixtures próximos via football-data.org |
| `GET` | `/api/elo?n=20` | Top N equipos por ELO |
| `GET` | `/api/teams` | Equipos disponibles por liga |

### Respuesta de `/api/predict`

```json
{
  "home": "Barcelona", "away": "Real Madrid",
  "p_home": 0.621, "p_draw": 0.214, "p_away": 0.165,
  "elo_home": 1842, "elo_away": 1856,
  "home_stats": { "avg_GF": 2.1, "avg_GA": 0.8, ... },
  "away_stats": { ... },
  "h2h": {
    "h2h_home_win_pct": 0.4, "h2h_draw_pct": 0.3, "h2h_away_win_pct": 0.3,
    "h2h_avg_goals_home": 1.8, "h2h_avg_goals_away": 1.4
  },
  "simulation": {
    "lambda_home": 1.82, "lambda_away": 1.24,
    "p_home": 0.518, "p_draw": 0.241, "p_away": 0.241,
    "over25": 0.67, "over15": 0.88, "btts": 0.71,
    "top_scores": [
      {"score": "2-1", "prob": 0.142},
      {"score": "1-0", "prob": 0.118},
      ...
    ]
  },
  "bookmaker": { "p_home": 0.601, "p_draw": 0.225, "p_away": 0.174 },
  "polymarket": { "question": "...", "prices": [...], "liquidity": 12000 },
  "analysis": {
    "verdict": "1", "confidence": "alta", "confidence_pct": 0.621,
    "key_factors": ["Barcelona llega con mejor forma...", ...]
  }
}
```

## Las cuatro capas

| Capa | Fuente | Señal |
|------|--------|-------|
| **ML** | XGBoost entrenado en históricos | Forma EWM + ELO + H2H + fatiga |
| **BK** | Bet365 normalizado (sin margen) | Consenso del mercado de apuestas |
| **PM** | Polymarket Gamma API | Mercado blockchain descentralizado |
| **MC** | Simulación Monte Carlo Poisson | Expected goals + distribución de marcadores |

Los badges `+X%` / `−X%` indican divergencia entre el modelo y cada fuente. Divergencia > 8% = señal de valor potencial.

## Simulación Monte Carlo

El botón **🎲 Monte Carlo** en cada card ejecuta 50.000 partidos simulados con distribución Poisson:

- **λ_home** = media entre goles marcados por el local en casa y goles encajados por el visitante fuera
- **λ_away** = media entre goles marcados por el visitante fuera y goles encajados por el local en casa
- Outputs: probabilidades 1/X/2, Over 2.5, Over 1.5, BTTS, top 6 marcadores con probabilidad

## Features del modelo

| Feature | Descripción |
|---------|-------------|
| `home/away_avg_GF/GA/SoT/Pts/GD` | EWM rolling span=6 por equipo (antes del partido) |
| `home_avg_GF_h / home_avg_GA_h` | Stats del local jugando en casa (EWM span=4) |
| `away_avg_GF_a / away_avg_GA_a` | Stats del visitante jugando fuera (EWM span=4) |
| `elo_home/away/diff` | ELO dinámico (K=32, home_adv=65, multiplicador por gol diff) |
| `elo_exp_home` | Probabilidad esperada por ELO |
| `h2h_home_win_pct/draw_pct/away_win_pct` | Últimos 5 enfrentamientos directos |
| `h2h_avg_goals_home/away` | Media de goles en H2H |
| `norm_pH/pD/pA` | Cuotas Bet365 sin margen bookmaker |
| `odds_spread` | Diferencia prob local − visitante |
| `rest_home/away/diff` | Días de descanso (proxy fatiga) |

## Datos

- **Fuente histórica**: [football-data.co.uk](https://www.football-data.co.uk) — libre, sin API key
- **Fuente fixtures**: [football-data.org](https://www.football-data.org) — free tier (10 req/min)
- **Ligas**: SP1 (La Liga) · F1 (Ligue 1) · E0 (Premier League)
- **Temporadas**: 2020/21 → 2025/26
- **Total partidos**: ~6.200

## Limitaciones

- **Accuracy ~51-53%** — techo práctico para predicción de fútbol con datos públicos
- **Cross-league**: para partidos entre equipos de distintas ligas (ej. Conference), el ELO y la simulación son más fiables que el ML puro
- **Polymarket football**: liquidez baja en liga regular; mejor señal en UCL/UEL/UECL
- **Equipos sin histórico**: equipos fuera de SP1/F1/E0 fallan con error limpio
- No es un sistema de betting. Es una herramienta de análisis.

## Añadir una jornada manualmente

Edita el endpoint `/api/matchdays` en `backend/api.py`:

```python
{
    "id": "laliga_j36",
    "label": "🇪🇸 La Liga J36",
    "date": "2026-05-17",
    "matches": [
        {"home": "Real Madrid", "away": "Sevilla", "home_league": "SP1", "away_league": "SP1"},
    ],
}
```

## Añadir una liga

En `backend/api.py`, cambia la llamada a `predictor.train(...)`:

```python
predictor.train(["SP1", "F1", "E0", "D1"])  # D1 = Bundesliga
```

Y añade el mapeo de nombres en `TEAM_NAME_MAP` si vas a usar fixtures live.

Códigos disponibles en football-data.co.uk: `SP1`, `F1`, `E0`, `D1`, `I1`.
