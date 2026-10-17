"""state.py: el estado compartido del orquestador.

La consigna pide un esquema que permita "rastrear qué agente contribuyó con qué
información, evitando la pérdida de contexto en la comunicación asíncrona".

Dos decisiones que se explican solas:

1. Heredo de MessagesState (LangGraph) porque ya trae `messages` con su reducer
   `add_messages`: no quiero reimplementar el manejo del historial.
2. `contribuciones` es una LISTA con reducer `operator.add`. Ese es el punto: si un nodo
   escribiera `{"contribuciones": [...]}` sin el reducer, su aporte PISARÍA el del
   especialista anterior y el supervisor perdería de vista quién dijo qué. Con el reducer,
   cada devolución se SUMA a la lista que ya estaba.

Nota: no uso `from __future__ import annotations` a propósito, para que las anotaciones
sean objetos reales (así los tests pueden leer el reducer del tipo).
"""

import operator
from typing import Annotated, Any, Dict, List, Optional

from langchain_core.messages import HumanMessage
from langgraph.graph import MessagesState


def contribucion(agente: str, aporte: str) -> Dict[str, str]:
    """Formato único de un aporte: quién lo dijo y qué dijo."""

    return {"agente": agente, "aporte": aporte}


class AgentState(MessagesState):
    """Estado que viaja por todo el grafo."""

    # A quién decidió llamar el supervisor en este turno ("investigador", "analista" o "FINISH").
    next_agent: Optional[str]

    # La instrucción puntual que el supervisor le dejó al especialista elegido.
    instruccion: Optional[str]

    # Registro acumulativo de aportes (el reducer operator.add es lo que evita que se pisen).
    contribuciones: Annotated[List[Dict[str, str]], operator.add]

    # Cuántos especialistas corrieron: es el contador del corte contra el "Supervisor Infinito".
    pasos: int

    # Se prende cuando el validador da el visto bueno (o cuando el flujo llegó a la síntesis).
    task_completed: bool

    # Informe del nodo de validación (suficiente, faltantes, motivo...).
    validacion: Optional[Dict[str, Any]]

    # Cuántas veces el validador mandó a refinar: la segunda red del corte.
    reintentos: int

    # Lo que se estima que va a costar el trabajo, calculado del pedido al arrancar (ver costos.py).
    # El HITL lo usa como una de sus reglas; antes llegaba siempre vacío y la regla no se activaba.
    costo_estimado: float

    # Lo que se gastó de verdad hasta ahora, sumado del uso que reporta el modelo en cada paso.
    costo_acumulado: float

    # Clasificación estructurada del supervisor: si la tarea delegada implica una acción con
    # efectos. Puede AGREGAR una pausa, nunca quitarla.
    accion_con_efectos: bool


def estado_inicial(
    pregunta: str, costo_estimado: float | None = None, modelo: str | None = None
) -> dict:
    """El estado con el que arranca un trabajo.

    El costo estimado se calcula acá, del pedido real: es el dato que la regla del HITL mira para
    decidir si un trabajo pide aprobación por lo que va a costar. Se puede forzar desde afuera
    (corridas de prueba) pasándolo por parámetro.
    """

    if costo_estimado is None:
        from intelligence.graph.costos import estimar_costo

        costo_estimado = float(estimar_costo(pregunta, modelo=modelo)["costo"])

    return {
        "messages": [HumanMessage(content=pregunta)],
        "next_agent": None,
        "instruccion": None,
        "contribuciones": [],
        "pasos": 0,
        "task_completed": False,
        "validacion": None,
        "reintentos": 0,
        "costo_estimado": float(costo_estimado),
        "costo_acumulado": 0.0,
        "accion_con_efectos": False,
    }
