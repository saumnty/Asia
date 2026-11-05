"""remember, recall y forget sin dato: dicen qué falta, sin caer al chat ni llamar al modelo."""
import pytest

from core.actions.memory import MISSING_FORGET, MISSING_RECALL, MISSING_REMEMBER
from test_confidencial import make_brain


class Intent:
    def __init__(self, action, params):
        self.intent = {"action": action, "params": params}

    def detect(self, text, model=None):
        return self.intent


@pytest.mark.parametrize("action, expected", [
    ("remember", MISSING_REMEMBER), ("recall", MISSING_RECALL), ("forget", MISSING_FORGET),
])
def test_sin_key_dice_que_falta(action, expected):
    brain = make_brain()
    brain.intent_engine = Intent(action, {})

    assert brain.process("haz memoria de algo") == expected
    assert brain.provider_router.providers["ollama"].received == []


def test_recordar_sin_valor_pregunta_por_el():
    brain = make_brain()
    brain.intent_engine = Intent("remember", {"key": "mi color favorito"})

    answer = brain.process("recuerda mi color favorito")

    assert answer == "¿Qué quieres que recuerde sobre «mi color favorito»? Ej.: recuerda que mi color favorito es …"


def test_recordar_sin_valor_con_una_clave_suelta():
    brain = make_brain()
    brain.intent_engine = Intent("remember", {"key": "color"})

    assert brain.process("recuerda el color") == "¿Qué quieres que recuerde sobre «color»? Ej.: recuerda que mi color es …"


def test_los_ejemplos_son_frases_que_se_pueden_decir():
    assert "recuerda que mi color favorito es el azul" in MISSING_REMEMBER
    assert "olvida mi color favorito" in MISSING_FORGET
