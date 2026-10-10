"""Las cinco pruebas del sistema, una por escenario.

La consigna pide "al menos 5 pruebas del sistema" con las trazas visibles en el dashboard. En vez de
mandar cinco veces la misma consulta, acá va una corrida por escenario, que es lo que muestra de
verdad cómo se comporta el sistema:

1. una sola capa del conocimiento (una consulta de ley);
2. dos dominios, con cálculo (una persona del legajo más la norma);
3. una acción con efecto, que tiene que PAUSAR hasta que una persona apruebe;
4. una acción con efecto que la persona RECHAZA (para ver el otro final);
5. una consulta que no está cubierta por el corpus (para ver que no inventa).

Corre contra la API de verdad, por HTTP, con el worker en otro proceso. Guarda el resultado de cada
corrida en `carga.json` y lo imprime como tabla.

Uso:
    python scripts/escenarios.py                  # la API en localhost:8000
    python scripts/escenarios.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ESPERA_MAXIMA_S = 420  # por encima del tope del sistema (300 s)
CADA_S = 3


@dataclass
class Escenario:
    nombre: str
    pregunta: str
    decision: bool | None = None  # None = no pide aprobación; True = aprueba; False = rechaza
    estado_esperado: str = "done"
    resultado: dict = field(default_factory=dict)
    segundos: float = 0.0
    error: str = ""


ESCENARIOS = [
    Escenario(
        nombre="1. una sola capa (ley)",
        pregunta=(
            "¿Qué dice la Ley 12.590 sobre los días de licencia anual y qué pasa con los feriados "
            "que caen en el medio?"
        ),
    ),
    Escenario(
        nombre="2. dos dominios con cálculo",
        pregunta=(
            "¿Cuántos días de licencia le corresponden a Bruno Cardozo, que entró en agosto de 2021, "
            "y cuánto cobra de salario vacacional por esos días?"
        ),
    ),
    Escenario(
        nombre="3. acción con efecto: la persona aprueba",
        pregunta=(
            "Enviá por correo a todo el equipo el resumen de la política de seguridad de la "
            "información de la empresa."
        ),
        decision=True,
        estado_esperado="done",
    ),
    Escenario(
        nombre="4. acción con efecto: la persona rechaza",
        pregunta="Publicá en el blog de la empresa el resumen de la política de teletrabajo.",
        decision=False,
        estado_esperado="rechazado",
    ),
    Escenario(
        nombre="5. consulta sin cobertura (no inventa)",
        pregunta="¿Cuánto sale el pasaje de avión a Miami en enero y qué hotel me recomendás?",
    ),
]


def pedir(metodo: str, ruta: str, cuerpo: dict | None = None) -> dict:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    pedido = urllib.request.Request(
        f"{BASE}{ruta}", data=datos, method=metodo, headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(pedido, timeout=30) as respuesta:
            return json.loads(respuesta.read())
    except urllib.error.HTTPError as error:
        return {"_http": error.code, "detalle": error.read().decode()[:200]}


def esperar_estado(job_id: str, hasta: str, limite: float = ESPERA_MAXIMA_S) -> dict:
    arranque = time.time()
    ultimo = {}
    while time.time() - arranque < limite:
        ultimo = pedir("GET", f"/tareas/{job_id}")
        if ultimo.get("estado") == hasta:
            return ultimo
        time.sleep(CADA_S)
    return ultimo


def correr(escenario: Escenario) -> None:
    inicio = time.time()
    creado = pedir("POST", "/tareas", {"pregunta": escenario.pregunta})
    job_id = creado.get("job_id")
    if not job_id:
        escenario.error = f"no se pudo encolar: {creado}"
        return

    if escenario.decision is None:
        ultimo = esperar_estado(job_id, escenario.estado_esperado)
    else:
        # Primero tiene que PAUSAR: si no pausa, la acción con efecto se ejecutó sin permiso.
        pausado = esperar_estado(job_id, "esperando_aprobacion")
        if pausado.get("estado") != "esperando_aprobacion":
            escenario.error = f"no pausó para pedir aprobación (quedó en {pausado.get('estado')})"
            ultimo = pausado
        else:
            escenario.resultado["instruccion_pendiente"] = pausado.get("instruccion_pendiente")
            escenario.resultado["pasos_al_pausar"] = pausado.get("pasos")
            pedir("POST", f"/tareas/{job_id}/aprobar", {"aprobado": escenario.decision, "comentario": "ok"})
            ultimo = esperar_estado(job_id, escenario.estado_esperado)

    escenario.segundos = round(time.time() - inicio, 1)
    escenario.resultado.update(
        {
            "job_id": job_id,
            "estado": ultimo.get("estado"),
            "pasos": ultimo.get("pasos"),
            "contribuciones": [c.get("agente") for c in (ultimo.get("contribuciones") or [])],
            "respuesta": (ultimo.get("resultado") or ultimo.get("error") or "")[:400],
        }
    )


def main() -> int:
    global BASE
    if "--base" in sys.argv:
        BASE = sys.argv[sys.argv.index("--base") + 1]

    print(f"corriendo {len(ESCENARIOS)} escenarios contra {BASE}\n")
    for escenario in ESCENARIOS:
        print(f"--- {escenario.nombre}")
        correr(escenario)
        estado = escenario.resultado.get("estado") or escenario.error
        print(f"    estado: {estado} | {escenario.segundos} s | pasos: {escenario.resultado.get('pasos')}")
        print(f"    agentes: {escenario.resultado.get('contribuciones')}\n")

    salida = Path("carga.json")
    salida.write_text(
        json.dumps([e.__dict__ for e in ESCENARIOS], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"{'escenario':44} {'estado':14} {'seg':>6} {'pasos':>6}  agentes")
    for e in ESCENARIOS:
        print(
            f"{e.nombre:44} {(e.resultado.get('estado') or 'ERROR'):14} {e.segundos:>6} "
            f"{str(e.resultado.get('pasos')):>6}  {','.join(e.resultado.get('contribuciones') or [])}"
        )

    fallaron = [e.nombre for e in ESCENARIOS if e.resultado.get("estado") != e.estado_esperado]
    print(f"\nresultado guardado en {salida} ({len(ESCENARIOS)} escenarios)")
    if fallaron:
        print("escenarios que no terminaron como se esperaba:")
        for nombre in fallaron:
            print(f"  - {nombre}")
        return 1
    print("los 5 terminaron como se esperaba")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
