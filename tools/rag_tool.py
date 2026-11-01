from config.settings_manager import SettingsManager
from core.prompts import NOT_FOUND
from core.rag.indexer import ProjectIndexer, unload_chat_models
from core.rag.library import CITE_PREFIX, DEFAULT_KIND, Library, citation, named_in_question, without_source
from core.rag.retriever import relevant, search_collections

# El mismo que rag.min_coverage en config/defaults.json, por si falta la clave.
DEFAULT_MIN_COVERAGE = 0.3


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
        collections = [named.collection] if named else [s.collection for s in sources] or [project_name]

        query = without_source(question, named) if named else question
        hits = search_collections(query, collections, n_results=n_results)

        limits = SettingsManager().get("rag") or {}

        if not relevant(hits, limits.get("min_coverage", DEFAULT_MIN_COVERAGE)):
            return NOT_FOUND

        response = ""

        for i, hit in enumerate(hits, start=1):
            source = hit.metadata.get("source", project_name)
            kind = hit.metadata.get("kind", DEFAULT_KIND)

            response += f"\n--- Fragmento {i} ---\n"
            response += f"Fuente: {source} ({kind})\n"
            response += f"{CITE_PREFIX}{citation(hit.metadata)}\n"
            response += f"Contenido:\n{hit.document.strip()[:1200]}\n"

        return response

    def index_project(
        self,
        project_name: str,
        project_path: str = ".",
        kind: str = DEFAULT_KIND
    ):
        unload_chat_models()

        indexer = ProjectIndexer(
            project_path=project_path,
            project_name=project_name,
            kind=kind
        )

        count = indexer.index_project()
        Library().save(project_name, kind, indexer.project_path.as_posix(), count)

        return (
            f"Fuente '{project_name}' al día: {count} fragmentos "
            f"({indexer.changed} archivos reindexados, {indexer.unchanged} sin cambios)."
        )
