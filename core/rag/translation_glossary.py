"""Glosario de traducción técnica para las fuentes en inglés (config/glosario_traduccion.json).

El 7B traducía "cómo cambio el nombre del equipo" como "How do I change the team
name?" y la búsqueda traía un hilo de Microsoft Teams. Antes de traducir, los
términos de informática de la pregunta van al prompt con su traducción ("nombre
del equipo" = hostname / computer name). El término más largo gana.
"""
import json
import re
import unicodedata

from core.paths import CONFIG_DIR

GLOSSARY_FILE = CONFIG_DIR / "glosario_traduccion.json"


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def load_glossary(path=None) -> dict:
    """{término: [traducciones]}; las claves que empiezan con "_" son notas."""
    path = path or GLOSSARY_FILE

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    return {term: list(values) for term, values in data.items() if not term.startswith("_") and values}


def terms_in(question: str, glossary: dict) -> list:
    """[(término, traducciones)] de question, sin tildes ni mayúsculas; uno largo tapa a los que contiene."""
    text = plain(question)
    taken = []
    found = []

    for term in sorted(glossary, key=len, reverse=True):
        for match in re.finditer(rf"(?<!\w){re.escape(plain(term))}(?!\w)", text):
            span = range(match.start(), match.end())

            if not any(set(span) & set(other) for other in taken):
                taken.append(span)
                found.append((term, glossary[term]))
                break

    return sorted(found, key=lambda pair: text.find(plain(pair[0])))
