"""costos.py: cuánto se estima que va a costar un trabajo y cuánto se gastó de verdad.

Esta pieza existe por una devolución concreta (pre-entrega 7): la regla de costo del HITL estaba
escrita y testeada, pero nunca se activaba, porque `costo_estimado` llegaba siempre vacío y nadie
lo calculaba en ningún paso. El README la describía como si funcionara, que es la parte que no se
puede repetir.

Las tres decisiones de acá:

1. **Precios en una tabla por modelo, pisables por entorno.** Inventar un precio es peor que no
   tenerlo: si el modelo no está en la tabla y nadie fijó un precio, la estimación da cero y se
   dice por qué en el detalle. Se calcula sobre el precio publicado de entrada y salida.
2. **La estimación es del PEDIDO, antes de arrancar.** Se estiman los tokens de entrada del pedido
   y se multiplican por las rondas esperadas del equipo (el flujo real da entre 2 y 4 pasos). Es
   una estimación gruesa y se dice que lo es: sirve para decidir si hay que pedir aprobación, no
   para facturar.
3. **El gasto real sale del uso que reporta el modelo** (`usage_metadata`), sumado paso a paso.
   Ese número no se estima: es lo que el proveedor informó de cada respuesta.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from intelligence.config.settings import PROVEEDORES

log = logging.getLogger(__name__)

# Precio publicado por millón de tokens (entrada, salida) de los modelos que el sistema usa por
# defecto. Con la capa gratis del proveedor el costo facturado es cero, pero el precio de lista es
# este: la estimación usa el de lista para que la regla del umbral tenga sentido.
PRECIOS_POR_MILLON: dict[str, tuple[float, float]] = {
    "gemini-flash-latest": (0.30, 2.50),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash": (0.10, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-3-5-sonnet-latest": (3.00, 15.00),
}

# Rondas que se esperan del equipo para un pedido (investigador + analista + las vueltas del
# supervisor). Medido en las corridas del sistema: entre 2 y 4.
RONDAS_ESPERADAS = 4

# Por cada token de entrada el equipo devuelve más de uno de salida (respuestas + aportes).
FACTOR_SALIDA = 1.5


def modelo_configurado() -> str:
    """El modelo que va a atender el pedido, según el proveedor elegido en el entorno."""

    proveedor = (os.getenv("LLM_PROVIDER", "gemini") or "gemini").lower()
    datos = PROVEEDORES.get(proveedor) or PROVEEDORES["gemini"]
    return os.getenv(datos["modelo"]) or datos["modelo_por_defecto"]


def precio_por_millon(modelo: str | None = None) -> tuple[float, float]:
    """(entrada, salida) por millón de tokens. El entorno puede pisar cualquier modelo.

    Ojo con las variables VACÍAS: un `.env` con `PRECIO_ENTRADA_POR_MILLON=` (copiado del
    `.env.example`) no es lo mismo que no tenerla, y `float("")` explota. Si están vacías o mal
    escritas, se usa la tabla.
    """

    entrada = (os.getenv("PRECIO_ENTRADA_POR_MILLON") or "").strip()
    salida = (os.getenv("PRECIO_SALIDA_POR_MILLON") or "").strip()
    if entrada and salida:
        try:
            return float(entrada), float(salida)
        except ValueError:
            log.warning(
                "el precio por millón del entorno no es un número (entrada=%r, salida=%r): "
                "uso la tabla por modelo",
                entrada,
                salida,
            )
    return PRECIOS_POR_MILLON.get(modelo or modelo_configurado(), (0.0, 0.0))


@lru_cache(maxsize=1)
def _codificador():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def estimar_tokens(texto: str) -> int:
    """Tokens del texto. Si tiktoken no está (o no puede bajar su tabla), se aproxima por largo.

    El codificador de tiktoken descarga su tabla la primera vez y en un contenedor sin red eso
    falla: la estimación tiene que seguir andando igual, sólo que más gruesa.
    """

    if not texto:
        return 0
    try:
        return len(_codificador().encode(texto))
    except Exception:  # noqa: BLE001: sin codificador se aproxima, no se cae
        return max(1, len(texto) // 4)


def estimar_costo(
    texto: str, modelo: str | None = None, rondas: int = RONDAS_ESPERADAS
) -> dict[str, float | int | str]:
    """Estimación del pedido ANTES de correrlo, con el detalle de dónde sale cada número."""

    modelo = modelo or modelo_configurado()
    precio_entrada, precio_salida = precio_por_millon(modelo)
    tokens_entrada = estimar_tokens(texto) * max(1, rondas)
    tokens_salida = int(tokens_entrada * FACTOR_SALIDA)
    costo = (
        tokens_entrada / 1_000_000 * precio_entrada + tokens_salida / 1_000_000 * precio_salida
    )
    if not precio_entrada and not precio_salida:
        log.info(
            "no tengo precio para el modelo '%s': la estimación de costo da cero "
            "(se puede fijar con PRECIO_ENTRADA_POR_MILLON y PRECIO_SALIDA_POR_MILLON)",
            modelo,
        )
    return {
        "modelo": modelo,
        "rondas": max(1, rondas),
        "tokens_entrada": tokens_entrada,
        "tokens_salida": tokens_salida,
        "precio_entrada": precio_entrada,
        "precio_salida": precio_salida,
        # Ocho decimales: en dólares, una estimación de este tamaño se pierde si se redondea a
        # centavos (los costos por trabajo caen en el orden de 0,00001 US$).
        "costo": round(costo, 8),
    }


def costo_de_mensaje(mensaje, modelo: str | None = None) -> float:
    """Lo que costó UNA respuesta, leído del uso que reporta el proveedor.

    Los proveedores no lo informan igual: LangChain normaliza el caso común en `usage_metadata`
    (entrada/salida) y algunos SDK lo dejan en `response_metadata.token_usage`. Si no hay ninguno
    de los dos, se cuenta cero y el trabajo sigue: no se inventa un consumo.
    """

    modelo = modelo or modelo_configurado()
    precio_entrada, precio_salida = precio_por_millon(modelo)

    uso = getattr(mensaje, "usage_metadata", None) or {}
    entrada = uso.get("input_tokens")
    salida = uso.get("output_tokens")

    if entrada is None or salida is None:
        crudo = (getattr(mensaje, "response_metadata", None) or {}).get("token_usage") or {}
        entrada = crudo.get("prompt_tokens", entrada)
        salida = crudo.get("completion_tokens", salida)

    if entrada is None or salida is None:
        return 0.0

    return round(
        int(entrada) / 1_000_000 * precio_entrada + int(salida) / 1_000_000 * precio_salida, 8
    )
