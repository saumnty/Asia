"""Palabras clave para buscar en un .zim (Wikipedia, Stack Exchange) con una pregunta natural.

La búsqueda de texto del .zim exige todas las palabras: "qué moneda se usa en
Japón" no traía Yen ni "en qué año llegó el hombre a la Luna" Apolo 11. Antes de
buscar, qwen3 (dominio general) convierte la pregunta en 2 a 4 búsquedas cortas
o posibles títulos; core/rag/wikipedia.found_articles las busca por título
(SuggestionSearcher) y por texto completo, con la pregunta original de respaldo.
"""
import re

SETTING = "zim_keywords"
# Quién las saca: "general" es qwen3; "code", el 7B que luego contesta /buscar (sin recargar).
DOMAIN_SETTING = "zim_keywords_domain"
DEFAULT_DOMAIN = "general"
MAX_KEYWORDS = 4
MAX_CHARS = 60
KEYWORD_TOKENS = 60
LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def keywords_prompt(question: str, language: str, site: str) -> str:
    idiom = "en inglés" if language == "en" else "en español"
    return f"""
Convierte la pregunta en 2 a 4 búsquedas cortas para el buscador de {site}: palabras clave o el título
probable de un artículo o de una pregunta, {idiom}. Una por línea, sin numerar ni explicar.

Pregunta:
{question}
"""


def parse_keywords(answer: str) -> list:
    """Las búsquedas de la respuesta del modelo, sin viñetas ni comillas, como mucho MAX_KEYWORDS."""
    found = []

    for line in (answer or "").splitlines():
        text = LIST_MARKER.sub("", line).strip().strip("\"'«»`").strip()

        if text and len(text) <= MAX_CHARS and text.lower() not in (k.lower() for k in found):
            found.append(text)

    return found[:MAX_KEYWORDS]


def enabled_for(setting, source) -> bool:
    """rag.zim_keywords: true para todos los .zim, o la lista de tipos ("enciclopedia").

    Medido en 2026-11: con Wikipedia el artículo aparece en 10/12 en vez de 6/12, pero
    en robotics baja de 4/6 a 2/6 (los títulos son preguntas enteras).
    """
    return setting is True or (isinstance(setting, list) and source.kind in setting)


def zim_keywords(question: str, source, ask, domain=DEFAULT_DOMAIN) -> list:
    """ask(prompt, domain=, max_tokens=): ProviderRouter.ask. [] si el modelo no da nada útil."""
    from core.rag.library import ENCYCLOPEDIA

    site = "Wikipedia" if source.kind == ENCYCLOPEDIA else "Stack Exchange"
    answer = ask(keywords_prompt(question, source.language, site), domain=domain, max_tokens=KEYWORD_TOKENS)
    return parse_keywords(answer)
