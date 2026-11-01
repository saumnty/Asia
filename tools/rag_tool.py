from core.rag.indexer import ProjectIndexer, unload_chat_models
from core.rag.library import DEFAULT_KIND, Library, citation, named_in_question
from core.rag.retriever import search_collections


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

        hits = search_collections(question, collections, n_results=n_results)

        if not hits:
            return "No encontré información relevante en tus proyectos."

        response = ""

        for i, hit in enumerate(hits, start=1):
            source = hit.metadata.get("source", project_name)
            kind = hit.metadata.get("kind", DEFAULT_KIND)

            response += f"\n--- Fragmento {i} ---\n"
            response += f"Fuente: {source} ({kind})\n"
            response += f"Cita: {citation(hit.metadata)}\n"
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
