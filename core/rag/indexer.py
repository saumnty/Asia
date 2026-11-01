from pathlib import Path

from config.settings_manager import SettingsManager
from core.rag.embedder import OllamaEmbedder
from core.rag.exclusions import SourceFilter
from core.rag.vector_store import VectorStore


def unload_chat_models():
    """Indexar es largo: el 7B no se queda en memoria junto al modelo de embeddings."""
    settings = SettingsManager()

    try:
        import ollama

        from providers.ollama_models import unload_others

        unload_others(ollama.Client(host=settings.get("ollama_host")), settings.get("embedding_model"), settings)
    except Exception:
        pass


class ProjectIndexer:
    def __init__(self, project_path: str, project_name: str, persist_dir=None, kind="proyecto"):
        # Ruta absoluta: los fragmentos se identifican igual sin importar
        # desde qué carpeta se indexe o se pregunte.
        self.project_path = Path(project_path).resolve()
        self.project_name = project_name
        self.kind = kind
        self.embedder = OllamaEmbedder()

        settings = SettingsManager()
        self.filter = SourceFilter(
            self.project_path, settings.text_extensions(), settings.ignored_dirs(include_tests=True),
        )

        self.store = VectorStore(
            persist_dir=persist_dir,
            collection_name=project_name
        )

    def chunk_text(self, text: str, chunk_size=1200, overlap=200):
        """(texto, primera línea, última línea) de cada fragmento."""
        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            first = text.count("\n", 0, start) + 1
            chunks.append((chunk, first, first + chunk.rstrip("\n").count("\n")))
            start += chunk_size - overlap

        return chunks

    def index_project(self):
        ids = []
        documents = []
        metadatas = []

        for file_path in self.filter.files():
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            chunks = self.chunk_text(text)

            for i, (chunk, first, last) in enumerate(chunks):
                doc_id = f"{file_path.as_posix()}::chunk_{i}"

                ids.append(doc_id)
                documents.append(chunk)
                metadatas.append({
                    "file_path": file_path.as_posix(),
                    "relative_path": file_path.relative_to(self.project_path).as_posix(),
                    "source": self.project_name,
                    "kind": self.kind,
                    "chunk": i,
                    "start_line": first,
                    "end_line": last,
                })

        embeddings = self.embedder.embed_documents(documents)

        # Se borran los fragmentos previos de esta carpeta (incluidos los de
        # archivos que ya no existen) solo después de generar todos los
        # embeddings, para no dejar el índice vacío si Ollama falla a medias.
        self.store.delete_where_file_path(self.is_inside_project)

        if ids:
            self.store.add_documents(ids, documents, embeddings, metadatas)

        return len(ids)

    def is_inside_project(self, file_path: str) -> bool:
        # Los índices creados antes de la fase 2 guardaban rutas relativas
        # (ambiguas sin la carpeta de origen): se reemplazan al reindexar.
        if not Path(file_path).is_absolute():
            return True

        root = self.project_path.as_posix()

        return file_path == root or file_path.startswith(root.rstrip("/") + "/")
