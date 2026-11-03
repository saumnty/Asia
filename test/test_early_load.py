"""Precarga anticipada del modelo de código mientras se escribe (core/early_load.py)."""
import sys
import threading
import types

import pytest

import launcher
from config.settings_manager import SettingsManager
from core.early_load import SETTING, EarlyLoad, goes_to_code_model
from test_confidencial import make_brain

SMALL, BIG = "qwen3:4b-instruct-2507-q4_K_M", "qwen2.5-coder:7b"


@pytest.mark.parametrize(
    "text",
    ["explica @core/brain.py", "@ROADMAP.md resume esto", "/buscar cómo se guardan los pendientes",
     "revisa el proyecto", "explica core/fast_chat.py", "genera una función que sume", "corrige el bug de Asia"],
)
def test_va_al_modelo_de_codigo(text):
    assert goes_to_code_model(text)


@pytest.mark.parametrize(
    "text",
    ["hola", "explica qué es una closure", "qué es un grafo bipartito", "cuéntame un chiste",
     "mi correo es a@b.com", "busca recetas"],
)
def test_no_va_al_modelo_de_codigo(text):
    assert not goes_to_code_model(text)


class Loads:
    def __init__(self):
        self.models = []
        self.done = threading.Event()

    def __call__(self, model):
        self.models.append(model)
        self.done.set()


def early(**overrides):
    SettingsManager.set_overrides({"intent_model": SMALL, "models_by_domain": {"code": BIG, "general": SMALL}, **overrides})
    loads = Loads()
    return EarlyLoad(SettingsManager(), loads), loads


def test_empieza_a_cargar_una_sola_vez_por_mensaje():
    loader, loads = early()

    for partial in ("expl", "explica @c", "explica @core/brain.py"):
        loader.typing(partial)

    loads.done.wait(2)
    assert loads.models == [BIG]
    assert loader.take() == BIG
    # Mensaje siguiente: vuelve a empezar.
    assert loader.take() is None
    loader.typing("/buscar algo")
    loader.thread.join(2)
    assert loads.models == [BIG, BIG]


def test_la_charla_no_carga_nada():
    loader, loads = early()

    loader.typing("hola, qué tal")

    assert loads.models == [] and loader.take() is None


def test_desactivada_o_con_el_mismo_modelo_no_carga():
    loader, loads = early(**{SETTING: False})
    loader.typing("explica @core/brain.py")
    assert loads.models == [] and loader.take() is None

    loader, loads = early(intent_model=BIG)
    loader.typing("explica @core/brain.py")
    assert loads.models == [] and loader.take() is None


class Intent:
    def __init__(self):
        self.models = []

    def detect(self, text, model=None):
        self.models.append(model)
        return {"action": "chat", "params": {}}


def test_la_intencion_va_con_el_modelo_precargado():
    brain = make_brain()
    brain.intent_engine = Intent()
    brain.early_load, loads = early()

    brain.early_load.typing("resume el archivo core/brain.py")
    brain.early_load.thread.join(2)
    brain.process("resume el archivo core/brain.py")
    brain.process("cuál es la diferencia entre una lista y una tupla en mi proyecto")

    # El primero con el 7B precargado; el siguiente, sin precarga, con intent_model.
    assert brain.intent_engine.models == [BIG, None]


def test_el_launcher_le_pasa_lo_que_se_escribe(monkeypatch):
    seen = []

    class Buffer:
        def __init__(self):
            self.text = ""
            self.on_text_changed = Event()

    class Event(list):
        def __iadd__(self, handler):
            self.append(handler)
            return self

    class PromptSession:
        def __init__(self, **kwargs):
            self.default_buffer = Buffer()

        def prompt(self, text):
            for partial in ("explica", "explica @a.py"):
                self.default_buffer.text = partial
                for handler in self.default_buffer.on_text_changed:
                    handler(self.default_buffer)
            return self.default_buffer.text

    monkeypatch.setitem(sys.modules, "prompt_toolkit", types.SimpleNamespace(PromptSession=PromptSession))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(launcher, "make_completer", lambda cwd: None)

    read = launcher.make_reader(seen.append)

    assert read("Tú: ") == "explica @a.py"
    assert seen == ["explica", "explica @a.py"]
