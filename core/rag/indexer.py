import hashlib
import sys
from pathlib import Path

from config.settings_manager import SettingsManager
from core.rag.chunking import chunk_text
from core.rag.embedder import OllamaEmbedder
from core.rag.exclusions import SourceFilter
from core.rag.library import origin_of
from core.rag.simulink import is_model_name, model_text
from core.rag.vector_store import VectorStore

# Cambiar el troceado invalida lo indexado: el hash incluye esta versión.
CHUNKER_VERSION = "2"


def unload_chat_models():
    """Indexar es largo: el 7B no se queda en memoria junto al modelo de embeddings."""
    settings = SettingsManager()

    try:
        import ollama

        from providers.ollama_models import unload_others

        unload_others(ollama.Client(host=settings.get("ollama_host")), settings.get("embedding_model"), settings)
    except Exception:
        pass


def content_hash(text: str) -> str:
    return hashlib.sha256(f"{CHUNKER_VERSION}\n{text}".encode("utf-8", "surrogatepass")).hexdigest()


def indexable_text(chunk, relative_path: str) -> str:
    """Lo que se embebe y se busca: dónde está el fragmento y su contenido."""
    where = f"{relative_path} · {chunk.label}" if chunk.label else relative_path
    return f"{where}\n{chunk.text}"


class ProjectIndexer:
    def __init__(self, project_path: str, project_name: str, persist_dir=None, kind="proyecto", url="", license=""):
        # Ruta absoluta: los fragmentos se identifican igual sin importar
        # desde qué carpeta se indexe o se pregunte.
        self.project_path = Path(project_path).resolve()
        self.project_name = project_name
        self.kind = kind
        self.url = url
        self.license = license
        self.embedder = OllamaEmbedder()
        self.changed = 0
        self.unchanged = 0

        settings = SettingsManager()
        self.filter = SourceFilter(
            self.project_path, settings.text_extensions(), settings.ignored_dirs(include_tests=True),
        )

        self.store = VectorStore(
            persist_dir=persist_dir,
            collection_name=project_name
        )

    def read_files(self) -> dict:
        """{ruta absoluta: texto} de los archivos indexables."""
        files = {}

        for file_path in self.filter.files():
            try:
                files[file_path] = (
                    model_text(file_path) if is_model_name(file_path)
                    else file_path.read_text(encoding="utf-8", errors="ignore")
                )
            except Exception:
                continue

        return files

    def fragments_of(self, file_path: Path, text: str) -> list:
        """(id, documento, metadatos) de cada fragmento de un archivo."""
        relative = file_path.relative_to(self.project_path).as_posix()
        file_hash = content_hash(text)

        return [
            (
                f"{file_path.as_posix()}::{chunk.start_line}-{chunk.end_line}::{i}",
                indexable_text(chunk, relative),
                {
                    "file_path": file_path.as_posix(),
                    "relative_path": relative,
                    "source": self.project_name,
                    "kind": self.kind,
                    "origin": origin_of(relative, self.url, self.license),
                    "chunk": i,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "label": chunk.label,
                    "file_hash": file_hash,
                },
            )
            for i, chunk in enumerate(chunk_text(text, file_path.suffix))
        ]

    def index_project(self) -> int:
        """Reindexa solo lo que cambió. Devuelve cuántos fragmentos hay en total."""
        files = self.read_files()
        stored = self.store.file_hashes()
        current = {path.as_posix(): content_hash(text) for path, text in files.items()}

        changed = [path for path in files if stored.get(path.as_posix()) != current[path.as_posix()]]
        fragments = [fragment for path in changed for fragment in self.fragments_of(path, files[path])]

        ids = [fragment[0] for fragment in fragments]
        documents = [fragment[1] for fragment in fragments]
        metadatas = [fragment[2] for fragment in fragments]

        if documents:
            print(f"[Indexando {len(documents)} fragmentos de {len(changed)} archivos]", file=sys.stderr, flush=True)

        embeddings = self.embedder.embed_documents(documents)

        # Se borran los fragmentos previos solo después de generar todos los
        # embeddings, para no dejar el índice vacío si Ollama falla a medias:
        # los de archivos que cambiaron, los de archivos que ya no están y los
        # de índices creados antes de la fase 2 (rutas relativas, sin hash).
        self.store.delete_where_file_path(lambda path: self.is_outdated(path, current, stored))

        if ids:
            self.store.add_documents(ids, documents, embeddings, metadatas)

        self.changed = len(changed)
        self.unchanged = len(files) - len(changed)
        return self.store.collection.count()

    def is_outdated(self, file_path: str, current: dict, stored: dict) -> bool:
        if not self.is_inside_project(file_path):
            return False

        return file_path not in current or current[file_path] != stored.get(file_path)

    def is_inside_project(self, file_path: str) -> bool:
        # Los índices creados antes de la fase 2 guardaban rutas relativas
        # (ambiguas sin la carpeta de origen): se reemplazan al reindexar.
        if not Path(file_path).is_absolute():
            return True

        root = self.project_path.as_posix()

        return file_path == root or file_path.startswith(root.rstrip("/") + "/")
