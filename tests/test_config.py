"""Tests de los ajustes: acá el test va ANTES del código (protocolo del proyecto).

El contrato que quiero que cumpla la capa de configuración:

- El sistema NO arranca sin la key del proveedor que se eligió, y el error dice cuál falta.
- Un proveedor que no existe se rechaza con la lista de los válidos, no con un KeyError.
- Los valores por defecto son razonables (Redis local, 3 trabajos a la vez, nombre de proyecto).
- Pinecone es opcional: sin su key el sistema carga igual (modo léxico).
- Los números de configuración que tienen que ser positivos, se validan.

Sin claves y sin red: el test carga variables a mano.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

VARIABLES = [
    "LLM_PROVIDER",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "REDIS_URL",
    "WORKER_CONCURRENCIA",
    "JOB_TTL_SEGUNDOS",
    "MINUTOS_ESPERA_APROBACION",
    "UMBRAL_COSTO_APROBACION",
    "PHOENIX_COLLECTOR_ENDPOINT",
    "PHOENIX_PROJECT_NAME",
    "PINECONE_API_KEY",
]


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    """Cada test arranca sin ninguna de las variables del sistema en el entorno."""

    for nombre in VARIABLES:
        monkeypatch.delenv(nombre, raising=False)
    yield


def cargar():
    from intelligence.config.settings import cargar_ajustes

    return cargar_ajustes()


def test_sin_la_key_del_proveedor_elegido_falla_diciendo_cual_falta(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    with pytest.raises(Exception) as error:
        cargar()

    mensaje = str(error.value)
    assert "GOOGLE_API_KEY" in mensaje, "el error tiene que nombrar la variable que falta"
    assert "aistudio" in mensaje.lower(), "y decir de dónde se saca la key gratis"


def test_un_proveedor_que_no_existe_se_rechaza_con_la_lista_de_validos(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "perplexity")
    monkeypatch.setenv("GOOGLE_API_KEY", "x")

    with pytest.raises(Exception) as error:
        cargar()

    mensaje = str(error.value)
    assert "perplexity" in mensaje
    for valido in ("gemini", "openai", "anthropic"):
        assert valido in mensaje, f"{valido} tiene que aparecer en la lista de válidos"


def test_los_defaults_son_los_que_esperamos(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-prueba")

    ajustes = cargar()

    assert ajustes.redis_url == "redis://127.0.0.1:6379/0"
    assert ajustes.worker_concurrencia == 3
    assert ajustes.phoenix_project_name == "the-intelligence-system"
    assert ajustes.umbral_costo_aprobacion == pytest.approx(0.02)
    assert ajustes.log_level == "INFO"


def test_pinecone_es_opcional_y_no_rompe_el_arranque(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-prueba")

    ajustes = cargar()

    assert ajustes.pinecone_api_key is None
    assert ajustes.modo_recuperacion == "lexico"


def test_con_pinecone_el_modo_es_hibrido(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("PINECONE_API_KEY", "pcsk_de_prueba")

    assert cargar().modo_recuperacion == "hibrido"


def test_la_concurrencia_tiene_que_ser_positiva(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("WORKER_CONCURRENCIA", "0")

    with pytest.raises(Exception) as error:
        cargar()

    assert "WORKER_CONCURRENCIA" in str(error.value)


def test_el_endpoint_de_phoenix_a_medias_no_pasa(monkeypatch):
    """Un endpoint sin esquema http(s) es un error de tipeo, no una configuración válida."""

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "127.0.0.1:6006")

    with pytest.raises(Exception) as error:
        cargar()

    assert "PHOENIX_COLLECTOR_ENDPOINT" in str(error.value)
