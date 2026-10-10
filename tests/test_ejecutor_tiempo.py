"""test_ejecutor_tiempo.py: el tope de tiempo de un trabajo.

Nació de una corrida real: un escenario se pasó de los cinco minutos y el trabajo seguía en
`en_proceso`, con el cliente consultando el estado sin saber que no iba a terminar nunca. La
consigna marca justamente eso como error grave, así que el ejecutor ahora corta.

Lo que se prueba:

1. que un grafo que tarda más que el tope haga fallar el trabajo con el motivo a la vista;
2. que sin variable de entorno el tope sea el de por defecto, y que un valor mal escrito no rompa
   (queda el de por defecto, y la capa de configuración lo valida al arrancar).
"""

from __future__ import annotations

import pytest

from intelligence.graph.ejecutor import TOPES_SEGUNDOS_POR_DEFECTO, EjecutorDelGrafo, _tope_de_entorno


class GrafoQueNoTermina:
    """Doble del grafo: se queda esperando más de lo que dura el tope."""

    async def ainvoke(self, *args, **kwargs):
        import asyncio

        await asyncio.sleep(30)


async def test_un_trabajo_que_se_pasa_del_tope_se_corta_con_el_motivo():
    ejecutor = EjecutorDelGrafo(tope_segundos=0.2)
    ejecutor._grafo = GrafoQueNoTermina()  # así `preparar()` no arma el grafo de verdad

    with pytest.raises(TimeoutError) as error:
        await ejecutor("¿Cuántos días de licencia me corresponden?")

    assert "tope" in str(error.value)
    assert "0" in str(error.value)


def test_el_tope_por_defecto_es_el_que_esperamos(monkeypatch):
    monkeypatch.delenv("JOB_TIMEOUT_SEGUNDOS", raising=False)
    assert _tope_de_entorno() == TOPES_SEGUNDOS_POR_DEFECTO


def test_el_tope_se_puede_configurar_por_entorno(monkeypatch):
    monkeypatch.setenv("JOB_TIMEOUT_SEGUNDOS", "45")
    assert _tope_de_entorno() == 45


@pytest.mark.parametrize("valor", ["", "cuarenta", "-5", "0"])
def test_un_tope_mal_escrito_no_rompe_el_arranque(monkeypatch, valor):
    monkeypatch.setenv("JOB_TIMEOUT_SEGUNDOS", valor)
    assert _tope_de_entorno() == TOPES_SEGUNDOS_POR_DEFECTO
