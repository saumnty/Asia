"""Preguntas y respuestas offline (fase H, capa 4): sitios de Stack Exchange en .zim.

La misma cadena que Wikipedia (core/rag/wikipedia.py): la búsqueda del .zim
elige las páginas de pregunta, qa_page.py las parte en la pregunta y sus
respuestas (la aceptada o la más votada primero) y los embeddings ordenan los
fragmentos al momento, con caché. Cada fragmento lleva en su origen el
enlace, el autor, los votos, la fecha, la licencia y si puede estar
desactualizado: es lo que se muestra sobre las líneas verificadas.
"""
import re
from datetime import date
from pathlib import Path

from core.rag.library import QA_SUFFIX
from core.rag.qa_page import page_chunks, parse_page, post_origin
from core.rag.tokens import tokenize
from core.rag.wikipedia import ARTICLE_FRAGMENTS, rank_fragments, searches_for, zim_pages
from core.rag.word_index import SPANISH

PAGES = 3
# "questions/103415/titulo", no "questions/tagged/lidar_page=6" ni "users/...".
QUESTION_PATHS = re.compile(r"questions/[0-9]+/")
NOT_IN_TAG = re.compile(r"[^\w-]+")


def metadata_text(archive, key: str) -> str:
    return bytes(archive.get_metadata(key)).decode("utf-8") if key in archive.metadata_keys else ""


def site_domain(archive) -> str:
    """"robotics.stackexchange.com", del metadato Name ("robotics.stackexchange.com_en_all")."""
    return metadata_text(archive, "Name").split("_")[0]


def edition_date(archive):
    """La fecha del metadato Date ("2026-10-20"), o None."""
    try:
        return date.fromisoformat(metadata_text(archive, "Date")[:10])
    except ValueError:
        return None


def zim_language(archive) -> str:
    """"es" si el .zim trae español ("eng,spa" en es.stackoverflow), si no "en"."""
    return "es" if "spa" in metadata_text(archive, "Language") else "en"


def closest_posts(chunks: list, question: str, language: str = SPANISH, count: int = ARTICLE_FRAGMENTS) -> list:
    """El principio de la mejor respuesta y los fragmentos de respuesta que más palabras comparten.

    page_chunks ya pone las respuestas en orden (aceptada, más votadas): la primera
    es la que se prioriza. El cuerpo de la pregunta queda fuera si hay respuestas:
    con él delante ("Tengo una gran duda..."), el 7B contestaba NINGUNA a "qué son
    los punteros en C". La pregunta sigue en la etiqueta (su título) y en el origen
    (su enlace). Sin respuestas, va la pregunta.
    """
    if not chunks:
        return []

    pool = [pair for pair in chunks if pair[0].kind == "respuesta"] or chunks
    fixed = pool[:1]
    wanted = set(tokenize(question, language))
    rest = [pair for pair in pool if pair not in fixed]
    rest.sort(key=lambda pair: -len(wanted.intersection(tokenize(pair[1].text, language))))
    return fixed + rest[:count - len(fixed)]


def qa_pages(archive, source, question: str, translated="", keywords=()) -> tuple:
    """(texto, idioma, páginas de pregunta) que /buscar lee del .zim de source (zim_pages)."""
    return zim_pages(archive, source, question, translated, keywords, PAGES, QUESTION_PATHS)


def qa_fragments(archive, source, pages: list, question: str, language: str = SPANISH) -> list:
    """[(id, documento, metadatos)] de los fragmentos elegidos de las páginas de pregunta."""
    edition = edition_date(archive)
    domain = site_domain(archive)
    fragments = []

    for _, _, html in pages:
        page = parse_page(html, edition)
        slug = f"{NOT_IN_TAG.sub('_', source.name)}_{page.question_id}{QA_SUFFIX}"

        for post, chunk in closest_posts(page_chunks(page), question, language):
            fragments.append((
                f"{slug}::{chunk.start_line}",
                chunk.text,
                {
                    "file_path": slug,
                    "relative_path": slug,
                    "source": source.name,
                    "kind": source.kind,
                    "origin": post_origin(page, post, domain, edition),
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "label": chunk.label,
                },
            ))

    return fragments


def qa_hits(question: str, source, n_results=5, embedder=None, translated="", keywords=()) -> list:
    """Los mejores fragmentos de las páginas de pregunta que encuentra question en el .zim de source."""
    from libzim.reader import Archive

    archive = Archive(str(Path(source.path)))
    text, language, pages = qa_pages(archive, source, question, translated, keywords)
    fragments = qa_fragments(archive, source, pages, text, language)
    return rank_fragments(fragments, searches_for(question, source, translated), n_results, embedder)
