"""/revisar memoria (fase R): entradas duplicadas o contradictorias en memory.json.

Primero reglas, que no inventan: claves casi iguales y valores iguales. Después
el modelo local, para lo que las reglas no ven ("ciudad" y "vivo_en"); de su
respuesta solo vale lo que nombra claves que existen. Aquí nada se cambia: el
launcher propone cada caso y solo borra lo que el usuario confirma.
"""
import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from core import prompts
from core.reflection import within_timeout

DUPLICATE, CONTRADICTION = "duplicada", "contradictoria"
SIMILAR_KEYS = 0.85
# Prefijos y palabras que no cambian de qué trata una clave.
KEY_NOISE = re.compile(r"\b(mi|mis|el|la|los|las|de|del|tu)\b")
JSON_LIST = re.compile(r"\[.*\]", re.DOTALL)
MIN_VALUE_CHARS = 3


@dataclass(frozen=True)
class Proposal:
    first: str
    second: str
    kind: str


def plain(value) -> str:
    text = unicodedata.normalize("NFD", str(value).lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def key_words(key) -> str:
    return " ".join(KEY_NOISE.sub(" ", plain(key)).split())


def same_topic(first, second) -> bool:
    a, b = key_words(first), key_words(second)

    if a == b:
        return True

    return SequenceMatcher(None, a, b).ratio() >= SIMILAR_KEYS


def same_value(first, second) -> bool:
    """Iguales, o uno dentro del otro ("UAM" y "Universidad Autónoma Metropolitana (UAM)")."""
    a, b = plain(first), plain(second)

    if a == b:
        return True

    return min(len(a), len(b)) >= MIN_VALUE_CHARS and (
        f" {a} " in f" {b} " or f" {b} " in f" {a} "
    )


def rule_proposals(memory: dict) -> list:
    keys = list(memory)
    found = []

    for i, first in enumerate(keys):
        for second in keys[i + 1:]:
            equal = same_value(memory[first], memory[second])

            if same_topic(first, second):
                found.append(Proposal(first, second, DUPLICATE if equal else CONTRADICTION))
            elif equal and len(plain(memory[first])) >= MIN_VALUE_CHARS:
                found.append(Proposal(first, second, DUPLICATE))

    return found


def parse_model_answer(text: str, memory: dict) -> list:
    """Los pares que dio el modelo, solo con claves que existen. Una respuesta rara no da ninguno."""
    match = JSON_LIST.search(text or "")

    try:
        items = json.loads(match.group()) if match else []
    except ValueError:
        return []

    found = []

    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue

        first, second, kind = item.get("a"), item.get("b"), item.get("tipo")
        valid = first in memory and second in memory and first != second

        if valid and kind in (DUPLICATE, CONTRADICTION):
            found.append(Proposal(first, second, kind))

    return found


def find_proposals(memory: dict, complete=None, timeout=60):
    """(propuestas, si el modelo participó). complete(messages) es el modelo local."""
    found = rule_proposals(memory)

    if complete is None or len(memory) < 2:
        return found, False

    messages = [{"role": "user", "content": prompts.memory_review(json.dumps(memory, ensure_ascii=False, indent=2))}]
    answer = within_timeout(lambda: complete(messages), timeout)

    if answer is None:
        return found, False

    known = {frozenset((p.first, p.second)) for p in found}

    for proposal in parse_model_answer(answer, memory):
        pair = frozenset((proposal.first, proposal.second))

        if pair not in known:
            known.add(pair)
            found.append(proposal)

    return found, True
