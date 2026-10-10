"""test_estado_inicial.py: el estado inicial con el que arranca cada trabajo.

Este test nació de un bug de verdad: al unificar el proyecto, `estado_inicial` se mudó de
módulo y se quedó sin el import de `HumanMessage`. La suite seguía verde porque ninguna prueba
llamaba a esa función, pero el sistema real no: el primer trabajo que encolé por la API terminó
en `fallo` con `NameError: name 'HumanMessage' is not defined`.

Por eso ahora hay una prueba que arma el estado de verdad: es la puerta por la que entra
cualquier consulta.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from intelligence.graph.estado import estado_inicial

CAMPOS_ESPERADOS = {
    "messages",
    "next_agent",
    "instruccion",
    "contribuciones",
    "pasos",
    "task_completed",
    "validacion",
    "reintentos",
}


def test_el_estado_inicial_lleva_la_pregunta_como_mensaje_del_usuario():
    estado = estado_inicial("¿Cuántos días de licencia me corresponden?")

    assert len(estado["messages"]) == 1
    mensaje = estado["messages"][0]
    assert isinstance(mensaje, HumanMessage)
    assert mensaje.content == "¿Cuántos días de licencia me corresponden?"


def test_el_estado_inicial_trae_todos_los_campos_del_grafo():
    """Si falta un campo, los nodos lo leen como None y el flujo se comporta raro."""

    estado = estado_inicial("una pregunta cualquiera")

    assert CAMPOS_ESPERADOS <= set(estado)
    assert estado["pasos"] == 0
    assert estado["reintentos"] == 0
    assert estado["contribuciones"] == []
    assert estado["task_completed"] is False
