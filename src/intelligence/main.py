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
from intelligence.observability.phoenix import activar_trazas

preparar_arranque()

# La API también activa las trazas, aunque el grafo corra en el worker. No es por gusto: el
# /health informa si el sistema está trazando, y con esto apagado acá decía "false" con Phoenix
# configurado, que se lee como si no hubiera trazas. La instrumentación es sólo sobre LangChain,
# así que a la API no le agrega ruido (no usa LangChain para atender pedidos).
activar_trazas()

app = crear_app(ejecutor=EjecutorDelGrafo())
