from pathlib import Path

from config.settings_manager import SettingsManager
from core.prompts import NOT_FOUND, NOT_FOUND_IN_QA, NOT_FOUND_IN_WIKIPEDIA, QA_MISSING, WIKIPEDIA_MISSING
from core.rag.glossary import glossary_terms
from core.rag.indexer import ProjectIndexer, unload_chat_models
from core.rag.library import (
    DEFAULT_KIND,
    DEFAULT_LANGUAGE,
    ENCYCLOPEDIA,
    ENGLISH_SOURCE,
    ORIGIN_PREFIX,
    QUESTIONS,
    ZIM_KINDS,
    Library,
    Source,
    fragment_header,
    named_in_question,
    searched_sources,
    without_source,
)
from core.rag.questions import qa_hits, zim_language
from core.rag.quotes import best_fragments
from core.rag.retriever import relevant, search_collections
from core.rag.wikipedia import wikipedia_hits, zim_summary
from core.provenance import PUBLICA, RAG, LabeledResult

# Los mismos que rag en config/defaults.json, por si falta la clave.
DEFAULT_MIN_COVERAGE = 0.3
# Calibrada con nomic-embed-text: otro modelo de embeddings tiene otra escala.
DEFAULT_MAX_DISTANCE = 392.0
WIKIPEDIA_LICENSE = "CC BY-SA 4.0"
WIKIPEDIA_URL = "https://{language}.wikipedia.org/wiki/{{}}"
# Stack Exchange: 2.5, 3.0 o 4.0 según la fecha de cada publicación.
QA_LICENSE = "CC BY-SA (versión según la fecha)"
ZIM_SUFFIX = ".zim"


class RagTool:
    def search_project(
        self,
        question: str,
        project_name: str,
        n_results: int = 5,
        translated: str = ""
    ):
        """Busca en todas las fuentes, o en la de "en <fuente>". Sin fuentes, en el proyecto activo.

        translated es la pregunta en inglés, para las fuentes en ese idioma.
        """
        sources = Library().all()
        named = named_in_question(question, sources)
        searched = searched_sources(question, sources)
        collections = [source.collection for source in searched] or [project_name]
        english = [source.collection for source in searched if source.language == ENGLISH_SOURCE]

        in_wikipedia = bool(named) and named.kind == ENCYCLOPEDIA
        in_questions = bool(named) and named.kind == QUESTIONS
        query = without_source(question, named) if named else question

        if (in_wikipedia or in_questions) and not Path(named.path).is_file():
            return WIKIPEDIA_MISSING if in_wikipedia else QA_MISSING

        if in_wikipedia:
            hits = wikipedia_hits(query, named, n_results, translated=translated)
        elif in_questions:
            hits = qa_hits(query, named, n_results, translated=translated)
        else:
            # Los términos del glosario cuentan aparte (core/rag/glossary.py).
            boost = glossary_terms(question, sources)
            hits = search_collections(
                query, collections, n_results=n_results, translated=translated, english=english, boost=boost,
            )

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

        # Pública solo si lo son todas las consultadas, aunque los fragmentos sean de una.
        label = PUBLICA if searched and all(source.publica for source in searched) else RAG

        if relevant(hits, coverage, limits.get("max_distance", DEFAULT_MAX_DISTANCE)):
            return LabeledResult(response, label)

        # Quien nombra la fuente sabe que el tema está ahí: la distancia mide mal el
        # español contra el inglés. Se enseña lo encontrado, sin pasar por el modelo.
        if named and hits:
            return LabeledResult(best_fragments(response), label)

        return NOT_FOUND_IN_WIKIPEDIA if in_wikipedia else NOT_FOUND_IN_QA if in_questions else NOT_FOUND

    def index_project(
        self,
        project_name: str,
        project_path: str = None,
        kind: str = None,
        url: str = "",
        license: str = "",
        named_only: bool = None,
        language: str = None
    ):
        # Volver a indexar con /indexar <nombre> no le cambia nada a la fuente.
        registered = Library().get(project_name)
        known = registered or Source(project_name, DEFAULT_KIND, ".", "")
        project_path = project_path or known.path
        kind = kind or known.kind

        if kind in ZIM_KINDS:
            return self.register_zim(project_name, kind, project_path, url, license, language, registered)

        unload_chat_models()
        url = url or known.url
        license = license or known.license
        named_only = known.named_only if named_only is None else named_only
        language = language or known.language

        indexer = ProjectIndexer(
            project_path=project_path,
            project_name=project_name,
            kind=kind,
            url=url,
            license=license
        )

        count = indexer.index_project()
        Library().save(
            project_name, kind, indexer.project_path.as_posix(), count, url, license, named_only, language, known.publica
        )

        return (
            f"Fuente '{project_name}' al día: {count} fragmentos "
            f"({indexer.changed} archivos reindexados, {indexer.unchanged} sin cambios)."
        )

    def register_zim(self, name: str, kind: str, path: str, url: str, license: str, language: str, known):
        """Una enciclopedia o un sitio de preguntas no se indexa: se apunta al .zim. Pública y solo con "en <fuente>".

        En un sitio de Stack Exchange la licencia depende de la fecha de cada
        publicación (core/rag/qa_page.py) y el idioma sale del metadato Language.
        """
        zim = Path(path)

        if zim.suffix.lower() != ZIM_SUFFIX or not zim.is_file():
            return f"No encuentro un archivo .zim en {path}."

        summary = zim_summary(zim)

        if not summary["searchable"]:
            return f"{zim.name} no trae índice de búsqueda: hace falta un .zim con _ftindex."

        publica = known.publica if known else True

        if kind == QUESTIONS:
            from libzim.reader import Archive

            language = language or (known.language if known else "") or zim_language(Archive(str(zim)))
            license = license or (known.license if known else "") or QA_LICENSE
        else:
            language = language or (known.language if known else DEFAULT_LANGUAGE)
            url = url or (known.url if known else "") or WIKIPEDIA_URL.format(language=language)
            license = license or (known.license if known else "") or WIKIPEDIA_LICENSE

        Library().save(name, kind, zim.as_posix(), summary["articles"], url, license, True, language, publica)
        units = "páginas" if kind == QUESTIONS else "artículos"
        return f"Fuente '{name}' lista: {summary['articles']} {units} de {zim.name}. Pregúntale con \"en {name}\"."
