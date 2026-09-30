from core.rag.retriever import ProjectRetriever
from core.rag.indexer import ProjectIndexer


class RagTool:
    def __init__(self):
        self.retriever = ProjectRetriever()

    def search_project(
        self,
        question: str,
        project_name: str = "asia",
        n_results: int = 5
    ):
        retriever = ProjectRetriever(
            project_name=project_name
        )

        results = retriever.search(
            question,
            n_results=n_results
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        if not documents:
            return "No encontré información relevante en el proyecto."

        response = ""

        for i, (doc, metadata) in enumerate(zip(documents, metadatas), start=1):
            file_path = metadata.get("file_path", "archivo desconocido")
            chunk = metadata.get("chunk", "?")

            response += f"\n--- Fragmento {i} ---\n"
            response += f"Archivo: {file_path}\n"
            response += f"Chunk: {chunk}\n"
            response += f"Contenido:\n{doc.strip()[:1200]}\n"

        return response
    
    def index_project(
        self,
        project_path: str = ".",
        project_name: str = "asia"
    ):
        indexer = ProjectIndexer(
            project_path=project_path,
            project_name=project_name
        )

        count = indexer.index_project()

        return f"Proyecto '{project_name}' indexado correctamente. Fragmentos guardados: {count}"