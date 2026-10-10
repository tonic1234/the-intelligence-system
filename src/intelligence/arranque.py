"""Arranque del sistema: lo primero que hace cualquier proceso antes de servir.

Existe por un hueco que apareció al correr el proyecto de verdad: el `.env` estaba escrito y la capa
de configuración validaba el entorno, pero **nadie la llamaba al arrancar**, así que los procesos
leían `os.getenv()` en el vacío. Se notó en el dashboard: el endpoint de Phoenix estaba en el `.env`
y la API arrancaba igual con las trazas apagadas.

Ahora los dos procesos (la API y el worker) pasan por acá: se carga el `.env` del repo, se valida el
entorno y, si falta algo, el proceso **no arranca a medias**: corta con el mensaje que dice qué
falta. Y al revés, si está todo, queda en el log en qué modo arrancó (proveedor, modelo, recuperación,
trazas y concurrencia), para no tener que adivinarlo después.
"""

from __future__ import annotations

import logging

from intelligence.config.settings import Ajustes, cargar_ajustes

log = logging.getLogger("intelligence")


def preparar_arranque(usar_env_del_repo: bool = True) -> Ajustes:
    """Carga el .env del repo, valida el entorno y deja el resumen en el log.

    `usar_env_del_repo=False` lo usan las pruebas: sin eso, un `.env` en la máquina de quien corre
    la suite cambiaría el resultado (y las pruebas que verifican "sin clave no arranca" pasarían a
    encontrar la clave del archivo).
    """

    ajustes = cargar_ajustes(usar_env_del_repo=usar_env_del_repo)
    log.info("arrancando: %s", ajustes.resumen())
    return ajustes
