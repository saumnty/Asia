from dataclasses import dataclass

from core.rag.embedder import OllamaEmbedder
from core.rag.vector_store import VectorStore


@dataclass
class Hit:
    """Un fragmento encontrado."""
    document: str
    metadata: dict
    score: float


class ProjectRetriever:
    def __init__(
        self,
        project_name: str,
        persist_dir=None,
        embedder=None
    ):
        self.embedder = embedder or OllamaEmbedder()

        self.store = VectorStore(
            persist_dir=persist_dir,
            collection_name=project_name
        )

    def search(self, question: str, n_results=5):
        return self.search_vector(self.embedder.embed_query(question), n_results)

    def search_vector(self, query_embedding, n_results=5):
        return self.store.query(query_embedding, n_results=n_results)


def search_collections(question: str, collections: list, n_results=5, persist_dir=None) -> list:
    """Los mejores fragmentos de varias colecciones, de más a menos parecido."""
    embedder = OllamaEmbedder()
    query_embedding = embedder.embed_query(question)
    hits = []

    for collection in collections:
        results = ProjectRetriever(collection, persist_dir, embedder).search_vector(query_embedding, n_results)
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        hits += [Hit(d, m or {}, s) for d, m, s in zip(documents, metadatas, distances)]

    return sorted(hits, key=lambda hit: hit.score)[:n_results]
