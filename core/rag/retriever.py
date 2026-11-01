"""Búsqueda híbrida: embeddings y palabras (BM25), fusionados por posición (RRF).

Los embeddings entienden el concepto; BM25 encuentra el nombre exacto. Se usa
la posición de cada lista y no sus puntuaciones, que no son comparables. Se
limitan los fragmentos por archivo para que un documento grande no acapare
los resultados.
"""
from dataclasses import dataclass

from core.rag.bm25 import BM25
from core.rag.embedder import OllamaEmbedder
from core.rag.vector_store import VectorStore

# Cuántos candidatos aporta cada lista antes de fusionar.
CANDIDATES = 20
RRF_K = 60
MAX_PER_FILE = 2


@dataclass
class Hit:
    """Un fragmento encontrado. distance: la de los embeddings, si salió por ahí."""
    document: str
    metadata: dict
    score: float = 0.0
    distance: float = None
    keyword_score: float = 0.0


def vector_hits(store, query_embedding) -> list:
    results = store.query(query_embedding, n_results=CANDIDATES)
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    return [(i, Hit(d, m or {}, distance=s)) for i, d, m, s in zip(ids, documents, metadatas, distances)]


def merge(vector: list, keyword: list, n_results: int) -> list:
    """Fusiona por RRF dos listas ordenadas de (id, Hit), con el tope por archivo."""
    hits = {}

    for ranked in (vector, keyword):
        for position, (key, hit) in enumerate(ranked, start=1):
            known = hits.setdefault(key, hit)
            known.score += 1 / (RRF_K + position)
            known.distance = known.distance if known.distance is not None else hit.distance
            known.keyword_score = known.keyword_score or hit.keyword_score

    per_file, selected = {}, []

    for hit in sorted(hits.values(), key=lambda h: -h.score):
        file_path = hit.metadata.get("file_path", "")
        per_file[file_path] = per_file.get(file_path, 0) + 1

        if per_file[file_path] <= MAX_PER_FILE:
            selected.append(hit)

    return selected[:n_results]


def search_collections(question: str, collections: list, n_results=5, persist_dir=None) -> list:
    """Los mejores fragmentos de varias colecciones."""
    query_embedding = OllamaEmbedder().embed_query(question)
    vector, ids, documents, metadatas = [], [], [], []

    for collection in collections:
        store = VectorStore(persist_dir=persist_dir, collection_name=collection)
        vector += vector_hits(store, query_embedding)
        stored = store.all_documents()
        ids += stored["ids"]
        documents += stored["documents"]
        metadatas += stored["metadatas"]

    vector = sorted(vector, key=lambda pair: pair[1].distance)[:CANDIDATES]
    keyword = [
        (ids[i], Hit(documents[i], metadatas[i] or {}, keyword_score=score))
        for i, score in BM25(documents).top(question, CANDIDATES)
    ]

    return merge(vector, keyword, n_results)
