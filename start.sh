#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Backend ──────────────────────────────────────────────────
echo "▶ Arrancando backend (FastAPI :8000)..."
cd "$ROOT/backend"
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# ── Frontend ─────────────────────────────────────────────────
echo "▶ Arrancando frontend (SvelteKit :3000)..."
cd "$ROOT/frontend"
HOST=0.0.0.0 PORT=3000 node build/index.js &
FRONTEND_PID=$!

echo ""
echo "  ⚽ Football Predictor corriendo en http://localhost:3000"
echo "     API en                          http://localhost:8000"
echo ""
echo "  Ctrl+C para parar ambos procesos."

# Matar ambos al salir
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait $BACKEND_PID $FRONTEND_PID
