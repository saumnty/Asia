"""Ruta rápida: charla clara directo al chat, sin el IntentEngine."""
import sys
from pathlib import Path

import pytest

from core.fast_chat import is_clear_chat

sys.path.insert(0, str(Path(__file__).parent / "manual"))
from check_intents import CHAT_CASES, EXPECTED, MESSAGES  # noqa: E402

APPS = ["chrome", "google", "navegador", "vscode", "bloc de notas", "notepad", "calculadora", "spotify", "whatsapp"]


@pytest.mark.parametrize("message, expected", list(zip(MESSAGES, EXPECTED)))
def test_los_28_casos_con_accion_siguen_en_el_intent_engine(message, expected):
    # Una acción nunca toma la ruta rápida; los de chat pueden tomarla o no.
    if expected != "chat":
        assert not is_clear_chat(message, APPS), message


@pytest.mark.parametrize("message", CHAT_CASES)
def test_charla_clara_va_directo(message):
    assert is_clear_chat(message, APPS)


@pytest.mark.parametrize(
    "message",
    [
        "qué es ProviderRouter",
        "qué es file_tool",
        "qué es brain.py",
        "qué es @a.py",
        "hola, abre spotify",
        "qué es spotify",
        "qué es el bloc de notas",
        "hola, revisa core",
        "gracias, ahora explica el archivo",
        "qué es mi color favorito",
        "no funciona el streaming",
        "si, aplica el cambio",
        "por qué falla el streaming",
        "qué proyecto está activo",
        "qué modelo estás usando",
        "quién soy",
        "cómo me llamo",
        "hola\nqué tal",
        "dime qué recuerdas de mí",
        "",
    ],
)
def test_ante_la_duda_intent_engine(message):
    assert not is_clear_chat(message, APPS)


def test_brain_no_llama_al_intent_engine_con_charla(monkeypatch):
    from core.brain import Brain

    brain = Brain.__new__(Brain)
    calls = []
    brain.intent_engine = type("I", (), {"detect": lambda self, t: calls.append(t) or {"action": "chat"}})()
    brain.settings = None
    monkeypatch.setattr(Brain, "app_names", lambda self: APPS)

    assert brain.process("hola") is None
    assert brain.process("qué es un grafo bipartito") is None
    assert calls == []

    brain.process("cuéntame un chiste")
    assert calls == ["cuéntame un chiste"]
