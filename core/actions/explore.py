"""Lectura y explicación de archivos y proyectos, y búsqueda con RAG."""
from pathlib import Path

from core import prompts
from core.rag.glossary import expand
from core.rag.library import Library, is_refusal
from core.rag.quotes import best_fragments, draft_problems, is_thin, quotes_text, verified_lines, verify_quotes

# Los mismos que config/defaults.json, por si falta la clave.
DEFAULT_ANSWER_LIMITS = {
    "explain_file": {"words": 150, "tokens": 450},
    "summarize_file": {"words": 100, "tokens": 300},
}
# Los que recibe el modelo en /buscar.
RAG_FRAGMENTS = 5


class ExploreActions:
    HANDLERS = {
        "summarize_file": "handle_summarize_file",
        "summarize_folder": "handle_summarize_folder",
        "index_project_rag": "handle_index_project_rag",
        "search_project_rag": "handle_search_project_rag",
        "explain_file": "handle_explain_file",
        "find_references": "handle_find_references",
        "explain_symbol": "handle_explain_symbol",
        "map_project": "handle_map_project",
        "find_dependencies": "handle_find_dependencies",
    }

    def handle_summarize_file(self, text, params):
        file_path = params.get("file_path")

        if not file_path:
            return "Necesito la ruta del archivo para resumirlo."

        content = self.tool_registry.execute(
            "read_file_preview",
            file_path=file_path,
            max_chars=self.limit("summarize_file")
        )
        limits = self.answer_limits("summarize_file")

        if self.is_document(file_path):
            prompt = prompts.summarize_document(file_path, content, limits["words"])
        else:
            prompt = prompts.summarize_file(file_path, content)

        return self.provider_router.ask(prompt, max_tokens=limits["tokens"])

    def handle_summarize_folder(self, text, params):
        folder_path = params.get("folder_path", ".")

        content = self.tool_registry.execute(
            "read_folder_context",
            folder_path=folder_path,
            **self.limit("summarize_folder")
        )

        return self.provider_router.ask(prompts.summarize_folder(folder_path, content))

    def handle_index_project_rag(self, text, params):
        project_path = params.get("project_path", ".")
        project_name = self.active_project()

        return self.tool_registry.execute(
            "index_project_rag",
            project_path=project_path,
            project_name=project_name
        )

    def handle_search_project_rag(self, text, params):
        question = params.get("question", text)
        project_name = self.active_project()

        if not question.strip():
            return "Escribe la pregunta: /buscar <pregunta>."

        # También por "/buscar", que no pasa por el IntentEngine.
        self.last_action = "search_project_rag"

        # También para el modelo: si no, no ve la relación con lo que dicen los fragmentos.
        question = expand(question, Library().all())

        rag_context = self.tool_registry.execute(
            "search_project_rag",
            question=question,
            project_name=project_name,
            n_results=RAG_FRAGMENTS
        )

        # Sin nada relevante, ni se llama al modelo: no hay de dónde responder.
        if rag_context == prompts.NOT_FOUND or rag_context.startswith(prompts.NO_DIRECT_ANSWER):
            return rag_context

        extracted = self.provider_router.ask(prompts.extract_quotes(question, rag_context))
        quotes = verify_quotes(extracted, rag_context)

        # Sin líneas verificadas no hay respuesta del modelo: no hay con qué comprobarla.
        if not quotes:
            return best_fragments(rag_context)

        answer = self.provider_router.ask(prompts.answer_from_quotes(question, quotes_text(quotes)))

        if is_refusal(answer) or is_thin(answer):
            return best_fragments(rag_context)

        # La redacción no se comprueba frase a frase, pero los nombres y las citas sí.
        if draft_problems(answer, quotes, rag_context):
            return f"{prompts.INVALID_DRAFT}\n\n{verified_lines(quotes)}"

        return f"{answer}\n\n{verified_lines(quotes)}"

    def handle_explain_file(self, text, params):
        file_path = params.get("file_path")

        if not file_path:
            return "Necesito la ruta del archivo."

        content = self.tool_registry.execute(
            "read_file_preview",
            file_path=file_path,
            max_chars=self.limit("explain_file")
        )
        limits = self.answer_limits("explain_file")

        # Un .md o .txt no tiene clases ni métodos: plantilla de documento.
        if self.is_document(file_path):
            prompt = prompts.explain_document(file_path, content, limits["words"])
        else:
            prompt = prompts.explain_file(file_path, content)

        return self.provider_router.ask(prompt, max_tokens=limits["tokens"])

    def is_document(self, file_path):
        """True si no es código (.md, .txt, .json...): ver code_extensions en config."""
        code = {ext.lower() for ext in self.settings.get("code_extensions") or []}
        return bool(code) and Path(file_path).suffix.lower() not in code

    def answer_limits(self, action):
        """{"words": ..., "tokens": ...} de answer_limits en config (tokens = num_predict)."""
        configured = (self.settings.get("answer_limits") or {}).get(action)
        return configured or DEFAULT_ANSWER_LIMITS[action]

    def handle_find_references(self, text, params):
        query = params.get("query")
        folder_path = params.get("folder_path", ".")

        if not query:
            return "Necesito saber qué referencia quieres buscar."

        raw_results = self.tool_registry.execute(
            "search_text",
            query=query,
            folder_path=folder_path
        )

        return self.provider_router.ask(prompts.find_references(query, raw_results))

    def handle_explain_symbol(self, text, params):
        symbol = params.get("symbol")
        folder_path = params.get("folder_path", ".")

        if not symbol:
            return "Necesito saber qué clase, función o método quieres explicar."

        raw_results = self.tool_registry.execute(
            "search_text",
            query=symbol,
            folder_path=folder_path
        )

        return self.provider_router.ask(prompts.explain_symbol(symbol, raw_results))

    def handle_map_project(self, text, params):
        folder_path = params.get("folder_path", ".")

        content = self.tool_registry.execute(
            "read_folder_context",
            folder_path=folder_path,
            **self.limit("map_project")
        )

        return self.provider_router.ask(prompts.map_project(content))

    def handle_find_dependencies(self, text, params):
        query = params.get("query")
        folder_path = params.get("folder_path", ".")

        if not query:
            return "Necesito saber qué dependencia, clase o módulo quieres buscar."

        raw_results = self.tool_registry.execute(
            "search_text",
            query=query,
            folder_path=folder_path
        )

        return self.provider_router.ask(prompts.find_dependencies(query, raw_results))
