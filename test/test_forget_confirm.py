"""forget: "¿Borro «X»? s/N" y el dato solo se borra con un sí (memoria en una carpeta temporal)."""
import json

import pytest

from core.voice.speakable import to_speakable
from memory.memory_manager import MemoryManager
from test_confidencial import make_brain


class ForgetThenChat:
    """El IntentEngine de mentira: "olvida X" -> forget; lo demás, conversación."""

    def detect(self, text, model=None):
        if text.startswith("olvida "):
            return {"action": "forget", "params": {"key": text.split(" ", 1)[1]}}

        return {"action": "chat", "params": {}}


@pytest.fixture
def brain(tmp_path):
    brain = make_brain()
    brain.intent_engine = ForgetThenChat()
    brain.memory = MemoryManager(tmp_path / "memoria.json")
    brain.memory.remember("color", "azul")
    brain.memory.remember("perro", "Toby")
    return brain


def stored(brain):
    return json.loads(brain.memory.memory_file.read_text(encoding="utf-8"))


def test_pregunta_antes_de_borrar_y_muestra_que_se_borra(brain):
    answer = brain.process("olvida color")

    assert answer.startswith("¿Borro «color»? s/N")
    assert "[Se borraría: color = azul]" in answer
    assert stored(brain) == {"color": "azul", "perro": "Toby"}


@pytest.mark.parametrize("yes", ["s", "sí", "Sí.", "dale", "ok", "claro", "bórralo", "sí, bórralo"])
def test_con_un_si_borra(brain, yes):
    brain.process("olvida color")

    assert brain.process(yes) == "Listo. Olvidé el dato: color."
    assert stored(brain) == {"perro": "Toby"}
    assert brain.last_action == "forget"


@pytest.mark.parametrize("no", ["n", "no", "No.", "no gracias", "cancela", "déjalo"])
def test_con_un_no_lo_conserva(brain, no):
    brain.process("olvida color")

    assert brain.process(no) == "Vale, no borro «color»."
    assert stored(brain) == {"color": "azul", "perro": "Toby"}


def test_sin_respuesta_lo_conserva_y_la_pregunta_se_olvida(brain):
    brain.process("olvida color")

    # Otra cosa en vez de un sí o un no: se atiende normal y el dato se queda.
    assert brain.process("cuéntame un chiste") != "Listo. Olvidé el dato: color."
    assert stored(brain)["color"] == "azul"

    # Un "sí" más tarde ya no borra nada: la pregunta valía solo para el mensaje siguiente.
    brain.process("sí")
    assert stored(brain) == {"color": "azul", "perro": "Toby"}


def test_un_si_suelto_sin_pregunta_no_borra(brain):
    brain.process("sí")

    assert stored(brain) == {"color": "azul", "perro": "Toby"}


def test_un_dato_que_no_existe_no_pregunta(brain):
    assert brain.process("olvida gato") == "No tenía guardado ningún dato para: gato."
    assert brain.pending_forget is None


def test_la_voz_dice_la_pregunta_y_no_lee_el_valor(brain):
    answer = brain.process("olvida color")

    assert "azul" in answer
    assert "azul" not in to_speakable(answer)
    assert "Borro" in to_speakable(answer)


def test_un_valor_largo_se_recorta_en_pantalla(brain):
    brain.memory.remember("nota", "x" * 500)

    answer = brain.process("olvida nota")

    assert "x" * 200 + "…" in answer and "x" * 201 not in answer


def test_cada_pregunta_es_la_ultima(brain):
    brain.process("olvida color")
    brain.process("olvida perro")

    assert brain.process("sí") == "Listo. Olvidé el dato: perro."
    assert stored(brain) == {"color": "azul"}
