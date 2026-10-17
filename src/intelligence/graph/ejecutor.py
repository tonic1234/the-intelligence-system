"""El ejecutor: corre el grafo de verdad y le devuelve al worker lo que hay que guardar.

Es el único módulo que sabe de LangGraph. El worker sólo llama a un `ejecutor(pregunta,
reanudacion)`, así que los tests pueden pasarle un doble y no hace falta modelo ni Redis.

El estado del grafo vive en Redis (checkpoints), por eso el trabajo se puede pausar en un
proceso y reanudar en otro: es lo que hace posible la aprobación humana sin mantener nada vivo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from langgraph.types import Command
from redis.asyncio import Redis

from intelligence.graph.grafo import construir_grafo
from intelligence.llm.cliente import texto
from intelligence.graph.estado import estado_inicial

log = logging.getLogger(__name__)


# Si el equipo de agentes se pasa de este tiempo, el trabajo se corta. Se puede cambiar por
# entorno; la capa de configuración lo valida al arrancar para que un valor mal escrito no pase.
TOPES_SEGUNDOS_POR_DEFECTO = 300.0


def _tope_de_entorno() -> float:
    try:
        valor = float(os.getenv("JOB_TIMEOUT_SEGUNDOS", str(TOPES_SEGUNDOS_POR_DEFECTO)))
    except ValueError:
        return TOPES_SEGUNDOS_POR_DEFECTO
    return valor if valor > 0 else TOPES_SEGUNDOS_POR_DEFECTO


class EjecutorDelGrafo:
    def __init__(
        self,
        redis_url: str | None = None,
        costo_estimado: float | None = None,
        tope_segundos: float | None = None,
    ):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        # El costo estimado se calcula por PEDIDO en `estado_inicial`. Este valor es sólo un tope
        # manual para forzarlo en una corrida de prueba (por ejemplo, para ver la pausa por costo
        # sin esperar a que el trabajo la alcance solo).
        self.costo_estimado = costo_estimado
        # Tope duro de tiempo por trabajo. La consigna marca como error grave dejar al cliente
        # en un polling infinito: si el equipo de agentes se toma más de esto, el trabajo se corta
        # y queda en FALLO con el motivo, en vez de quedarse "en_proceso" para siempre.
        self.tope_segundos = tope_segundos or _tope_de_entorno()
        self._cliente = None
        self._saver = None
        self._grafo = None
        self._candado = asyncio.Lock()

    async def _crear_saver(self):
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
        from redis.asyncio import Redis

        self._cliente = Redis.from_url(self.redis_url)
        saver = AsyncRedisSaver(redis_client=self._cliente)
        try:
            await saver.asetup()  # crea los índices de checkpoints si no están
        except Exception as error:  # noqa: BLE001
            # Dos procesos pueden querer crear el mismo índice a la vez: el que llega segundo
            # recibe "index already exists", que no es un problema. Cualquier otro error sí sube.
            if "SEARCH_INDEX_EXISTS" not in str(error) and "already exists" not in str(error):
                raise
            log.info("los índices de checkpoints ya estaban creados en Redis")
        return saver

    async def preparar(self) -> None:
        if self._grafo is not None:
            return

        # El candado evita que dos tareas del mismo worker armen el grafo a la vez (y que las dos
        # pidan crear los índices: eso fue un fallo real, con el job marcado como FALLO).
        async with self._candado:
            if self._grafo is not None:
                return
            self._saver = await self._crear_saver()
            self._grafo = construir_grafo(checkpointer=self._saver, costo_estimado=self.costo_estimado)
            log.info("grafo listo con checkpoints en %s", self.redis_url)

    async def cerrar(self) -> None:
        if self._cliente is not None:
            await self._cliente.aclose()

    async def _correr(self, espera, hilo_id: str):
        """Espera a que el grafo termine, con tope de tiempo.

        `asyncio.wait_for` cancela la espera y devuelve el control: el trabajo no queda colgado y
        el worker lo puede marcar en FALLO con el motivo. Sin esto, un agente que se traba deja al
        cliente consultando el estado para siempre.
        """

        try:
            return await asyncio.wait_for(espera, timeout=self.tope_segundos)
        except asyncio.TimeoutError:
            log.warning("el trabajo %s se pasó del tope de %.0f s: lo corto", hilo_id, self.tope_segundos)
            raise TimeoutError(
                f"el trabajo superó el tope de {self.tope_segundos:.0f} segundos sin terminar"
            ) from None

    async def __call__(self, pregunta: str, reanudacion: dict | None = None) -> dict:
        await self.preparar()

        hilo_id = (reanudacion or {}).get("hilo_id") or uuid.uuid4().hex[:12]
        config = {"configurable": {"thread_id": hilo_id}}

        if reanudacion:
            aprobado = bool(reanudacion.get("aprobado"))
            log.info("reanudo el hilo %s con la decisión: %s", hilo_id, "aprobado" if aprobado else "rechazado")
            await self._correr(
                self._grafo.ainvoke(
                    Command(resume={"aprobado": aprobado, "comentario": reanudacion.get("comentario")}),
                    config,
                ),
                hilo_id,
            )
        else:
            # El costo estimado del pedido viaja en el estado (y no como un valor del ejecutor):
            # lo calcula `estado_inicial` para ESTE pedido. Antes el ejecutor se construía sin ese
            # valor, así que la regla de costo del HITL no se activaba nunca (devolución de la PE7).
            await self._correr(
                self._grafo.ainvoke(
                    estado_inicial(pregunta, costo_estimado=self.costo_estimado), config
                ),
                hilo_id,
            )

        estado = await self._grafo.aget_state(config)
        valores = dict(estado.values or {})
        interrumpido = bool(estado.next) and bool(estado.interrupts)

        pendiente = None
        motivo = None
        if interrumpido:
            valor = estado.interrupts[0].value
            if isinstance(valor, dict):
                pendiente = valor.get("instruccion")
                # El motivo de la pausa viaja con el trabajo: quien va a aprobar tiene que ver POR
                # QUÉ el sistema frenó (qué regla se disparó), no sólo que frenó.
                motivo = valor.get("motivo")
            else:
                pendiente = str(valor)

        resultado = None
        if not interrumpido and valores.get("messages"):
            resultado = texto(valores["messages"][-1])

        return {
            "resultado": resultado,
            "pasos": valores.get("pasos", 0),
            "contribuciones": valores.get("contribuciones", []),
            "interrumpido": interrumpido,
            "instruccion_pendiente": pendiente,
            "motivo_aprobacion": motivo,
            "hilo_id": hilo_id,
            # Los dos números del costo viajan al trabajo para que se puedan ver desde la API
            # (GET /tareas/{id}): el estimado al arrancar y lo gastado de verdad hasta ahora.
            "costo_estimado": valores.get("costo_estimado") or self.costo_estimado or 0.0,
            "costo_acumulado": valores.get("costo_acumulado") or 0.0,
        }
