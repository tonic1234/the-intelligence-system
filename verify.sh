#!/usr/bin/env bash
# Puerta de calidad del proyecto. Si esto termina en VERDE, el repo se puede entregar.
#
#   ./verify.sh
#
# Qué revisa (y qué no):
#   1. que la suite de pruebas pase completa, sin claves y sin red;
#   2. que el número de pruebas que declara el README sea el real (hay un test que lo compara);
#   3. que no haya claves ni archivos .env versionados;
#   4. que la sintaxis de los scripts y del compose esté bien.
#
# NO verifica que el sistema funcione contra el modelo real: eso es la corrida de escenarios
# (scripts/escenarios.py), que necesita Redis, Phoenix y una clave, y por eso va aparte.
set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RAIZ"

fallas=0
ok()    { printf "  \033[32mok\033[0m   %s\n" "$1"; }
fallo() { printf "  \033[31mFALLA\033[0m %s\n" "$1"; fallas=$((fallas + 1)); }

echo
echo "puerta de calidad — the-intelligence-system"
echo

# 1. pruebas
echo "pruebas"
salida_pruebas="$(python -m pytest -q --no-header 2>&1 || true)"
resumen="$(printf '%s\n' "$salida_pruebas" | grep -E "^[0-9]+ (passed|failed)" | tail -1)"
if printf '%s' "$resumen" | grep -q "failed"; then
  fallo "la suite no está verde: $resumen"
elif printf '%s' "$resumen" | grep -q "passed"; then
  ok "$resumen"
else
  fallo "no pude leer el resultado de pytest"
fi

# 2. el README dice el número real
declarado="$(grep -oE "## Las pruebas \([0-9]+" README.md | grep -oE "[0-9]+" || echo "")"
real="$(printf '%s\n' "$salida_pruebas" | grep -oE "^[0-9]+ passed" | grep -oE "[0-9]+" || echo "")"
if [ -n "$declarado" ] && [ "$declarado" = "$real" ]; then
  ok "el README declara $declarado pruebas y son las que corren"
else
  fallo "el README declara '${declarado:-nada}' y pytest corre '${real:-?}'"
fi

# 3. claves
echo "claves"
versionados="$(git ls-files | grep -E "(^|/)\.env$|secret|credentials" || true)"
if [ -z "$versionados" ]; then ok "no hay .env ni credenciales versionadas"; else fallo "hay archivos sensibles versionados: $versionados"; fi

# Busco claves con forma de clave en los archivos versionados. Excluyo el .env local a propósito
# (es el lugar donde van las claves) y NUNCA imprimo el valor encontrado: sólo archivo y línea.
patrones="$(git grep -InE "(AQ\.[A-Za-z0-9_-]{20,}|pcsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{20,})" -- \
  ':(exclude)*.md' ':(exclude).env.example' 2>/dev/null | cut -d: -f1,2 || true)"
if [ -z "$patrones" ]; then ok "no encontré claves con forma de clave en los archivos versionados"; else fallo "posible clave versionada (archivo:línea):"$'\n'"$patrones"; fi

# 4. sintaxis
echo "sintaxis"
bash -n run.sh 2>/dev/null && ok "run.sh" || fallo "run.sh tiene un error de sintaxis"
bash -n verify.sh 2>/dev/null && ok "verify.sh" || fallo "verify.sh tiene un error de sintaxis"
if command -v docker >/dev/null 2>&1; then
  docker compose config >/dev/null 2>&1 && ok "docker-compose.yml" || fallo "docker-compose.yml no valida"
else
  ok "docker no está instalado: salteo la validación del compose"
fi

echo
if [ "$fallas" -eq 0 ]; then
  printf "\033[32mVERDE\033[0m — el repo se puede entregar\n\n"
  exit 0
fi
printf "\033[31mROJO\033[0m — %s cosa(s) para arreglar\n\n" "$fallas"
exit 1
