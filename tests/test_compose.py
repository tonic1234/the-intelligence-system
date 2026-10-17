"""Que el arranque en Docker espere de verdad: la devolución de la pre-entrega 7 lo marcó.

"En Docker, api y worker no esperan a que Phoenix arranque." Y no es un detalle de forma: Phoenix
tarda ~40 segundos en levantar (medido contra la imagen real), así que la API y el worker
arrancaban con el colector de trazas caído y perdían los primeros spans.

Estos tests no corren Docker: leen el compose y verifican que el orden de arranque sea explícito.
El healthcheck se probó contra la imagen de verdad (arizephoenix/phoenix:latest NO tiene shell:
por eso el test también cuida que no use `sh` ni `curl`).
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
COMPOSE = RAIZ / "docker-compose.yml"


def _bloque(servicio: str) -> str:
    """Las líneas de un servicio del compose (desde su nombre hasta el próximo de nivel 2)."""

    lineas = COMPOSE.read_text(encoding="utf-8").splitlines()
    dentro, bloque = False, []
    for linea in lineas:
        if re.match(rf"^  {re.escape(servicio)}:\s*$", linea):
            dentro = True
            continue
        if dentro:
            if re.match(r"^  \S", linea) or re.match(r"^\S", linea):
                break
            bloque.append(linea)
    assert bloque, f"no encontré el servicio '{servicio}' en docker-compose.yml"
    return "\n".join(bloque)


def test_phoenix_tiene_healthcheck():
    assert "healthcheck:" in _bloque("phoenix")


def test_el_healthcheck_de_phoenix_pregunta_por_el_puerto_de_phoenix():
    bloque = _bloque("phoenix")
    assert "6006" in bloque, "el healthcheck tiene que golpear el puerto en el que escucha Phoenix"
    assert "172.17" not in bloque, "la sonda va dentro del contenedor, no contra el host"


def test_el_healthcheck_no_depende_de_un_shell_que_la_imagen_no_tiene():
    """La imagen de Phoenix arranca en /usr/bin/python3.13 y no trae `sh`, `curl` ni `wget`."""

    bloque = _bloque("phoenix")
    sonda = bloque.split("healthcheck:", 1)[1].split("restart:", 1)[0]
    assert "CMD-SHELL" not in sonda
    assert "curl" not in sonda and "wget" not in sonda


def test_la_api_espera_a_phoenix_sano():
    bloque = _bloque("api")
    assert re.search(r"phoenix:\s*\n\s*condition:\s*service_healthy", bloque), (
        "la API tiene que arrancar recién cuando Phoenix contesta; sin eso pierde las primeras trazas"
    )


def test_el_worker_espera_a_phoenix_sano():
    bloque = _bloque("worker")
    assert re.search(r"phoenix:\s*\n\s*condition:\s*service_healthy", bloque)


def test_los_dos_procesos_siguen_esperando_a_redis():
    """Lo que ya funcionaba no se toca: el orden con Redis queda como estaba."""

    for servicio in ("api", "worker"):
        assert re.search(r"redis:\s*\n\s*condition:\s*service_healthy", _bloque(servicio))
