from pathlib import Path

from config.settings_manager import SettingsManager
from core.paths import has_ignored_part, iter_files
from core.rag.embedder import OllamaEmbedder
from core.rag.vector_store import VectorStore


class ProjectIndexer:
    def __init__(self, project_path: str, project_name: str):
        # Ruta absoluta: los fragmentos se identifican igual sin importar
        # desde qué carpeta se indexe o se pregunte.
        self.project_path = Path(project_path).resolve()
        self.embedder = OllamaEmbedder()

        settings = SettingsManager()
        self.allowed_extensions = settings.text_extensions()
        self.ignored_dirs = settings.ignored_dirs(include_tests=True)

        self.store = VectorStore(
            collection_name=project_name
        )

    def should_index(self, path: Path) -> bool:
        if path.suffix.lower() not in self.allowed_extensions:
            return False

        return not has_ignored_part(path, self.project_path, self.ignored_dirs)

    def chunk_text(self, text: str, chunk_size=1200, overlap=200):
        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += chunk_size - overlap

        return chunks

    def index_project(self):
        ids = []
        documents = []
        embeddings = []
        metadatas = []

        for file_path in iter_files(self.project_path, self.ignored_dirs):
            if not self.should_index(file_path):
                continue

            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            chunks = self.chunk_text(text)

            for i, chunk in enumerate(chunks):
                doc_id = f"{file_path.as_posix()}::chunk_{i}"

                ids.append(doc_id)
                documents.append(chunk)
                embeddings.append(self.embedder.embed(chunk))
                metadatas.append({
                    "file_path": file_path.as_posix(),
                    "chunk": i
                })

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