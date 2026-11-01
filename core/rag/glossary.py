"""Glosario de una fuente: lo que el usuario llama de una forma y el código de otra.

data/biblioteca/glosario_<fuente>.json, un archivo opcional que mantiene el usuario
a mano: Asia lo lee y nunca lo escribe.

    {"punto desplazado": ["x_front", "y_front"]}

Si la pregunta dice "punto desplazado", se le añaden esos nombres antes de buscar.
"""
import json
import re

from core import paths
from core.rag.library import named_in_question
from core.rag.tokens import without_accents
from core.rag.vector_store import safe_collection_name


def glossary_path(name: str):
    return paths.GLOSSARY_DIR / f"glosario_{safe_collection_name(name)}.json"


def read_glossary(name: str):
    """{término: [equivalentes]}, {} si no hay archivo. ValueError si no se entiende."""
    path = glossary_path(name)

    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("el glosario debe ser un objeto JSON")

    return {term: [values] if isinstance(values, str) else list(values) for term, values in data.items()}


def normalized(text: str) -> str:
    return without_accents(text).lower()


def said_in(term: str, question: str) -> bool:
    return bool(re.search(rf"\b{re.escape(normalized(term))}\b", normalized(question)))


def expand(question: str, sources: list) -> str:
    """La pregunta con los equivalentes de sus términos, de la fuente nombrada o de todas."""
    named = named_in_question(question, sources)
    extra = []

    for source in [named] if named else sources:
        try:
            glossary = read_glossary(source.name)
        except (ValueError, TypeError):
            # /glosario dice qué le pasa al archivo; aquí solo no se usa.
            continue

        for term, values in glossary.items():
            if said_in(term, question):
                extra += [value for value in values if not said_in(value, question)]

    return f"{question} ({', '.join(dict.fromkeys(extra))})" if extra else question
