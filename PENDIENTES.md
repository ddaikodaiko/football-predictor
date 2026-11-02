# Pendientes — Football Predictor

Qué falta para enseñarlo a un recruiter.

## Publicar en GitHub (prioritario)

- [ ] Crear repo público `ddaikodaiko/football-predictor`
- [ ] Revisar que no hay claves de API, tokens ni datos de pago en el historial de git (`git log --all -- .env*`)
- [ ] Añadir `.gitignore` que excluya `data/raw/` (los CSV de football-data.co.uk pesan demasiado y no se pueden redistribuir libremente)
- [ ] Verificar la licencia: el README ya es bueno, añadir `LICENSE` MIT al repo

## Demo

- [ ] Captura o GIF de la app funcionando (modelo, partido, liga). El README ya tiene capturas estáticas en `docs/media/` — subirlas al repo cuando sea público.
- [ ] Evaluar si la app web (SvelteKit) puede desplegarse en un servidor público aunque sea con datos en solo lectura. Si no, el README actual (con capturas + tabla de resultados) ya es suficiente.

## Código

- [ ] Verificar que los 49 tests siguen en verde (`pytest backend/`)
- [ ] Añadir `requirements.txt` con versiones fijadas para el backend
- [ ] Revisar `README.md`: la sección "Contra las casas de apuestas" es excelente, asegurarse de que está actualizada con el modelo de precios (el que usa los partidos ya jugados, no solo goles+xG)

## Comunicar bien

- [ ] La métrica de calibración ("lo que dice que pasa el 25,5 % pasa el 25,9 %") es el dato más impresionante: asegurarse de que destaca en el README.
- [ ] Mencionar explícitamente las 3 fuentes de datos y el matching automático (100 % de cruce) — es un logro técnico real.
