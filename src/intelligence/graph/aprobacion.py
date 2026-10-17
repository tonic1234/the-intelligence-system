"""Human-in-the-loop: qué tareas se pausan y cómo se destraban.

La decisión de pausar no puede quedar "a criterio del modelo" (no es auditable ni repetible): se
decide en código, con reglas que se pueden leer y testear. Son tres:

  1. el pedido de la persona pide una acción con efecto (publicar, escribir, enviar, borrar...);
  2. el costo estimado del trabajo alcanza el umbral configurado;
  3. el gasto acumulado del trabajo ya alcanzó ese umbral.

La devolución de la pre-entrega 7 pidió dos cambios que están en este archivo:

  * la detección mira PALABRAS COMPLETAS y su papel en la frase, no fragmentos. Antes buscaba
    "actualiz" y "archiv" dentro del texto, así que "la política actualizada" activaba el verbo
    "actualizar" y "el archivo de onboarding" activaba "archivar": consultas inocentes quedaban
    esperando una aprobación que nadie iba a dar.
  * lo que se evalúa es el PEDIDO DE LA PERSONA, no la instrucción que redacta el supervisor. Esa
    instrucción es una descripción del trabajo ("buscá en el archivo de políticas...") y puede
    nombrar acciones sin pedirlas. El supervisor igual puede AGREGAR una pausa con su
    clasificación estructurada (`accion_con_efectos`), que es el lado seguro del error: el modelo
    no puede quitar la pausa que el código decide.

Sobre los verbos: en español el mismo token puede ser verbo o sustantivo ("la firma", "el envío").
Por eso una forma cuenta como acción sólo si no viene precedida por un determinante y además
aparece en posición de pedido: seguida de un objeto ("publicá EL informe") o, si es infinitivo,
precedida por un marcador de pedido ("necesito publicar", "hay que enviar").
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from intelligence.api.esquemas import EstadoJob

UMBRAL_COSTO_APROBACION = float(os.getenv("UMBRAL_COSTO_APROBACION", "0.02"))

# Formas aceptadas por verbo, normalizadas sin acentos (así "publicá" y "publica" son la misma).
# Las de infinitivo (-ar/-er/-ir) se usan además para la construcción "hay que publicar".
VERBOS_DE_EFECTO: dict[str, tuple[str, ...]] = {
    "publicar": ("publicar", "publica", "publiquen"),
    "escribir": ("escribir", "escribi", "escribe", "escriban"),
    "enviar": ("enviar", "envia", "envien"),
    "mandar": ("mandar", "manda", "manden"),
    "borrar": ("borrar", "borra", "borren"),
    "eliminar": ("eliminar", "elimina", "eliminen"),
    "contratar": ("contratar", "contrata", "contraten"),
    "firmar": ("firmar", "firma", "firmen"),
    "modificar": ("modificar", "modifica", "modifiquen"),
    "actualizar": ("actualizar", "actualiza", "actualicen"),
    "desplegar": ("desplegar", "despliega", "desplega", "desplieguen"),
    "pagar": ("pagar", "paga", "paguen"),
    "transferir": ("transferir", "transferi", "transfiere", "transfieran"),
    "archivar": ("archivar", "archiva", "archiven"),
    "subir": ("subir", "subi", "sube", "suban"),
    "reemplazar": ("reemplazar", "reemplaza", "reemplacen"),
}

_VERBO_DE_FORMA = {forma: verbo for verbo, formas in VERBOS_DE_EFECTO.items() for forma in formas}
_INFINITIVOS = frozenset(f for formas in VERBOS_DE_EFECTO.values() for f in formas if f.endswith(("ar", "er", "ir")))

# Lo que convierte una forma verbal en sustantivo: "la firma", "el envío", "los archivos".
DETERMINANTES = frozenset(
    {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "mi", "mis", "tu", "tus", "su",
        "sus", "nuestro", "nuestra", "este", "esta", "estos", "estas", "ese", "esa", "esos",
        "esas", "aquel", "aquella",
    }
)

# Lo que tiene que venir después del verbo para que sea una orden sobre algo y no una mención.
# Incluye preposiciones porque la acción se pide así: "enviá POR correo", "publicá EN el portal".
MARCAS_DE_OBJETO = frozenset(
    {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "lo", "le", "les", "me", "te",
        "nos", "mi", "mis", "tu", "tus", "su", "sus", "nuestro", "nuestra", "esto", "eso",
        "esta", "este", "estos", "estas", "al", "del", "a", "en", "por", "para", "con", "de",
        "desde", "hacia", "sin", "todo", "todos", "toda", "todas",
    }
)

# Lo que indica que esa misma palabra está funcionando como verbo conjugado en una oración
# descriptiva ("si SE envía por mail") y no como un pedido. Es la defensa contra el falso positivo
# por el otro lado: sin esto, cualquier "se publica por..." pausaría.
ANTES_DE_ORACION = frozenset(
    {"se", "si", "yo", "el", "ella", "ellos", "ellas", "eso", "esto", "alguien", "quien", "que",
     "no", "nunca", "ya", "suele", "suelen", "cuando", "donde"}
)

# Lo que tiene que venir ANTES de un infinitivo para que sea un pedido: "necesito publicar",
# "hay que enviar". Sin esto, "¿qué dice la política sobre enviar por correo?" pausaría.
MARCADORES_DE_PEDIDO = frozenset(
    {"hay", "que", "necesito", "necesitamos", "quiero", "queremos", "podes", "puede", "podrias",
     "deberia", "deberias", "tenes", "tiene", "tenemos", "debemos"}
)


def umbral_costo() -> float:
    """El umbral de costo, leído del entorno en el momento de la decisión.

    Una variable vacía o mal escrita NO puede romper la regla (un `.env` copiado del `.env.example`
    deja la clave sin valor): en ese caso se usa el valor por defecto y se avisa por log.
    """

    crudo = (os.getenv("UMBRAL_COSTO_APROBACION") or "").strip()
    if not crudo:
        return UMBRAL_COSTO_APROBACION
    try:
        return float(crudo)
    except ValueError:
        log.warning("UMBRAL_COSTO_APROBACION=%r no es un número: uso %s", crudo, UMBRAL_COSTO_APROBACION)
        return UMBRAL_COSTO_APROBACION


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _tokens(texto: str) -> list[str]:
    return re.findall(r"[a-zñ]+", _sin_acentos(texto))


def verbo_de_accion(texto: str | None) -> str | None:
    """El verbo de efecto que el texto PIDE, o None si sólo lo menciona."""

    tokens = _tokens(texto or "")
    for i, token in enumerate(tokens):
        verbo = _VERBO_DE_FORMA.get(token)
        if verbo is None:
            continue
        anterior = tokens[i - 1] if i else ""
        siguiente = tokens[i + 1] if i + 1 < len(tokens) else ""
        if anterior in DETERMINANTES:
            continue  # "la firma", "el envío": la misma palabra es un sustantivo
        if token in _INFINITIVOS:
            # Un infinitivo sólo es un pedido cuando alguien lo pide ("necesito publicar", "hay que
            # enviar"): sin esto, "¿qué pasa si me olvido de firmar la planilla?" pausaría.
            # Ojo con el orden de los controles: "que" es marcador de pedido acá ("hay QUE enviar")
            # y a la vez palabra que describe ("el hecho que envía"), así que los infinitivos se
            # resuelven ANTES del control de oración descriptiva.
            if anterior in MARCADORES_DE_PEDIDO:
                return verbo
            continue
        if anterior in ANTES_DE_ORACION:
            continue  # "si se envía por mail": describe, no pide
        if siguiente in MARCAS_DE_OBJETO:
            return verbo
    return None


def es_critica(
    pedido: str | None,
    costo_estimado: float | None = None,
    costo_acumulado: float | None = None,
    accion_con_efectos: bool = False,
) -> tuple[bool, str]:
    """Devuelve (si hay que pedir aprobación, por qué)."""

    verbo = verbo_de_accion(pedido)
    if verbo:
        return True, f"el pedido pide una acción con efecto ('{verbo}')"

    if accion_con_efectos:
        return True, (
            "el supervisor marcó la tarea como una acción con efectos sobre algo "
            "(clasificación estructurada)"
        )

    umbral = umbral_costo()
    if costo_estimado is not None and costo_estimado >= umbral:
        return True, (
            f"el costo estimado del trabajo ({costo_estimado:.4f} US$) alcanza el umbral "
            f"({umbral:.4f} US$)"
        )

    if costo_acumulado is not None and costo_acumulado >= umbral:
        return True, (
            f"el gasto acumulado del trabajo ({costo_acumulado:.4f} US$) alcanzó el umbral "
            f"({umbral:.4f} US$)"
        )

    return False, ""


def _momento(texto: str | None) -> datetime:
    if not texto:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(texto)
    except ValueError:
        return datetime.now(timezone.utc)


async def vencer_aprobaciones(cola, minutos: float | None = None) -> list[str]:
    """Cierra las aprobaciones que nadie contestó (si no, quedan colgadas para siempre)."""

    limite = float(minutos if minutos is not None else os.getenv("MINUTOS_ESPERA_APROBACION", "15"))
    corte = datetime.now(timezone.utc) - timedelta(minutes=limite)
    vencidos: list[str] = []
    for job_id in await cola.por_estado(EstadoJob.ESPERANDO_APROBACION):
        datos = await cola.leer(job_id)
        if datos and _momento(datos.get("actualizada_en")) <= corte:
            await cola.actualizar(
                job_id,
                EstadoJob.RECHAZADO_POR_TIMEOUT,
                error=f"la aprobación no llegó en {limite:g} minutos",
            )
            vencidos.append(job_id)
    return vencidos
