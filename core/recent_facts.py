"""Preguntas por hechos concretos que el modelo no puede saber: no se contestan de memoria.

qwen3 contestó "¿quién ganó el mundial de 2026?" con "Estados Unidos ante
México". Un año posterior a lo que sabe el modelo (knowledge_until_year), o
"actual", "último", "hoy" con un resultado, un campeón, unas elecciones o una
noticia: Asia dice que no lo sabe y ofrece buscarlo en la Wikipedia offline.
Con "sí", lo busca.
"""
import re

from core.actions.models import command_text
from core.fast_chat import CODE_LIKE

# El mismo que knowledge_until_year en config/defaults.json, por si falta la clave.
DEFAULT_KNOWN_UNTIL = 2024

QUESTION = re.compile(
    r"^(y\s+)?(quien|quienes|cual|cuales|cuando|donde|cuanto|cuantos|cuantas|que paso|que ocurrio|que sucedio"
    r"|como quedo|como termino|como acabo|gano|hubo|sabes quien|sabes que|sabes cual)\b"
)
YEAR = re.compile(r"\b(20\d\d)\b")
EVENT = re.compile(
    r"\b(gan\w*|campeon\w*|elecci\w*|elegid\w*|presiden\w*|mundial\w*|olimpi\w*|premio\w*|oscar\w*|nobel"
    r"|final|resultado\w*|noticia\w*|muri\w*|fallec\w*|lanz\w*|estren\w*|guerra|copa|liga|torneo|record)\b"
)
NOW = re.compile(r"\b(actual|actualmente|ahora|hoy|ultim[oa]s?|reciente\w*|este ano|esta semana|este mes)\b")

AFFIRMATIVE = {"si", "si por favor", "si busca", "si buscalo", "buscalo", "dale", "ok", "vale", "claro", "por favor"}
EDITION = re.compile(r"_(\d{4}-\d{2})\.zim$")


def asks_recent_fact(text: str, known_until: int = DEFAULT_KNOWN_UNTIL) -> bool:
    command = command_text(text or "")

    if not QUESTION.match(command) or CODE_LIKE.search(text):
        return False

    if any(int(year) > known_until for year in YEAR.findall(command)):
        return bool(EVENT.search(command)) or not command.startswith(("cuanto", "cuantos", "cuantas"))

    return bool(NOW.search(command) and EVENT.search(command))


def is_affirmative(text: str) -> bool:
    return " ".join(re.findall(r"\w+", command_text(text or ""))) in AFFIRMATIVE


def offer_text(source) -> str:
    """La negativa con la oferta; sin la fuente wikipedia, solo la negativa."""
    refusal = (
        "No lo sé de memoria: es un hecho concreto que puede ser posterior a lo que aprendí, "
        "y no quiero inventarlo."
    )

    if source is None:
        return f"{refusal} Tampoco tengo una copia de Wikipedia para buscarlo."

    edition = EDITION.search(source.path or "")
    copy = f" (copia offline de {edition.group(1)})" if edition else " (copia offline)"
    return f"{refusal} ¿Lo busco en Wikipedia{copy}? Responde «sí» para buscarlo."
