"""La instalación tiene que ser liviana: el corrector tiene que poder correr las pruebas.

Lo pidió la devolución de la pre-entrega 7 con estas palabras: "requirements.txt instala
sentence-transformers y Phoenix completo, lo que hace muy lenta una instalación desde cero. Probé
pip install y no terminó en 10 minutos, así que no pude correr los tests."

La causa era que el camino BASE del sistema no necesita nada de eso: torch y los embeddings
locales sólo hacen falta para la rama vectorial sobre Pinecone, y el paquete completo de Phoenix
sólo para el dashboard sin Docker. Este test deja esa separación por escrito, para que nadie
vuelva a meter los pesados en el camino crítico.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# Lo que tarda muchísimo en instalarse y NO hace falta para correr el sistema ni la suite.
PESADOS = ("sentence-transformers", "torch", "arize-phoenix")

# Lo que el camino base sí necesita declarado.
BASE_OBLIGATORIA = (
    "fastapi",
    "uvicorn",
    "redis",
    "langgraph-checkpoint-redis",
    "langchain",
    "langgraph",
    "pinecone",
    "rank_bm25",
    "pydantic",
    "python-dotenv",
    "tiktoken",
    "openinference-instrumentation-langchain",
    "opentelemetry-sdk",
)


def _leer(nombre: str) -> str:
    archivo = RAIZ / nombre
    assert archivo.exists(), f"falta {nombre}"
    return archivo.read_text(encoding="utf-8")


def _declarados(texto: str) -> list[str]:
    """Los paquetes de un requirements, sin comentarios ni líneas de inclusión."""

    paquetes = []
    for linea in texto.splitlines():
        linea = linea.split("#", 1)[0].strip()
        if not linea or linea.startswith("-"):
            continue
        paquetes.append(re.split(r"[<>=!\[;]", linea, maxsplit=1)[0].strip().lower())
    return paquetes


def test_los_pesados_no_estan_en_los_requisitos_base():
    base = _declarados(_leer("requirements.txt"))
    colados = [p for p in PESADOS if p in base]
    assert not colados, (
        f"{', '.join(colados)} no puede estar en requirements.txt: la instalación base tiene que "
        "ser rápida. Va en su archivo opcional."
    )


def test_los_pesados_quedan_declarados_en_su_archivo_opcional():
    opcional = _declarados(_leer("requirements-embeddings.txt"))
    assert "sentence-transformers" in opcional
    assert "langchain-huggingface" in opcional


def test_los_requisitos_base_declaran_lo_que_el_sistema_necesita():
    base = _declarados(_leer("requirements.txt"))
    faltan = [p for p in BASE_OBLIGATORIA if p not in base]
    assert not faltan, f"faltan en requirements.txt: {', '.join(faltan)}"


def test_el_archivo_de_pruebas_instala_lo_que_la_suite_necesita():
    dev = _declarados(_leer("requirements-dev.txt"))
    for paquete in ("pytest", "pytest-asyncio", "fakeredis", "httpx"):
        assert paquete in dev, f"{paquete} tiene que estar en requirements-dev.txt"


def test_el_env_de_ejemplo_declara_todas_las_variables_que_el_codigo_lee():
    """El mismo cruce que se hizo a mano en la pre-entrega 7: si el código lee una variable que el
    .env.example no declara, quien clone el repo no sabe que existe."""

    leidas = set()
    for archivo in (RAIZ / "src").rglob("*.py"):
        leidas |= set(re.findall(r'os\.(?:getenv|environ\.get)\(\s*"([A-Z_0-9]+)"', archivo.read_text(encoding="utf-8")))
        leidas |= set(re.findall(r'environ\[\s*"([A-Z_0-9]+)"\s*\]', archivo.read_text(encoding="utf-8")))

    ejemplo = _leer(".env.example")
    faltan = sorted(v for v in leidas if not re.search(rf"^\s*#?\s*{v}=", ejemplo, re.MULTILINE))
    assert not faltan, f"el .env.example no declara: {', '.join(faltan)}"
