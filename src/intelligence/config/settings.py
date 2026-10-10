"""Ajustes del sistema: se leen del entorno, se validan al arrancar y se leen una sola vez.

Por qué existe este módulo (en vez de leer os.getenv() suelto por el código):

1. Un solo lugar donde mirar qué necesita el sistema para correr.
2. Falla TEMPRANO y con mensaje útil. La devolución de la pre-entrega 4 lo pidió explícito:
   "degradar en silencio puede enmascarar errores". Si elegís Gemini y no está GOOGLE_API_KEY,
   el sistema tiene que decir qué variable falta y de dónde sacarla, no explotar tres capas más
   adentro con un 401 del proveedor.
3. Lo que es opcional es opcional DE VERDAD: sin PINECONE_API_KEY el recuperador arranca en modo
   léxico y el sistema anda igual.

Detalle de implementación que me costó un rato: el .env se lee SÓLO el del repo (ruta explícita), y no se
busca hacia arriba con `find_dotenv`. En este servidor hay otros .env en carpetas superiores y buscarlos
hacia arriba hace que un proyecto arranque con las claves de otro. Lo descubrí cuando este arrancó con las
claves de otra carpeta y tardé en darme cuenta.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# La raíz del repo: src/intelligence/config/settings.py -> config -> intelligence -> src -> raíz
RAIZ = Path(__file__).resolve().parents[3]
ARCHIVO_ENV = RAIZ / ".env"

# Cada proveedor con lo que necesita: la variable de su key, de dónde se saca gratis y su modelo.
PROVEEDORES: dict[str, dict[str, str]] = {
    "gemini": {
        "variable": "GOOGLE_API_KEY",
        "donde": "https://aistudio.google.com/apikey (tiene capa gratis)",
        "modelo": "GEMINI_MODEL",
        "modelo_por_defecto": "gemini-flash-latest",
    },
    "openai": {
        "variable": "OPENAI_API_KEY",
        "donde": "https://platform.openai.com/api-keys",
        "modelo": "OPENAI_MODEL",
        "modelo_por_defecto": "gpt-4o-mini",
    },
    "anthropic": {
        "variable": "ANTHROPIC_API_KEY",
        "donde": "https://console.anthropic.com/settings/keys",
        "modelo": "ANTHROPIC_MODEL",
        "modelo_por_defecto": "claude-3-5-sonnet-latest",
    },
}


class AjustesInvalidos(Exception):
    """El entorno no alcanza para arrancar. El mensaje dice qué falta y cómo resolverlo."""


@dataclass(frozen=True)
class Ajustes:
    """La configuración ya validada. Se pasa por parámetro; nadie lee el entorno por su cuenta."""

    proveedor: str
    api_key: str = field(repr=False)
    modelo: str
    redis_url: str
    worker_concurrencia: int
    job_ttl_segundos: int
    minutos_espera_aprobacion: int
    job_timeout_segundos: int
    umbral_costo_aprobacion: float
    phoenix_collector_endpoint: str | None
    phoenix_project_name: str
    pinecone_api_key: str | None = field(default=None, repr=False)
    pinecone_namespace: str = "politicas-internas"
    index_name: str = "the-intelligence-system"
    log_level: str = "INFO"

    @property
    def modo_recuperacion(self) -> str:
        """Con Pinecone el recuperador es híbrido (BM25 + vectorial); sin él, sólo léxico."""

        return "hibrido" if self.pinecone_api_key else "lexico"

    @property
    def trazas_activas(self) -> bool:
        return bool(self.phoenix_collector_endpoint)

    def resumen(self) -> str:
        """Lo que se imprime al arrancar. Nunca incluye claves (por eso las marco repr=False)."""

        return (
            f"proveedor={self.proveedor} modelo={self.modelo} "
            f"recuperacion={self.modo_recuperacion} "
            f"trazas={'activas' if self.trazas_activas else 'apagadas'} "
            f"concurrencia={self.worker_concurrencia} tope={self.job_timeout_segundos}s"
        )


def _texto(nombre: str, por_defecto: str | None = None) -> str | None:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return por_defecto
    return valor.strip()


def _entero(nombre: str, por_defecto: int) -> int:
    crudo = _texto(nombre)
    if crudo is None:
        return por_defecto
    try:
        valor = int(crudo)
    except ValueError:
        raise AjustesInvalidos(f"{nombre} tiene que ser un número entero y llegó {crudo!r}") from None
    if valor <= 0:
        raise AjustesInvalidos(f"{nombre} tiene que ser mayor que cero y llegó {valor}")
    return valor


def _decimal(nombre: str, por_defecto: float) -> float:
    crudo = _texto(nombre)
    if crudo is None:
        return por_defecto
    try:
        valor = float(crudo)
    except ValueError:
        raise AjustesInvalidos(f"{nombre} tiene que ser un número y llegó {crudo!r}") from None
    if valor < 0:
        raise AjustesInvalidos(f"{nombre} no puede ser negativo y llegó {valor}")
    return valor


def _cargar_env_del_repo() -> None:
    """Lee el .env del repo si existe. Nunca pisa variables ya presentes en el entorno."""

    if not ARCHIVO_ENV.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # sin python-dotenv se sigue: el entorno puede venir de afuera
        return
    load_dotenv(ARCHIVO_ENV, override=False)


def _validar_endpoint(nombre: str, valor: str | None) -> str | None:
    if valor is None:
        return None
    if not valor.startswith(("http://", "https://")):
        raise AjustesInvalidos(
            f"{nombre} tiene que empezar con http:// o https:// y llegó {valor!r}. "
            "Un endpoint de trazas al que no se puede llegar hace que el sistema parezca andar "
            "sin trazas, que es peor que un error."
        )
    return valor


def cargar_ajustes(usar_env_del_repo: bool = True) -> Ajustes:
    """Lee y valida el entorno. Levanta AjustesInvalidos con el detalle de lo que falta."""

    if usar_env_del_repo:
        _cargar_env_del_repo()

    proveedor = (_texto("LLM_PROVIDER", "gemini") or "gemini").lower()
    if proveedor not in PROVEEDORES:
        validos = ", ".join(sorted(PROVEEDORES))
        raise AjustesInvalidos(
            f"LLM_PROVIDER={proveedor!r} no es un proveedor conocido. Los válidos son: {validos}."
        )

    datos = PROVEEDORES[proveedor]
    api_key = _texto(datos["variable"])
    if not api_key:
        raise AjustesInvalidos(
            f"falta {datos['variable']}: es la clave de {proveedor}, que es el proveedor elegido "
            f"en LLM_PROVIDER. Se saca en {datos['donde']}. Si querés usar otro proveedor, "
            f"cambiá LLM_PROVIDER (válidos: {', '.join(sorted(PROVEEDORES))})."
        )

    return Ajustes(
        proveedor=proveedor,
        api_key=api_key,
        modelo=_texto(datos["modelo"], datos["modelo_por_defecto"]) or datos["modelo_por_defecto"],
        redis_url=_texto("REDIS_URL", "redis://127.0.0.1:6379/0") or "redis://127.0.0.1:6379/0",
        worker_concurrencia=_entero("WORKER_CONCURRENCIA", 3),
        job_ttl_segundos=_entero("JOB_TTL_SEGUNDOS", 86400),
        minutos_espera_aprobacion=_entero("MINUTOS_ESPERA_APROBACION", 15),
        job_timeout_segundos=_entero("JOB_TIMEOUT_SEGUNDOS", 300),
        umbral_costo_aprobacion=_decimal("UMBRAL_COSTO_APROBACION", 0.02),
        phoenix_collector_endpoint=_validar_endpoint(
            "PHOENIX_COLLECTOR_ENDPOINT", _texto("PHOENIX_COLLECTOR_ENDPOINT")
        ),
        phoenix_project_name=_texto("PHOENIX_PROJECT_NAME", "the-intelligence-system")
        or "the-intelligence-system",
        pinecone_api_key=_texto("PINECONE_API_KEY"),
        pinecone_namespace=_texto("PINECONE_NAMESPACE", "politicas-internas") or "politicas-internas",
        index_name=_texto("INDEX_NAME", "the-intelligence-system") or "the-intelligence-system",
        log_level=(_texto("LOG_LEVEL", "INFO") or "INFO").upper(),
    )
