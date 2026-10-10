"""test_cortes.py: las tres redes que evitan que el flujo dé vueltas para siempre.

Los tres casos salieron de una corrida real, con el trabajo cortado por el tope de tiempo y cero
pasos cerrados. En la traza se veía el bucle: supervisor -> analista -> supervisor -> analista...
sin fin.

1. El corte por cantidad de pasos tiene que ser la ÚLTIMA palabra: si el supervisor llega al
   máximo y la red de corrección lo pisa para mandar de nuevo al especialista que "falta", el
   grafo no cierra nunca.
2. El especialista no puede encadenar vueltas de herramientas sin límite: se le pasa un tope de
   recursión a su propia invocación.
3. Cuando ese tope se dispara, el aporte tiene que volver como ERROR legible (el supervisor y el
   validador saben qué hacer con un ERROR; con un volcado de excepción, no).
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from intelligence.agents.supervisor import MAX_PASOS, DecisionSupervisor, Supervisor, nodo_supervisor
from intelligence.graph.nodos import _correr_especialista


class LLMQueSiempreDelega:
    """Doble del supervisor: nunca quiere cerrar (es el caso que provocaba el bucle)."""

    def with_structured_output(self, esquema):
        return self

    def invoke(self, mensajes):
        return DecisionSupervisor(
            next="analista",
            instruccion="Calculá la cuenta que falta con los números del contexto.",
            razon="todavía falta el cálculo del analista",
        )


def test_el_corte_por_pasos_no_se_puede_deshacer(monkeypatch):
    """Con el máximo de pasos alcanzado, el nodo cierra aunque el validador diga que falta algo."""

    estado = {
        "messages": [HumanMessage(content="¿Cuántos días de licencia le corresponden a Ana?")],
        "pasos": MAX_PASOS,
        "contribuciones": [{"agente": "investigador", "aporte": "[Fuente: leyes/01] 20 días"}],
        "reintentos": 0,
    }
    supervisor = Supervisor(llm=LLMQueSiempreDelega())

    salida = nodo_supervisor(estado, supervisor=supervisor)

    assert salida["next_agent"] == "FINISH"
    assert salida["task_completed"] is True


def test_por_debajo_del_maximo_el_supervisor_sigue_decidiendo():
    """El corte no puede adelantarse: mientras haya margen, el supervisor manda."""

    estado = {
        "messages": [HumanMessage(content="¿Cuántos días de licencia le corresponden a Ana?")],
        "pasos": 1,
        "contribuciones": [],
        "reintentos": 0,
    }
    supervisor = Supervisor(llm=LLMQueSiempreDelega())

    salida = nodo_supervisor(estado, supervisor=supervisor)

    assert salida["next_agent"] in ("investigador", "analista")


class AgenteQueRegistra:
    """Doble del especialista: guarda con qué configuración se lo invocó."""

    def __init__(self):
        self.config = None

    def invoke(self, entrada, config=None):
        self.config = config
        return {"messages": [HumanMessage(content="Resultado: 21")]}


def test_el_especialista_se_invoca_con_un_tope_de_vueltas():
    agente = AgenteQueRegistra()
    estado = {"messages": [HumanMessage(content="una pregunta")], "instruccion": "Calculá la cuenta."}

    salida = _correr_especialista(agente, estado, "analista")

    assert agente.config == {"recursion_limit": 12}
    assert salida["contribuciones"][0]["aporte"] == "Resultado: 21"
    assert salida["pasos"] == 1


class AgenteQueSePasaDeVueltas:
    def invoke(self, entrada, config=None):
        raise RuntimeError("Recursion limit of 12 reached without hitting a stop condition")


def test_cuando_se_dispara_el_tope_el_aporte_vuelve_como_error_legible():
    estado = {"messages": [HumanMessage(content="una pregunta")], "instruccion": "Buscá el dato."}

    salida = _correr_especialista(AgenteQueSePasaDeVueltas(), estado, "investigador")

    aporte = salida["contribuciones"][0]["aporte"]
    assert aporte.startswith("ERROR:")
    assert "vueltas de herramientas" in aporte
