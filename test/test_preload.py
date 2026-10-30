"""Precarga del modelo del IntentEngine al abrir el modo interactivo."""
import threading

import launcher
from config.settings_manager import SettingsManager
from core.brain import Brain
from core.intent_engine import IntentEngine

# Antes de que el fixture de conftest la desactive.
REAL_PRELOAD = Brain.preload_in_background


class Client:
    def __init__(self, error=None):
        self.error = error
        self.generated = []
        self.started = threading.Event()
        self.release = threading.Event()

    def ps(self):
        raise ConnectionError

    def generate(self, **kwargs):
        self.started.set()
        self.release.wait(5)

        if self.error:
            raise self.error

        self.generated.append(kwargs)


def engine(client):
    e = IntentEngine.__new__(IntentEngine)
    e.settings = SettingsManager()
    e.client = client
    return e


def test_precarga_sin_prompt_ni_keep_alive_con_el_mismo_num_ctx():
    client = Client()
    client.release.set()

    engine(client).preload()

    settings = SettingsManager()
    assert client.generated == [{"model": settings.get("intent_model"), "options": {"num_ctx": settings.get("ollama_num_ctx")}}]


def test_ollama_apagado_no_muestra_nada(capsys):
    client = Client(error=ConnectionError("Failed to connect to Ollama"))
    client.release.set()

    engine(client).preload()

    assert capsys.readouterr() == ("", "")


def test_otro_error_se_avisa(capsys):
    client = Client(error=RuntimeError("model 'x' not found"))
    client.release.set()

    engine(client).preload()

    assert "No pude precargar" in capsys.readouterr().err


def test_no_bloquea_la_entrada(monkeypatch):
    client = Client()
    brain = Brain.__new__(Brain)
    brain.intent_engine = engine(client)
    brain.settings = SettingsManager()
    brain.provider_router = None
    monkeypatch.setattr(Brain, "preload_in_background", REAL_PRELOAD)
    prompts = []

    def read(prompt):
        # La precarga sigue esperando y ya se lee el primer mensaje.
        assert client.started.wait(5)
        prompts.append(prompt)
        return "salir"

    launcher.interactive_mode(brain, read=read)

    assert prompts == ["\nTú: "] and client.generated == []
    client.release.set()


def test_sin_preload_no_falla():
    brain = Brain.__new__(Brain)
    brain.intent_engine = object()

    assert REAL_PRELOAD(brain) is None
