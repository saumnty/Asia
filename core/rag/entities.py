"""La regla de la entidad: si la pregunta nombra un nombre propio, la cita tiene que nombrarlo.

El 7B cambiaba el sujeto: "el puente de Valdecierzo se inauguró en 1929" con una línea
del Puente de Hierro de Soria, "la capital de Australia es Camberra" con un JSON de
ejemplo de un hilo de Javascript. Una cita de fuera (Wikipedia, Stack Exchange) solo
vale si su línea o el título de su artículo o hilo dice el nombre.
"""
import re
import unicodedata

from core.rag.library import QA_SUFFIX, WIKI_SUFFIX

# Una palabra con mayúscula inicial y alguna minúscula: las siglas (PID, LED, DNS) no son nombres.
NAME_WORD = re.compile(r"[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+(?:-[\wáéíóúñü]+)?")
WORD = re.compile(r"[\wáéíóúñüÁÉÍÓÚÑÜ¿¡-]+")
# Dentro de un nombre: "Brezalmonte de Arriba", "Don Quijote de la Mancha".
CONNECTORS = {"de", "del", "la", "las", "los", "el", "y"}


def plain(text: str) -> str:
    """En minúsculas, sin tildes y con espacios en vez de guiones bajos (las rutas de los artículos)."""
    text = unicodedata.normalize("NFKD", text.replace("_", " ").casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def question_entities(question: str, skip=()) -> list:
    """Los nombres propios de question, sin la primera palabra (puede ir en mayúscula) ni los de skip."""
    words = [w.strip("¿¡") for w in WORD.findall(question)]
    skipped = {plain(name) for name in skip}
    entities, run, pending = [], [], []

    def close():
        if run:
            entities.append(" ".join(run))

    for position, word in enumerate(words):
        if position and NAME_WORD.fullmatch(word) and plain(word) not in skipped:
            run.extend(pending + [word])
            pending = []
        elif run and word.lower() in CONNECTORS:
            pending.append(word)
        else:
            close()
            run, pending = [], []

    close()
    return list(dict.fromkeys(entities))


def names(entity: str) -> list:
    return [plain(word) for word in entity.split() if word.lower() not in CONNECTORS]


def mentions(entity: str, text: str) -> bool:
    """True si text dice cada palabra del nombre ("Australia" vale dentro de "Australiana")."""
    found = plain(text)
    return all(name in found for name in names(entity))


def outside(quote) -> bool:
    return WIKI_SUFFIX in quote.path or QA_SUFFIX in quote.path


def about_entities(quotes: list, question: str, skip=()) -> tuple:
    """(las citas que valen, los nombres que ninguna cita de fuera dice).

    Las de los proyectos no se miran: allí los nombres son de código. Si ninguna
    cita de fuera queda, los nombres van en "No encontré información sobre …".
    """
    entities = question_entities(question, skip)

    def says(quote, entity):
        return mentions(entity, f"{quote.text} {quote.label} {quote.path}")

    kept = [quote for quote in quotes if not outside(quote) or all(says(quote, e) for e in entities)]

    if kept or not quotes:
        return kept, []

    return kept, [e for e in entities if not any(says(q, e) for q in quotes)] or entities
