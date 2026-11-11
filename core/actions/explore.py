"""Lectura y explicación de archivos y proyectos, y búsqueda con RAG."""
from core.voice.notices import announce
import threading
from pathlib import Path

from core import prompts
from core.rag.entities import about_entities, missing_names
from core.rag.glossary import expand
from core.rag.translation_glossary import load_glossary, terms_in
from core.rag.instructions import source_notes, with_project_notes
from core.rag.keywords import (
    DEFAULT_DOMAIN as KEYWORDS_DOMAIN,
    DOMAIN_SETTING as KEYWORDS_DOMAIN_SETTING,
    SETTING as KEYWORDS_SETTING,
    enabled_for,
    zim_keywords,
)
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
    numbered_context,
    parse_fragments,
    quotes_text,
    verified_lines,
    verify_quotes,
    without_decoration,
)
from core.tool_output import clip
from core.actions.voice import VOICE_SETTING
from core.model_selection import model_for
from providers.provider_router import SYSTEM_PROMPT, wants_detail
from providers.ollama_provider import estimate_tokens, model_options, without_cut_notice

# Los mismos que config/defaults.json, por si falta la clave.
DEFAULT_ANSWER_LIMITS = {
    "explain_file": {"words": 150, "tokens": 450, "voice_tokens": 150},
    "summarize_file": {"words": 100, "tokens": 300, "voice_tokens": 150},
    "search_quotes": {"tokens": 1024},
    "search_answer": {"tokens": 512, "voice_tokens": 120},
}
# Los que recibe el modelo en /buscar.
RAG_FRAGMENTS = 5
VOICE_RAG_FRAGMENTS = 4
# El mismo que context_limits.search_text en config/defaults.json, por si falta la clave.
SEARCH_TEXT_CHARS = 6000
# Una pregunta en inglés: si no cabe aquí, no es una traducción.
TRANSLATION_TOKENS = 80
TRANSLATE_DOMAIN_SETTING = "translate_domain"
DEFAULT_TRANSLATE_DOMAIN = "general"
# La respuesta breve por voz va al modelo de este dominio si cabe en su contexto (brief_domain).
VOICE_BRIEF_DOMAIN_SETTING = "voice_brief_domain"
DEFAULT_VOICE_BRIEF_DOMAIN = "general"
# La estimación de tokens (3,3 caracteres por token) se queda corta con código denso.
BRIEF_ESTIMATE_MARGIN = 1.2
# Los mismos que context_limits.summarize_folder_voice en config/defaults.json.
DEFAULT_FOLDER_VOICE_LIMITS = {"max_files": 12, "max_chars_per_file": 250}


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

        if self.voice_brief(text):
            return self.brief_answer(
                prompts.voice_brief("Resume este archivo", file_path, content), limits,
                f"Para el resumen completo: resume {file_path} a fondo.",
            )

        if self.is_document(file_path):
            prompt = prompts.summarize_document(file_path, content, limits["words"])
        else:
            prompt = prompts.summarize_file(file_path, content)

        return self.ask_streaming(prompt, max_tokens=limits["tokens"])

    def handle_summarize_folder(self, text, params):
        folder_path = params.get("folder_path", ".")
        brief = self.voice_brief(text)
        # Con voz, el principio de cada archivo: cabe en el contexto del modelo ya cargado.
        voice_limits = (self.settings.get("context_limits") or {}).get("summarize_folder_voice")
        limits = (voice_limits or DEFAULT_FOLDER_VOICE_LIMITS) if brief else self.limit("summarize_folder")

        content = self.tool_registry.execute(
            "read_folder_context",
            folder_path=folder_path,
            **limits
        )

        if brief:
            return self.brief_answer(
                prompts.voice_brief("Resume de qué trata esta carpeta", folder_path, content, what="de la carpeta"),
                self.answer_limits("summarize_file"), f"Para el resumen completo: resume la carpeta {folder_path} a fondo.",
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
        # Con voz: "Busco en la biblioteca." ya sintetizado; la respuesta espera a las citas.
        announce(self, "search")

        # La regla de la entidad mira la pregunta tal cual, sin los equivalentes del glosario.
        asked = question
        question, translated, keywords = self.zim_search_inputs(question)
        # Con voz: el 7B (citas y respuesta) carga mientras se buscan los fragmentos.
        self.preload_answer_model()

        rag_context = self.tool_registry.execute(
            "search_project_rag",
            question=question,
            project_name=project_name,
            # Con voz, uno menos: el prompt de las citas es lo que más tarda en el 7B.
            n_results=VOICE_RAG_FRAGMENTS if self.voice_brief(text) else RAG_FRAGMENTS,
            translated=translated,
            keywords=keywords
        )

        # Sin nada relevante, ni se llama al modelo: no hay de dónde responder.
        if rag_context in prompts.NOTHING_TO_ANSWER or rag_context.startswith(prompts.NO_DIRECT_ANSWER):
            return rag_context

        # Un comando o paquete que no sale en ningún fragmento de fuera: lo que se encontró es de otro.
        missing = missing_names(asked, parse_fragments(rag_context), self.source_names())

        if missing:
            return f"{prompts.NO_INFO_ABOUT} {' ni '.join(missing)}."

        # Sin subrayados ni separadores: ni el modelo los copia ni valen como cita.
        rag_context = without_decoration(rag_context)

        # Con tope: un 7B puede no parar nunca (llenó 16384 tokens con una pregunta de Python).
        # Si se corta, vale lo que copió entero; la última línea a medias no se verifica.
        # Con voz, números de línea: el modelo escribe "41, 43-45" y el código copia el texto
        # exacto (más rápido). Por texto, el modelo copia las líneas, como siempre.
        numbers = self.voice_brief(text)
        extracted = self.provider_router.ask(
            prompts.extract_quotes(question, numbered_context(rag_context) if numbers else rag_context, translated,
                                   source_notes(rag_context, Library().all()), numbers=numbers),
            max_tokens=self.answer_limits("search_quotes")["tokens"],
        )
        quotes = verify_quotes(without_cut_notice(extracted)[0], rag_context)

        # Si la pregunta nombra un lugar, una persona o una obra, la línea o su artículo tiene que
        # nombrarlo: el 7B contestaba por el puente de Valdecierzo con el Puente de Hierro de Soria.
        quotes, missing = about_entities(quotes, asked, self.source_names())

        if missing:
            return f"{prompts.NO_INFO_ABOUT} {' ni '.join(missing)}."

        # Sin líneas verificadas no hay respuesta del modelo: no hay con qué comprobarla.
        if not quotes:
            return best_fragments(rag_context)

        # Con voz, 1 o 2 frases y un tope: se lee cuando está entera y verificada.
        brief = self.voice_brief(text)
        limits = self.answer_limits("search_answer")
        answer, cut = without_cut_notice(self.provider_router.ask(
            prompts.answer_from_quotes(question, quotes_text(quotes), brief=brief),
            max_tokens=limits.get("voice_tokens", limits["tokens"]) if brief else limits["tokens"]
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

    def preload_answer_model(self):
        """Con voz, la carga del modelo de las citas en un hilo: eran ~9 s esperando al final.

        Después de la traducción (qwen3), que la precarga descarga; nomic, el de los
        embeddings, puede convivir con el 7B durante la búsqueda.
        """
        engine = getattr(self, "intent_engine", None)

        if getattr(self, "action_notice", None) is None or not hasattr(engine, "preload"):
            return None

        # Sin descargar nomic: si no, el embedding de la pregunta esperaba a que cargara el 7B.
        keep = [self.settings.get("embedding_model")] if self.settings.get("embedding_model") else []
        thread = threading.Thread(target=engine.preload, kwargs={"model": model_for(self.settings, "code"), "keep": keep},
                                  name="asia-precarga-citas", daemon=True)
        thread.start()
        return thread

    def source_names(self):
        """Los nombres de las fuentes, que no son nombres de la pregunta (core/rag/entities.py)."""
        return [source.name for source in Library().all()] + ["Wikipedia"]

    def zim_search_inputs(self, question):
        """(pregunta, traducida, palabras clave) con que /buscar busca; check_rag mide con lo mismo."""
        # También para el modelo: si no, no ve la relación con lo que dicen los fragmentos.
        question = expand(question, Library().all())
        translated = self.translated_question(question)
        return question, translated, self.zim_search_keywords(question)

    def zim_search_keywords(self, question):
        """{idioma: [búsquedas]} para una pregunta a un .zim (rag.zim_keywords); {} si no toca.

        Una llamada al modelo de rag.zim_keywords_domain por idioma: con "en preguntas"
        puede ser una en español y otra en inglés.
        """
        rag = self.settings.get("rag") or {}
        setting = rag.get(KEYWORDS_SETTING)
        domain = rag.get(KEYWORDS_DOMAIN_SETTING, KEYWORDS_DOMAIN)

        if not setting:
            return {}

        sources = Library().all()
        named = named_in_question(question, sources)
        targets = ([named] if named.kind in ZIM_KINDS else []) if named else questions_group(question, sources)
        found = {}

        for source in targets:
            if enabled_for(setting, source) and source.language not in found:
                text = without_source(question, source) if named else without_group(question)
                found[source.language] = zim_keywords(text, source, self.provider_router.ask, domain)

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
        # Con los términos técnicos del glosario: "nombre del equipo" es hostname, no "team name".
        terms = terms_in(text, load_glossary())
        # Con el modelo ya cargado (qwen3): traducir una frase no necesita el 7B, que tardaba
        # en cargar y en escribir. rag.translate_domain para cambiarlo.
        domain = (self.settings.get("rag") or {}).get(TRANSLATE_DOMAIN_SETTING, DEFAULT_TRANSLATE_DOMAIN)
        answer = self.provider_router.ask(prompts.translate_question(text, terms), max_tokens=TRANSLATION_TOKENS, domain=domain)
        return clean_translation(answer)

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

        if self.voice_brief(text):
            prompt = with_project_notes(
                prompts.voice_brief("Explica para qué sirve este archivo", file_path, content), file_path, Library().all()
            )
            return self.brief_answer(prompt, limits, f"Para la explicación completa: explica {file_path} a fondo.")

        # Un .md o .txt no tiene clases ni métodos: plantilla de documento.
        if self.is_document(file_path):
            prompt = prompts.explain_document(file_path, content, limits["words"])
        else:
            prompt = prompts.explain_file(file_path, content)

        # El ASIA.md de su fuente, si tiene (core/rag/instructions.py).
        prompt = with_project_notes(prompt, file_path, Library().all())
        return self.ask_streaming(prompt, max_tokens=limits["tokens"])

    def voice_brief(self, text):
        """Con la voz activa, salvo "a fondo": 1 a 3 frases (sin voz, nada cambia).
        La plantilla larga con 415 tokens tardaba 65 s en empezar a sonar."""
        return bool(self.settings.get(VOICE_SETTING)) and not wants_detail(text)

    def brief_answer(self, prompt, limits, more):
        """La respuesta corta y, solo en pantalla, cómo pedir la larga: entre corchetes,
        la lectura en voz alta se la salta (core/voice/speakable.py)."""
        max_tokens = limits.get("voice_tokens", limits["tokens"])
        answer = self.ask_streaming(prompt, max_tokens=max_tokens, domain=self.brief_domain(prompt, max_tokens))
        return f"{answer}\n\n[{more}]"

    def brief_domain(self, prompt, max_tokens) -> str:
        """El dominio del modelo de la respuesta breve por voz.

        voice_brief_domain (por defecto "general": qwen3, el del IntentEngine, que ya
        está cargado) si el prompt y la respuesta caben en su contexto; si no, "code"
        (el 7B, con 16384). Cambiar de modelo costaba ~10 s de carga del 7B antes de
        la primera palabra, y el primer audio de las acciones pasaba de 15 s.
        """
        domain = self.settings.get(VOICE_BRIEF_DOMAIN_SETTING) or DEFAULT_VOICE_BRIEF_DOMAIN

        if domain == "code":
            return domain

        num_ctx = model_options(self.settings, model_for(self.settings, domain)).get("num_ctx")
        needed = estimate_tokens([{"content": SYSTEM_PROMPT}, {"content": prompt}]) * BRIEF_ESTIMATE_MARGIN + max_tokens
        return domain if num_ctx and needed <= num_ctx else "code"

    def ask_streaming(self, prompt, **options):
        """ask con el on_chunk que dejó el launcher (action_stream, solo con voz): la respuesta
        se escribe y se lee frase por frase mientras llega. Sin él, la llamada de siempre."""
        on_chunk = getattr(self, "action_stream", None)

        if on_chunk is not None:
            options["on_chunk"] = on_chunk

        return self.provider_router.ask(prompt, **options)

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
