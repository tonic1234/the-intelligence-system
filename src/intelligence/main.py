"""Punto de entrada para el servidor: `uvicorn intelligence.main:app`.

La app se arma acá y no en `api.py` para que importar el módulo en los tests no tenga efectos
(conectar Redis o instrumentar trazas son cosas que hace el servidor, no una importación).

Antes de armar la app se pasa por `preparar_arranque()`: eso lee el `.env` del repo y valida el
entorno. Si falta algo, el servidor no arranca y el error dice qué falta (mejor eso que arrancar
a medias y descubrirlo tres capas más adentro).
"""

from __future__ import annotations

from intelligence.api.api import crear_app
from intelligence.arranque import preparar_arranque
from intelligence.graph.ejecutor import EjecutorDelGrafo

preparar_arranque()

# Ojo: la API NO activa la instrumentación a propósito. Las trazas las exporta el worker, que es
# donde corre el grafo; instrumentar también acá llena el dashboard de spans de `GET /tareas/<id>`
# (el polling del cliente) y entierra las trazas de los agentes. Me pasó al probarlo: 387 trazas
# con el dashboard casi todo de consultas de estado.
app = crear_app(ejecutor=EjecutorDelGrafo())
