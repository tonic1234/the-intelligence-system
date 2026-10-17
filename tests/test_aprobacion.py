"""La regla del HITL, con los casos que salieron en la devolución de la pre-entrega 7.

La devolución (7-oct-2026) marcó dos cosas concretas:

1. la regla pausaba consultas **inofensivas** porque buscaba FRAGMENTOS de verbo dentro del texto
   ("actualiz" dentro de "actualizada", "archiv" dentro de "archivo");
2. y avisaba que la instrucción que redacta el supervisor también puede traer esas palabras, así
   que la comparación tenía que ser más fina (palabras completas / clasificación estructurada).

Los dos casos textuales de la devolución quedan acá como testigos del arreglo, junto con los que
SÍ tienen que pausar: un arreglo que apague la regla también pasaría el primer grupo, y eso sería
peor que el bug.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from intelligence.graph.aprobacion import UMBRAL_COSTO_APROBACION, es_critica
from intelligence.graph.estado import estado_inicial
from intelligence.graph import grafo


# --- el grupo que tiene que PAUSAR (acciones con efecto) --------------------------------

ACCIONES_CON_EFECTO = [
    "Publicá el resumen en el portal interno",
    "Borrá los documentos vencidos del repositorio",
    "Enviá el informe al cliente",
    "Actualizá la política de vacaciones en el portal",
    "Firmá el contrato con el proveedor",
    "Necesito publicar el resumen de la reunión",
    "Hay que transferir el pago al proveedor",
    "Modificá el manual de onboarding",
    "Archivá los legajos del año pasado",
    "Desplegá la versión nueva del portal",
    # estos tres salieron de la corrida real del 17-oct: la acción se pide con una PREPOSICIÓN en el
    # medio ("enviá POR correo", "publicá EN el blog") y la regla no la veía.
    "Enviá por correo a todo el equipo el resumen de la política de seguridad",
    "Publicá en el blog de la empresa el resumen de la política de teletrabajo",
    "Mandá a todos los jefes el listado de licencias pendientes",
]


# --- el grupo que NO tiene que pausar ------------------------------------------------

CONSULTAS_INOFENSIVAS = [
    # los dos casos textuales de la devolución
    "¿Qué dice la política de vacaciones actualizada?",
    "Resumí el archivo de onboarding",
    # y el resto de la familia del mismo bug
    "¿Cuántos días de licencia me corresponden con 12 años de antigüedad?",
    "¿Qué dice el manual sobre el envío de reportes?",
    "¿Cómo funciona el archivo de legajos?",
    "Buscá en las políticas internas el plazo de la licencia anual",
    "Resumí la política de teletrabajo",
    "¿Qué pasa si me olvido de firmar la planilla de asistencia?",
    "¿Cuál es el monto de la indemnización por despido?",
    "¿Qué dice la política sobre enviar por correo las liquidaciones?",
    # el otro lado del caso de arriba: acá el mismo verbo describe, no pide
    "¿Qué pasa si se envía por mail la liquidación de sueldos?",
    "¿Cómo se publica en el portal interno una política nueva?",
]


@pytest.mark.parametrize("pedido", ACCIONES_CON_EFECTO)
def test_una_accion_con_efecto_pausa(pedido):
    critica, motivo = es_critica(pedido)
    assert critica is True, f"'{pedido}' pide una acción con efecto y tiene que pausar"
    assert motivo, "la pausa tiene que explicar por qué"


@pytest.mark.parametrize("pedido", CONSULTAS_INOFENSIVAS)
def test_una_consulta_no_pausa(pedido):
    critica, motivo = es_critica(pedido)
    assert critica is False, f"'{pedido}' es una consulta y no puede pausar el trabajo"
    assert motivo == ""


def test_el_motivo_nombra_el_verbo_que_la_disparo():
    _, motivo = es_critica("Publicá el resumen en el portal interno")
    assert "publicar" in motivo.lower()


# --- la decisión no la toma el texto del supervisor -------------------------------------


def _estado(pregunta: str, **campos) -> dict:
    estado = estado_inicial(pregunta, costo_estimado=0.0)
    estado.update({"next_agent": "investigador", "instruccion": "", **campos})
    return estado


def test_una_instruccion_del_supervisor_con_esas_palabras_no_pausa(monkeypatch):
    """La devolución avisaba justo de esto: la instrucción puede decir "archivo" sin pedir nada."""

    llamado = {}

    def interrupt_falso(payload):  # noqa: ANN001
        llamado["payload"] = payload
        return {"aprobado": True}

    monkeypatch.setattr(grafo, "interrupt", interrupt_falso)

    estado = _estado(
        "Resumí el archivo de onboarding",
        instruccion="Buscá en el archivo de políticas internas lo que dice sobre el onboarding "
        "y devolvelo textual, con su fuente entre corchetes.",
    )
    assert grafo.nodo_aprobacion(estado) == {}
    assert "payload" not in llamado


def test_una_accion_del_pedido_original_pausa_aunque_el_supervisor_la_reformule(monkeypatch):
    capturado = {}

    def interrupt_falso(payload):  # noqa: ANN001
        capturado["payload"] = payload
        return {"aprobado": True}

    monkeypatch.setattr(grafo, "interrupt", interrupt_falso)

    estado = _estado("Publicá el resumen en el portal interno", instruccion="Redactá el resumen.")
    resultado = grafo.nodo_aprobacion(estado)
    assert capturado["payload"]["esperando"] == "aprobacion_humana"
    assert resultado["aprobado_en_el_hilo"] is True


def test_una_sola_aprobacion_por_trabajo(monkeypatch):
    """Sin esto el pedido original vuelve a pausar en cada ronda y el trabajo nunca cierra."""

    def interrupt_falso(payload):  # noqa: ANN001
        raise AssertionError("no debería volver a pedir aprobación")

    monkeypatch.setattr(grafo, "interrupt", interrupt_falso)
    estado = _estado("Publicá el resumen", aprobado_en_el_hilo=True)
    assert grafo.nodo_aprobacion(estado) == {}


def test_el_supervisor_puede_agregar_la_pausa_con_la_clasificacion_estructurada(monkeypatch):
    """La clasificación estructurada suma: la decisión dura sigue en el código y el modelo sólo
    puede AGREGAR una pausa (nunca quitarla), que es el lado seguro del error."""

    capturado = {}

    def interrupt_falso(payload):  # noqa: ANN001
        capturado["payload"] = payload
        return {"aprobado": True}

    monkeypatch.setattr(grafo, "interrupt", interrupt_falso)

    estado = _estado("Resumí el archivo de onboarding", accion_con_efectos=True)
    grafo.nodo_aprobacion(estado)
    assert "supervisor" in capturado["payload"]["motivo"].lower()


# --- la regla del costo ----------------------------------------------------------------


def test_el_costo_estimado_del_estado_pausa(monkeypatch):
    monkeypatch.setenv("UMBRAL_COSTO_APROBACION", "0.001")
    capturado = {}

    def interrupt_falso(payload):  # noqa: ANN001
        capturado["payload"] = payload
        return {"aprobado": True}

    monkeypatch.setattr(grafo, "interrupt", interrupt_falso)

    estado = _estado("Resumí la política de teletrabajo", costo_estimado=0.02)
    grafo.nodo_aprobacion(estado)
    assert "costo estimado" in capturado["payload"]["motivo"].lower()


def test_el_gasto_acumulado_del_trabajo_tambien_pausa(monkeypatch):
    monkeypatch.setenv("UMBRAL_COSTO_APROBACION", "0.01")
    capturado = {}

    def interrupt_falso(payload):  # noqa: ANN001
        capturado["payload"] = payload
        return {"aprobado": True}

    monkeypatch.setattr(grafo, "interrupt", interrupt_falso)

    estado = _estado("Resumí la política de teletrabajo", costo_acumulado=0.03)
    grafo.nodo_aprobacion(estado)
    assert "acumulado" in capturado["payload"]["motivo"].lower()


def test_un_costo_bajo_no_alcanza_para_pausar():
    assert es_critica("Resumí dos párrafos", costo_estimado=0.0001)[0] is False
    assert es_critica("Analizá el histórico", costo_estimado=UMBRAL_COSTO_APROBACION + 0.01)[0] is True


def test_no_se_pausa_cuando_el_supervisor_quiere_cerrar(monkeypatch):
    def interrupt_falso(payload):  # noqa: ANN001
        raise AssertionError("no hay acción que aprobar si el supervisor cierra")

    monkeypatch.setattr(grafo, "interrupt", interrupt_falso)
    estado = _estado("Publicá el resumen", next_agent="FINISH")
    assert grafo.nodo_aprobacion(estado) == {}


def test_el_estado_inicial_lleva_el_costo_estimado_del_pedido():
    """El bug que marcó el profesor: el costo llegaba siempre vacío y la regla nunca se activaba."""

    estado = estado_inicial("¿Cuántos días de licencia anual me corresponden con 12 años de antigüedad?")
    assert isinstance(estado["costo_estimado"], float)
    assert estado["costo_estimado"] > 0, "con un modelo con precio, la estimación no puede ser cero"
    assert estado["costo_acumulado"] == 0.0


def test_el_estado_inicial_lleva_el_flag_de_accion_estructurada():
    estado = estado_inicial("una pregunta")
    assert estado["accion_con_efectos"] is False
    assert isinstance(estado["messages"][0], HumanMessage)
