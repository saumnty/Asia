"""Consistencia del prompt del IntentEngine (sin llamar al modelo)."""
import json
import re

from core.intent_engine import INTENT_PROMPT, IntentEngine

PROMPT = INTENT_PROMPT
LISTED = {
    line.strip().strip(",")
    for line in re.search(r"Acciones disponibles:\n(.*?)\n\nFormato", PROMPT, re.DOTALL).group(1).splitlines()
    if line.strip()
}
EXAMPLES = [
    json.loads(line)
    for line in PROMPT.splitlines()
    if line.startswith('{"action":"')
]


def test_cada_ejemplo_es_json_con_una_accion_de_la_lista():
    assert EXAMPLES
    assert {e["action"] for e in EXAMPLES} <= LISTED


def test_cada_accion_de_la_lista_tiene_un_ejemplo():
    assert LISTED - {e["action"] for e in EXAMPLES} == set()


def test_ejemplos_sin_frases_repetidas():
    users = [line for line in PROMPT.splitlines() if line.startswith("Usuario: ")]

    assert len(users) == len(set(users)) == len(EXAMPLES)
