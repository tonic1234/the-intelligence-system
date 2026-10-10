"""test_graph.py: el armado del grafo.

Se prueban los dos mapeos que son fuente clásica de errores en LangGraph:
- la decisión del supervisor (que habla en nombres de agentes, o dice FINISH) tiene que
  transformarse en el nombre REAL del nodo;
- después de validar, hay que decidir si se cierra o si el supervisor pide un refinamiento.
"""

from __future__ import annotations

from intelligence.graph.grafo import construir_grafo, enrutar, ruta_tras_validacion, tras_aprobacion


def test_el_supervisor_manda_siempre_al_nodo_de_aprobacion():
    """Cambió al unificar: entre el supervisor y el especialista ahora está la aprobación."""

    assert enrutar({"next_agent": "FINISH"}) == "aprobacion"
    assert enrutar({"next_agent": None}) == "aprobacion"
    assert enrutar({"next_agent": "investigador"}) == "aprobacion"


def test_despues_de_la_aprobacion_va_al_especialista_que_pidio_el_supervisor():
    assert tras_aprobacion({"next_agent": "investigador"}) == "investigador"
    assert tras_aprobacion({"next_agent": "analista"}) == "analista"
    assert tras_aprobacion({"next_agent": "FINISH"}) == "validacion"
    assert tras_aprobacion({"next_agent": "investigador", "aprobacion_rechazada": True}) == "sintesis"


def test_validacion_suficiente_cierra_en_sintesis():
    estado = {"validacion": {"suficiente": True}, "pasos": 2}
    assert ruta_tras_validacion(estado) == "sintesis"


def test_validacion_incompleta_vuelve_al_supervisor():
    estado = {
        "validacion": {"suficiente": False},
        "pasos": 1,
        "reintentos": 0,
        "contribuciones": [{"agente": "investigador", "aporte": "solo el dato, sin calcular"}],
    }
    assert ruta_tras_validacion(estado) == "supervisor"


def test_sin_ningun_aporte_no_tiene_sentido_mandarlo_de_nuevo():
    """Si el supervisor quiso cerrar sin que nadie aportara, se sintetiza y listo."""

    estado = {"validacion": {"suficiente": False}, "pasos": 0, "reintentos": 0, "contribuciones": []}
    assert ruta_tras_validacion(estado) == "sintesis"


def test_demasiados_reintentos_cierran_igual():
    from intelligence.graph.grafo import MAX_REINTENTOS

    estado = {
        "validacion": {"suficiente": False},
        "pasos": 2,
        "reintentos": MAX_REINTENTOS,
        "contribuciones": [{"agente": "investigador", "aporte": "algo"}],
    }
    assert ruta_tras_validacion(estado) == "sintesis"


def test_el_corte_por_max_pasos_cierra_igual():
    """Aunque el validador diga que falta, si se agotaron los pasos no se sigue iterando."""

    from intelligence.agents.supervisor import MAX_PASOS

    estado = {"validacion": {"suficiente": False}, "pasos": MAX_PASOS}
    assert ruta_tras_validacion(estado) == "sintesis"


def test_el_grafo_compila_con_los_nodos_y_el_ciclo():
    # Ahora el grafo es uno solo: el de la PE6 más el nodo de aprobación humana, que se mete
    # entre el supervisor y el especialista. Por eso acá se pide también "aprobacion".
    app = construir_grafo()

    nodos = set(app.get_graph().nodes)
    assert {"supervisor", "aprobacion", "investigador", "analista", "validacion", "sintesis"} <= nodos

    aristas = {(a.source, a.target) for a in app.get_graph().edges}
    # el ciclo: cada especialista vuelve al supervisor
    assert ("investigador", "supervisor") in aristas
    assert ("analista", "supervisor") in aristas
    assert ("validacion", "sintesis") in aristas
