"""test_arranque.py: la puerta por la que entra cualquier proceso.

Nació de un hueco real: el `.env` estaba escrito y la capa de configuración sabía validarlo, pero
nadie la llamaba al arrancar, así que la API y el worker arrancaban leyendo el entorno vacío. Se
descubrió mirando el dashboard: el endpoint de Phoenix estaba en el `.env` y las trazas seguían
apagadas.

Lo que se prueba acá es el contrato del arranque: con el entorno completo pasa y deja el resumen; con
el entorno incompleto CORTA, nombrando la variable que falta.
"""

from __future__ import annotations

import pytest

from intelligence.arranque import preparar_arranque
from intelligence.config.settings import AjustesInvalidos

VARIABLES = [
    "LLM_PROVIDER",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "REDIS_URL",
    "PHOENIX_COLLECTOR_ENDPOINT",
    "PHOENIX_PROJECT_NAME",
    "PINECONE_API_KEY",
]


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    for nombre in VARIABLES:
        monkeypatch.delenv(nombre, raising=False)
    yield


def test_con_el_entorno_completo_arranca_y_devuelve_los_ajustes(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006/v1/traces")

    ajustes = preparar_arranque(usar_env_del_repo=False)

    assert ajustes.proveedor == "gemini"
    assert ajustes.trazas_activas is True
    assert "gemini" in ajustes.resumen()
    assert "trazas=activas" in ajustes.resumen()


def test_sin_la_clave_del_modelo_no_arranca_y_dice_cual_falta(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    with pytest.raises(AjustesInvalidos) as error:
        preparar_arranque(usar_env_del_repo=False)

    assert "GOOGLE_API_KEY" in str(error.value)


def test_sin_endpoint_de_trazas_arranca_igual_pero_lo_declara(monkeypatch):
    """Las trazas son opcionales: lo que no puede pasar es que queden apagadas sin decirse."""

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-prueba")

    ajustes = preparar_arranque(usar_env_del_repo=False)

    assert ajustes.trazas_activas is False
    assert "trazas=apagadas" in ajustes.resumen()


def test_avisa_cuando_la_pata_vectorial_no_esta(monkeypatch, caplog):
    """Con Pinecone configurado pero sin los embeddings locales, el arranque lo tiene que decir.

    Lo vi en el contenedor de Docker: el resumen informaba "recuperación híbrida" mientras la
    búsqueda corría en BM25, porque los embeddings van aparte de los requisitos base.
    """

    from intelligence.config import settings

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("PINECONE_API_KEY", "pcsk_de_prueba")
    monkeypatch.setattr(settings, "embeddings_locales_disponibles", lambda: False)

    with caplog.at_level("WARNING"):
        ajustes = preparar_arranque(usar_env_del_repo=False)

    assert "recuperacion=lexico" in ajustes.resumen()
    assert any("requirements-embeddings.txt" in r.message for r in caplog.records)
