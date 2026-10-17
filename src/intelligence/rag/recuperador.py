"""El recuperador: la parte del sistema que va a buscar los datos a los documentos.

Es el mismo camino que armé en las pre-entregas anteriores, adaptado al corpus nuevo. El hilo
del curso es que cada módulo se apoye en el anterior, así que mantengo las decisiones que ya
estaban probadas:

- chunking medido en TOKENS (tiktoken), no en caracteres;
- embeddings LOCALES con sentence-transformers/all-MiniLM-L6-v2 (384 dimensiones): el repo corre
  gratis y sin tarjeta;
- búsqueda híbrida: BM25 (palabras exactas) + vectorial (significado) con EnsembleRetriever.

Lo que cambió respecto de la pre-entrega es de dónde salen los documentos. Ahora son tres capas
en `data/`, cada una un archivo Markdown con un encabezado de metadatos:

    data/leyes/    normas uruguayas reales (con el artículo y la fuente oficial)
    data/empresa/  los documentos internos de la empresa ficticia
    data/legajos/  los datos de las personas

Los metadatos del encabezado viajan con cada fragmento, así la respuesta puede citar la norma o
el manual del que salió cada cosa y la búsqueda puede filtrar por capa.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

TOP_K = 5
CANTIDAD_CARACTERES_PREVIEW = 160

# La raíz del repo: src/intelligence/rag/recuperador.py -> rag -> intelligence -> src -> raíz
RAIZ = Path(__file__).resolve().parents[3]
DATA_DIR = RAIZ / "data"
CAPAS = ("leyes", "empresa", "legajos")


def _leer_encabezado(texto: str) -> tuple[dict, str]:
    """Separa el encabezado de metadatos (--- clave: valor ---) del cuerpo del documento.

    Escribirlo a mano en vez de sumar una dependencia: el formato es simple y así se ve
    exactamente qué se está leyendo.
    """

    if not texto.startswith("---"):
        return {}, texto
    partes = texto.split("---", 2)
    if len(partes) < 3:
        return {}, texto
    metadatos = {}
    for linea in partes[1].strip().splitlines():
        if ":" in linea:
            clave, valor = linea.split(":", 1)
            metadatos[clave.strip()] = valor.strip()
    return metadatos, partes[2].lstrip("\n")


def load_dataset() -> List[Document]:
    """Lee los documentos de las tres capas y les deja los metadatos del encabezado."""

    documentos: List[Document] = []
    for capa in CAPAS:
        carpeta = DATA_DIR / capa
        if not carpeta.exists():
            continue
        for archivo in sorted(carpeta.glob("*.md")):
            if archivo.name == "README.md":
                continue
            encabezado, cuerpo = _leer_encabezado(archivo.read_text(encoding="utf-8"))
            metadatos = {
                "source": str(archivo.relative_to(DATA_DIR)),  # p. ej. leyes/01-licencia-anual.md
                "capa": capa,
                "categoria": encabezado.get("tema", capa),  # el tema, para poder citarlo
                "tipo": encabezado.get("tipo", capa),
            }
            for clave in ("norma", "fuente", "empresa", "legajo", "persona"):
                if clave in encabezado:
                    metadatos[clave] = encabezado[clave]
            documentos.append(Document(page_content=cuerpo, metadata=metadatos))
    return documentos


def chunk_documents(documentos: List[Document]) -> List[Document]:
    """Parte cada documento en fragmentos de ~600 tokens con 100 de solapamiento.

    La numeración del fragmento es POR DOCUMENTO (0, 1, 2...), no global: así el id que se usa
    para subir el índice nombra el archivo y su fragmento, y sigue siendo determinista.
    """

    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=600, chunk_overlap=100
    )
    fragmentos: List[Document] = []
    for documento in documentos:
        for i, fragmento in enumerate(splitter.split_documents([documento])):
            fragmento.metadata["chunk_id"] = i
            fragmentos.append(fragmento)
    return fragmentos


def build_vector_retriever(k: int = TOP_K):
    """Conecta con el índice de Pinecone (si ya existe, no se reingesta nada)."""

    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_pinecone import PineconeVectorStore

    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    indice = os.getenv("INDEX_NAME", "the-intelligence-system")
    namespace = os.getenv("PINECONE_NAMESPACE", "politicas-internas")

    vectorstore = PineconeVectorStore(index_name=indice, embedding=embeddings, namespace=namespace)
    return vectorstore.as_retriever(search_kwargs={"k": k, "namespace": namespace})


def build_hybrid_retriever(k: int = TOP_K):
    """Arma el EnsembleRetriever si hay Pinecone; si no, devuelve solo BM25 (modo local)."""

    fragmentos = chunk_documents(load_dataset())

    retriever_bm25 = BM25Retriever.from_documents(fragmentos)
    retriever_bm25.k = k

    if not os.getenv("PINECONE_API_KEY"):
        # Antes esto era un logger.info y pasaba desapercibido: en la devolución de la
        # pre-entrega 4 me marcaron justamente que degradar en silencio "puede enmascarar
        # errores de configuración". Ahora es warning y la demo imprime el modo real.
        logger.warning(
            "SIN PINECONE_API_KEY: recuperador en modo LÉXICO (solo BM25, sin la pata "
            "vectorial). El flujo funciona, pero la búsqueda es peor: completá la clave en "
            ".env para correr en modo híbrido."
        )
        return retriever_bm25

    try:
        retriever_vectorial = build_vector_retriever(k)
    except Exception as exc:  # si la nube falla, seguimos con la parte léxica
        # El mensaje dice QUÉ instalar cuando el problema es que faltan los embeddings locales:
        # sin eso, quien clone el repo ve "No module named 'langchain_huggingface'" y no sabe que
        # hay un archivo de requisitos aparte (es el camino liviano que pide la devolución de PE7).
        pista = ""
        if "langchain_huggingface" in str(exc) or "sentence_transformers" in str(exc):
            pista = ": los embeddings locales se instalan con pip install -r requirements-embeddings.txt"
        logger.warning("No pude armar la rama vectorial (%s); sigo con BM25%s", exc, pista)
        return retriever_bm25

    from langchain_classic.retrievers import EnsembleRetriever

    logger.info("Recuperador HÍBRIDO (BM25 + vectorial)")
    return EnsembleRetriever(retrievers=[retriever_bm25, retriever_vectorial], weights=[0.5, 0.5])


def nombre_modo(retriever) -> str:
    """Nombre legible del modo de recuperación, leído del retriever real."""

    tipo = type(retriever).__name__
    if tipo == "EnsembleRetriever":
        return "híbrido (BM25 + vectorial sobre Pinecone)"
    if tipo == "BM25Retriever":
        return "léxico (solo BM25, sin Pinecone)"
    return f"personalizado ({tipo})"


class RAGSystem:
    """Envoltorio simple: `obtener_top_k(pregunta)` devuelve los fragmentos con su fuente."""

    def __init__(self, retriever=None, k: int = TOP_K) -> None:
        self.retriever = retriever or build_hybrid_retriever(k)
        self.k = k
        # El modo se lee del retriever que REALMENTE quedó armado (no de lo que pide el .env):
        # así la demo puede decir en qué modo corrió sin depender de una suposición.
        self.modo = nombre_modo(self.retriever)

    def obtener_top_k(self, query: str) -> List[Dict]:
        docs: List[Document] = self.retriever.invoke(query)[: self.k]
        return [
            {
                "contenido": d.page_content,
                "fuente": d.metadata.get("source", "desconocida"),
                "categoria": d.metadata.get("categoria", "desconocida"),
                "capa": d.metadata.get("capa", ""),
                "norma": d.metadata.get("norma", ""),
            }
            for d in docs
        ]


def serializar_fragmentos(fragmentos: List[Dict]) -> str:
    """Formato que le devuelvo al LLM: cada fragmento con su fuente a la vista."""

    if not fragmentos:
        return ""
    partes = []
    for f in fragmentos:
        referencia = f"[{f['fuente']}"
        if f.get("norma"):
            referencia += f" · {f['norma']}"
        partes.append(f"{referencia}] {f['contenido']}")
    return "\n\n".join(partes)


if __name__ == "__main__":  # pragma: no cover - prueba manual
    sistema = RAGSystem()
    for i, fragmento in enumerate(sistema.obtener_top_k("licencia anual por antigüedad"), 1):
        print(f"{i}. [{fragmento['fuente']}] {fragmento['contenido'][:CANTIDAD_CARACTERES_PREVIEW]}...")
