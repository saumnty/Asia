"""Lectura y explicación de archivos y proyectos, y búsqueda con RAG."""
from pathlib import Path

from core import prompts
from core.rag.glossary import expand
from core.rag.instructions import source_notes, with_project_notes
from core.rag.keywords import SETTING as KEYWORDS_SETTING, enabled_for, zim_keywords
from core.rag.library import (
    ZIM_KINDS,
    Library,
    clean_translation,
    is_refusal,
    named_in_question,
    needs_translation,
    questions_group,
    without_group,
    without_source,
)
from core.rag.quotes import (
    best_fragments,
    check_draft,
    is_thin,
    quotes_text,
    verified_lines,
    verify_quotes,
    without_decoration,
)
from core.tool_output import clip
from providers.ollama_provider import without_cut_notice

# Los mismos que config/defaults.json, por si falta la clave.
DEFAULT_ANSWER_LIMITS = {
    "explain_file": {"words": 150, "tokens": 450},
    "summarize_file": {"words": 100, "tokens": 300},
    "search_quotes": {"tokens": 1024},
    "search_answer": {"tokens": 512},
}
# Los que recibe el modelo en /buscar.
RAG_FRAGMENTS = 5
# El mismo que context_limits.search_text en config/defaults.json, por si falta la clave.
SEARCH_TEXT_CHARS = 6000
# Una pregunta en inglés: si no cabe aquí, no es una traducción.
TRANSLATION_TOKENS = 80


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

        translated = self.translated_question(question)

        rag_context = self.tool_registry.execute(
            "search_project_rag",
            question=question,
            project_name=project_name,
            n_results=RAG_FRAGMENTS,
            translated=translated,
            keywords=self.zim_search_keywords(question)
        )

        # Sin nada relevante, ni se llama al modelo: no hay de dónde responder.
        if rag_context in prompts.NOTHING_TO_ANSWER or rag_context.startswith(prompts.NO_DIRECT_ANSWER):
            return rag_context

        # Sin subrayados ni separadores: ni el modelo los copia ni valen como cita.
        rag_context = without_decoration(rag_context)

        # Con tope: un 7B puede no parar nunca (llenó 16384 tokens con una pregunta de Python).
        # Si se corta, vale lo que copió entero; la última línea a medias no se verifica.
        extracted = self.provider_router.ask(
            prompts.extract_quotes(question, rag_context, translated, source_notes(rag_context, Library().all())),
            max_tokens=self.answer_limits("search_quotes")["tokens"],
        )
        quotes = verify_quotes(without_cut_notice(extracted)[0], rag_context)

        # Sin líneas verificadas no hay respuesta del modelo: no hay con qué comprobarla.
        if not quotes:
            return best_fragments(rag_context)

        answer, cut = without_cut_notice(self.provider_router.ask(
            prompts.answer_from_quotes(question, quotes_text(quotes)), max_tokens=self.answer_limits("search_answer")["tokens"]
        ))

        if is_refusal(answer) or is_thin(answer):
            return best_fragments(rag_context)

        # Las frases que quedan tienen nombres reales, no significado comprobado. El aviso
        # de recorte lo escribe el código: va al final, sin pasar por la comprobación.
        shown = check_draft(answer, quotes, question)[0]
        lines = verified_lines(quotes)

        if shown:
            summary = "\n".join(shown + [cut] if cut else shown)
            return f"{lines}\n\n{prompts.UNVERIFIED_SUMMARY}\n\n{summary}"

        return f"{prompts.INVALID_DRAFT}\n\n{lines}"

    def zim_search_keywords(self, question):
        """{idioma: [búsquedas]} para una pregunta a un .zim (rag.zim_keywords); {} si no toca.

        Una llamada a qwen3 por idioma: con "en preguntas" puede ser una en español y
        otra en inglés.
        """
        setting = (self.settings.get("rag") or {}).get(KEYWORDS_SETTING)

        if not setting:
            return {}

        sources = Library().all()
        named = named_in_question(question, sources)
        targets = ([named] if named.kind in ZIM_KINDS else []) if named else questions_group(question, sources)
        found = {}

        for source in targets:
            if enabled_for(setting, source) and source.language not in found:
                text = without_source(question, source) if named else without_group(question)
                found[source.language] = zim_keywords(text, source, self.provider_router.ask)

        return found

    def translated_question(self, question):
        """La pregunta en inglés si nombra una fuente en ese idioma; si no, vacía.

        En una búsqueda general no compensa: es otra llamada al modelo en cada pregunta.
        """
        sources = Library().all()

        if not (self.settings.get("rag") or {}).get("translate_question") or not needs_translation(question, sources):
            return ""

        named = named_in_question(question, sources)
        text = without_source(question, named) if named else question
        return clean_translation(self.provider_router.ask(prompts.translate_question(text), max_tokens=TRANSLATION_TOKENS))

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

        # El ASIA.md de su fuente, si tiene (core/rag/instructions.py).
        prompt = with_project_notes(prompt, file_path, Library().all())
        return self.provider_router.ask(prompt, max_tokens=limits["tokens"])

    def is_document(self, file_path):
        """True si no es código (.md, .txt, .json...): ver code_extensions en config."""
        code = {ext.lower() for ext in self.settings.get("code_extensions") or []}
        return bool(code) and Path(file_path).suffix.lower() not in code

    def answer_limits(self, action):
        """{"words": ..., "tokens": ...} de answer_limits en config (tokens = num_predict)."""
        configured = (self.settings.get("answer_limits") or {}).get(action)
        return configured or DEFAULT_ANSWER_LIMITS[action]

    def search_text_for_model(self, query, folder_path):
        """search_text para el prompt: un nombre común puede salir en cientos de líneas (core/tool_output.py)."""
        results = self.tool_registry.execute("search_text", query=query, folder_path=folder_path)
        limit = (self.settings.get("context_limits") or {}).get("search_text", SEARCH_TEXT_CHARS)
        return clip(results, limit, f"search_text-{query}")

    def handle_find_references(self, text, params):
        query = params.get("query")
        folder_path = params.get("folder_path", ".")

        if not query:
            return "Necesito saber qué referencia quieres buscar."

        raw_results = self.search_text_for_model(query, folder_path)

        return self.provider_router.ask(prompts.find_references(query, raw_results))

    def handle_explain_symbol(self, text, params):
        symbol = params.get("symbol")
        folder_path = params.get("folder_path", ".")

        if not symbol:
            return "Necesito saber qué clase, función o método quieres explicar."

        raw_results = self.search_text_for_model(symbol, folder_path)

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

        raw_results = self.search_text_for_model(query, folder_path)

        return self.provider_router.ask(prompts.find_dependencies(query, raw_results))
