#!/usr/bin/env bash
# Levanta todo sin Docker, en un solo comando: Redis, Phoenix, la API y el worker.
#
#   ./run.sh
#
# Al final imprime la URL de la API y la del dashboard de trazas. Para bajar todo: ./run.sh --parar
# Los registros quedan en logs/ (api.log, worker.log, phoenix.log) por si algo no arranca.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RAIZ"

PUERTO_API="${PUERTO_API:-8000}"
PUERTO_PHOENIX="${PUERTO_PHOENIX:-6006}"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export PYTHONPATH="$RAIZ/src"

mkdir -p logs

parar() {
  for archivo in logs/*.pid; do
    [ -e "$archivo" ] || continue
    pid="$(cat "$archivo")"
    kill "$pid" 2>/dev/null || true
    rm -f "$archivo"
  done
  if [ -f logs/phoenix.docker ]; then
    docker rm -f tis-phoenix >/dev/null 2>&1 || true
    rm -f logs/phoenix.docker
  fi
  echo "API, worker y Phoenix detenidos."
}

if [ "${1:-}" = "--parar" ]; then
  parar
  exit 0
fi

if [ ! -f .env ]; then
  echo "Falta el archivo .env. Copiá .env.example a .env y completá la clave del modelo:"
  echo "  cp .env.example .env"
  exit 1
fi

# Redis: si no responde, lo levanto con Docker (es la vía más rápida y no ensucia el sistema).
if ! python -c "import redis,sys; sys.exit(0 if redis.Redis.from_url('$REDIS_URL').ping() else 1)" 2>/dev/null; then
  echo "Redis no responde en $REDIS_URL: lo levanto con Docker..."
  docker run -d --rm --name tis-redis -p 6379:6379 redis:8-alpine >/dev/null
  sleep 2
fi

echo "arrancando Phoenix (dashboard de trazas)..."
if python -c "import phoenix.server.main" 2>/dev/null; then
  PHOENIX_HOST=127.0.0.1 PHOENIX_PORT="$PUERTO_PHOENIX" \
    python -m phoenix.server.main serve >logs/phoenix.log 2>&1 &
  echo $! >logs/phoenix.pid
elif command -v docker >/dev/null 2>&1; then
  # El paquete de Phoenix no está instalado (no es requisito del camino base): se levanta el mismo
  # dashboard en su contenedor, igual que Redis.
  echo "  (el paquete de Phoenix no está instalado: lo levanto con Docker)"
  docker rm -f tis-phoenix >/dev/null 2>&1 || true
  docker run -d --rm --name tis-phoenix -p "$PUERTO_PHOENIX":6006 arizephoenix/phoenix:latest >/dev/null
  echo "docker" >logs/phoenix.docker
else
  echo "  no tengo Phoenix (ni el paquete ni Docker): el sistema arranca SIN trazas y lo avisa por log"
fi

# Espero a que Phoenix conteste antes de arrancar la API y el worker. Tarda unos 40 segundos: si
# los otros dos arrancan primero, el colector todavía no está y las primeras trazas se pierden.
if [ ! -f logs/phoenix.docker ] || docker ps --format '{{.Names}}' | grep -q '^tis-phoenix$'; then
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$PUERTO_PHOENIX/" 2>/dev/null; then
      echo "  Phoenix contesta en el puerto $PUERTO_PHOENIX"
      break
    fi
    sleep 1
  done
fi

echo "arrancando la API..."
uvicorn intelligence.main:app --host 0.0.0.0 --port "$PUERTO_API" >logs/api.log 2>&1 &
echo $! >logs/api.pid

echo "arrancando el worker..."
python -m intelligence.worker >logs/worker.log 2>&1 &
echo $! >logs/worker.pid

# Espero a que la API conteste antes de decir que está listo: si no, el primer curl falla.
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PUERTO_API/health" >/dev/null 2>&1; then
    echo
    echo "listo."
    echo "  API:      http://localhost:$PUERTO_API      (documentación en /docs)"
    echo "  Phoenix:  http://localhost:$PUERTO_PHOENIX"
    echo
    curl -s "http://127.0.0.1:$PUERTO_API/health"; echo
    echo
    echo "para bajar todo: ./run.sh --parar"
    exit 0
  fi
  sleep 1
done

echo "la API no contestó en 60 segundos: mirá logs/api.log"
exit 1
