from config.settings_manager import SettingsManager
from core.prompts import NOT_FOUND
from core.rag.indexer import ProjectIndexer, unload_chat_models
from core.rag.library import DEFAULT_KIND, ORIGIN_PREFIX, Library, Source, fragment_header, named_in_question, without_source
from core.rag.quotes import best_fragments
from core.rag.retriever import relevant, search_collections

# Los mismos que rag en config/defaults.json, por si falta la clave.
DEFAULT_MIN_COVERAGE = 0.3
# Calibrada con nomic-embed-text: otro modelo de embeddings tiene otra escala.
DEFAULT_MAX_DISTANCE = 392.0


class RagTool:
    def search_project(
        self,
        question: str,
        project_name: str,
        n_results: int = 5
    ):
        """Busca en todas las fuentes, o en la de "en <fuente>". Sin fuentes, en el proyecto activo."""
        sources = Library().all()
        named = named_in_question(question, sources)
        collections = [named.collection] if named else [s.collection for s in sources if not s.named_only] or [project_name]

        query = without_source(question, named) if named else question
        hits = search_collections(query, collections, n_results=n_results)

        limits = SettingsManager().get("rag") or {}

        coverage = limits.get("min_coverage", DEFAULT_MIN_COVERAGE)
        response = ""

        for hit in hits:
            source = hit.metadata.get("source", project_name)
            kind = hit.metadata.get("kind", DEFAULT_KIND)

            response += f"\n{fragment_header(hit.metadata)}\n"
            response += f"Fuente: {source} ({kind})\n"

            if hit.metadata.get("origin"):
                response += f"{ORIGIN_PREFIX}{hit.metadata['origin']}\n"

            response += f"Contenido:\n{hit.document.strip()[:1200]}\n"

        if relevant(hits, coverage, limits.get("max_distance", DEFAULT_MAX_DISTANCE)):
            return response

        # Quien nombra la fuente sabe que el tema está ahí: la distancia mide mal el
        # español contra el inglés. Se enseña lo encontrado, sin pasar por el modelo.
        return best_fragments(response) if named and hits else NOT_FOUND

    def index_project(
        self,
        project_name: str,
        project_path: str = None,
        kind: str = None,
        url: str = "",
        license: str = "",
        named_only: bool = None
    ):
        unload_chat_models()

        # Volver a indexar con /indexar <nombre> no le cambia nada a la fuente.
        known = Library().get(project_name) or Source(project_name, DEFAULT_KIND, ".", "")
        project_path = project_path or known.path
        kind = kind or known.kind
        url = url or known.url
        license = license or known.license
        named_only = known.named_only if named_only is None else named_only

        indexer = ProjectIndexer(
            project_path=project_path,
            project_name=project_name,
            kind=kind,
            url=url,
            license=license
        )

        count = indexer.index_project()
        Library().save(project_name, kind, indexer.project_path.as_posix(), count, url, license, named_only)

        return (
            f"Fuente '{project_name}' al día: {count} fragmentos "
            f"({indexer.changed} archivos reindexados, {indexer.unchanged} sin cambios)."
        )
