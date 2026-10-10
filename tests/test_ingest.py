"""test_ingest.py: el script que puebla el índice.

No toca la red: prueba las dos cosas que pueden romper el índice sin que nadie se entere.

- Los ids de los chunks tienen que ser DETERMINISTAS (mismo dataset → mismos ids). Si no lo
  fueran, cada corrida del ingestor duplicaría vectores en Pinecone.
- Sin la clave tiene que CORTAR con un mensaje claro. Esto es a propósito: en la devolución
  de la pre-entrega 4 me marcaron que degradar en silencio "puede enmascarar errores de
  configuración", y un ingestor que sigue sin clave deja el índice a medio actualizar.
"""

from __future__ import annotations

import pytest

from intelligence.rag.ingest import _exigir_clave, ids_de_chunks, limpiar_namespace
from intelligence.rag.recuperador import chunk_documents, load_dataset


class StoreDePrueba:
    """Doble del índice: permite simular la primera corrida y un error de verdad."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.borrados = 0

    def delete(self, delete_all: bool = False):
        self.borrados += 1
        if self.error:
            raise self.error


def test_la_primera_corrida_no_falla_porque_el_namespace_no_existe():
    """Pinecone responde 404 'Namespace not found' y eso no es un error: no había nada que limpiar."""

    store = StoreDePrueba(error=Exception('(404) Reason: Not Found ... "message":"Namespace not found"'))

    limpiar_namespace(store, "politicas-internas")  # no tiene que levantar

    assert store.borrados == 1


def test_cualquier_otro_error_al_limpiar_si_sube():
    """Si el borrado falla de verdad, seguir subiría vectores viejos mezclados con los nuevos."""

    store = StoreDePrueba(error=Exception("(500) Internal Server Error"))

    with pytest.raises(Exception) as error:
        limpiar_namespace(store, "politicas-internas")

    assert "500" in str(error.value)


def test_los_ids_son_deterministas_y_unicos():
    ids_una_vez = ids_de_chunks(chunk_documents(load_dataset()))
    ids_otra_vez = ids_de_chunks(chunk_documents(load_dataset()))

    assert ids_una_vez == ids_otra_vez, "los ids cambiaron entre dos corridas: duplicaría vectores"
    assert len(ids_una_vez) == len(set(ids_una_vez)), "hay ids repetidos"
    assert ids_una_vez[0].endswith("::0"), "el id tiene que nombrar el archivo y el chunk"


def test_sin_clave_corta_con_un_mensaje_que_explica_que_hacer(monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)

    with pytest.raises(SystemExit) as error:
        _exigir_clave()

    mensaje = str(error.value)
    assert "PINECONE_API_KEY" in mensaje
    assert ".env" in mensaje


def test_con_clave_devuelve_indice_y_namespace(monkeypatch):
    monkeypatch.setenv("PINECONE_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("INDEX_NAME", "indice-de-prueba")
    monkeypatch.setenv("PINECONE_NAMESPACE", "namespace-de-prueba")

    assert _exigir_clave() == ("indice-de-prueba", "namespace-de-prueba")
