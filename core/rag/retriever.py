from core.rag.embedder import OllamaEmbedder
from core.rag.vector_store import VectorStore


class ProjectRetriever:
    def __init__(
        self,
        project_name="asia"
    ):
        self.embedder = OllamaEmbedder()

        self.store = VectorStore(
            collection_name=project_name
        )

    def search(self, question: str, n_results=5):
        query_embedding = self.embedder.embed(question)
        return self.store.query(query_embedding, n_results=n_results)