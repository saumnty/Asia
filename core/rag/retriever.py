"""Búsqueda híbrida: embeddings y palabras (FTS5, con BM25), fusionados por posición (RRF).

Los embeddings entienden el concepto; BM25 encuentra el nombre exacto. Se usa
la posición de cada lista y no sus puntuaciones, que no son comparables. Se
limitan los fragmentos por archivo para que un documento grande no acapare
los resultados.
"""
from dataclasses import dataclass

from core.rag.embedder import OllamaEmbedder
from core.rag.vector_store import VectorStore
from core.rag.word_index import ENGLISH, SPANISH

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
    coverage: float = 0.0


def relevant(hits: list, min_coverage: float, max_distance: float = None) -> bool:
    """False si la pregunta no tiene que ver con lo encontrado.

    Pasa si bastante de la pregunta está en algún fragmento o, para el código con
    pocas palabras en común con la pregunta, si un fragmento está muy cerca en los
    embeddings. Solo evita gastar el modelo: la distancia no separa del todo lo que
    tiene respuesta de lo que no (check_rag.py --calibrar), y lo que pasa aún tiene
    que sobrevivir a la extracción y a la verificación de citas.
    """
    if any(hit.coverage >= min_coverage for hit in hits):
        return True

    return max_distance is not None and any(
        hit.distance is not None and hit.distance <= max_distance for hit in hits
    )


def vector_hits(store, query_embedding) -> list:
    results = store.query(query_embedding, n_results=CANDIDATES)
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    return [(i, Hit(d, m or {}, distance=s)) for i, d, m, s in zip(ids, documents, metadatas, distances)]


def merge(*lists, n_results: int) -> list:
    """Fusiona por RRF listas ordenadas de (id, Hit), con el tope por archivo."""
    hits = {}

    for ranked in lists:
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


def ranked_lists(stores: list, question: str, language: str) -> tuple:
    """Lo que encuentra question en stores: por embeddings y por palabras, cada lista ordenada."""
    query_embedding = OllamaEmbedder().embed_query(question)
    vector = sorted(
        (pair for store in stores for pair in vector_hits(store, query_embedding)),
        key=lambda pair: pair[1].distance,
    )[:CANDIDATES]
    keyword = [
        (chunk_id, Hit(document, metadata, keyword_score=score))
        for chunk_id, document, metadata, score in stores[0].words.top(
            question, [store.name for store in stores], CANDIDATES, language,
        )
    ]
    return vector, keyword


def search_collections(question: str, collections: list, n_results=5, persist_dir=None, translated="", english=()) -> list:
    """Los mejores fragmentos de varias colecciones.

    translated es la pregunta en inglés: se busca además en las colecciones de english,
    con raíces del inglés, y la cobertura de cada fragmento es la mejor de las dos.
    """
    stores = [VectorStore(persist_dir=persist_dir, collection_name=collection) for collection in collections]

    if not stores:
        return []

    for store in stores:
        store.sync_words()

    lists = ranked_lists(stores, question, SPANISH)
    in_english = [store for store, collection in zip(stores, collections) if translated and collection in english]

    if in_english:
        lists += ranked_lists(in_english, translated, ENGLISH)

    hits = merge(*lists, n_results=n_results)
    documents = [hit.document for hit in hits]
    names = [store.name for store in stores]
    coverages = stores[0].words.coverage(question, documents, names)

    if in_english:
        names = [store.name for store in in_english]
        coverages = map(max, coverages, stores[0].words.coverage(translated, documents, names, ENGLISH))

    for hit, coverage in zip(hits, coverages):
        hit.coverage = coverage

    return hits
