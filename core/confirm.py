"""Respuesta a una pregunta "s/N" de Asia: sí, no u otra cosa (la pregunta se olvida)."""
import re

from core.actions.models import command_text
from core.recent_facts import is_affirmative

# Las mismas que usa "¿Abro X? s/N" (core/brain.py: DONT_OPEN).
NO = {"n", "no", "no gracias", "nada", "cancela", "cancelar", "dejalo"}


def confirmation(text, yes=()):
    """True con un sí (escrito o dicho; yes: frases propias de la pregunta), False con un no,
    None si el mensaje es otra cosa."""
    words = " ".join(re.findall(r"\w+", command_text(text or "")))

    if is_affirmative(text) or words in yes:
        return True

    return False if words in NO else None
