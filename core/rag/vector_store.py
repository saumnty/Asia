import re

import chromadb


BATCH_SIZE = 1000


def safe_collection_name(name: str) -> str:
    """Adapta un nombre de proyecto a las reglas de ChromaDB.

    ChromaDB exige 3-512 caracteres de [a-zA-Z0-9._-] que empiecen y terminen
    en alfanumérico. Los nombres ya válidos (p. ej. "asia") no cambian.
    """
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", name.strip()).strip("._-")

    if len(safe) < 3:
        safe = f"project_{safe}" if safe else "project_default"

    return safe[:512].rstrip("._-")


class VectorStore:

    def __init__(
        self,
        persist_dir="data/chroma",
        collection_name="default"
    ):

        self.client = chromadb.PersistentClient(
            path=persist_dir
        )

        self.collection = self.client.get_or_create_collection(
            name=safe_collection_name(collection_name)
        )

    def add_documents(
        self,
        ids,
        documents,
        embeddings,
        metadatas
    ):
        """Inserta o actualiza documentos (upsert), en lotes."""
        for start in range(0, len(ids), BATCH_SIZE):
            end = start + BATCH_SIZE

            self.collection.upsert(
                ids=ids[start:end],
                documents=documents[start:end],
                embeddings=embeddings[start:end],
                metadatas=metadatas[start:end]
            )

    def delete_where_file_path(self, matches) -> int:
        """Borra los documentos cuyo metadata file_path cumple matches(path)."""
        existing = self.collection.get(include=["metadatas"])

        ids = [
            doc_id
            for doc_id, metadata in zip(existing["ids"], existing["metadatas"])
            if matches((metadata or {}).get("file_path", ""))
        ]

        for start in range(0, len(ids), BATCH_SIZE):
            self.collection.delete(ids=ids[start:start + BATCH_SIZE])

        return len(ids)

    def query(
        self,
        query_embedding,
        n_results=5
    ):

        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
