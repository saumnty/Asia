"""explain_file y summarize_file: plantilla de documento y tope de la respuesta."""
from types import SimpleNamespace

import pytest

from config.settings_manager import SettingsManager
from core.actions.explore import ExploreActions
from core.confidential import OutgoingRequest
from providers.ollama_provider import OllamaProvider


class Router:
    def __init__(self):
        self.calls = []

    def ask(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return "respuesta"


class Actions(ExploreActions):
    def __init__(self, content="# Título\n\nTexto."):
        self.settings = SettingsManager()
        self.provider_router = Router()
        self.tool_registry = SimpleNamespace(execute=lambda *a, **k: content)

    def limit(self, name):
        return 1000


@pytest.mark.parametrize("action", ["explain_file", "summarize_file"])
@pytest.mark.parametrize("path", ["ROADMAP.md", "notas.txt", "config/defaults.json", "datos.YAML"])
def test_documentos_sin_clases_ni_metodos(action, path):
    actions = Actions()

    getattr(actions, f"handle_{action}")("", {"file_path": path})

    [(prompt, kwargs)] = actions.provider_router.calls
    assert "no es código" in prompt and "No hables de clases, métodos ni funciones" in prompt
    assert "Clases principales" not in prompt and "Métodos importantes" not in prompt
    limits = SettingsManager().get("answer_limits")[action]
    assert f"{limits['words']} palabras como máximo" in prompt
    assert kwargs == {"max_tokens": limits["tokens"]}


@pytest.mark.parametrize("path", ["tools/file_tool.py", "Main.java"])
def test_codigo_conserva_su_plantilla_con_tope(path):
    actions = Actions()

    actions.handle_explain_file("", {"file_path": path})

    [(prompt, kwargs)] = actions.provider_router.calls
    assert "Clases principales" in prompt
    assert kwargs == {"max_tokens": SettingsManager().get("answer_limits")["explain_file"]["tokens"]}


def test_los_topes_estan_en_defaults():
    limits = SettingsManager().get("answer_limits")

    assert set(limits) == {"explain_file", "summarize_file", "chat"}
    assert all(limits[a]["tokens"] > 0 and limits[a]["words"] > 0 for a in ("explain_file", "summarize_file"))


def test_el_tope_llega_a_ollama_como_num_predict():
    sent = {}

    class Client:
        def ps(self):
            raise ConnectionError

        def show(self, model):
            raise ConnectionError

        def chat(self, **kwargs):
            sent.update(kwargs)
            return {"message": {"content": "ok"}}

    provider = OllamaProvider.__new__(OllamaProvider)
    provider.settings = SettingsManager()
    provider.client = Client()

    provider.complete([{"role": "user", "content": "x"}], max_tokens=123)
    assert sent["options"]["num_predict"] == 123
    assert sent["options"]["num_ctx"] == SettingsManager().get("ollama_num_ctx")

    provider.complete([{"role": "user", "content": "x"}])
    assert "num_predict" not in sent["options"]


def test_el_router_pasa_el_tope_al_proveedor():
    from test_confidencial import make_brain

    brain = make_brain()
    received = {}
    ollama = brain.provider_router.providers["ollama"]
    original = ollama.complete

    def complete(messages, **kwargs):
        received.update(kwargs)
        return original(messages, **{k: v for k, v in kwargs.items() if k != "max_tokens"})

    ollama.complete = complete

    brain.provider_router.ask("hola", max_tokens=50)
    assert received["max_tokens"] == 50

    received.clear()
    brain.provider_router.ask("hola")
    assert "max_tokens" not in received


def test_limits_sin_tope():
    assert OutgoingRequest([], []).limits() == {}
    assert OutgoingRequest([], [], max_tokens=10).limits() == {"max_tokens": 10}


@pytest.mark.parametrize("stream", [False, True])
def test_aviso_si_ollama_corta_por_el_tope(stream):
    class Client:
        def ps(self):
            raise ConnectionError

        def show(self, model):
            raise ConnectionError

        def chat(self, stream=False, **kwargs):
            final = {"message": {"content": "texto"}, "done": True, "done_reason": "length"}
            return iter([final]) if stream else final

    provider = OllamaProvider.__new__(OllamaProvider)
    provider.settings = SettingsManager()
    provider.client = Client()
    chunks = []

    answer = provider.complete([{"role": "user", "content": "x"}], max_tokens=450,
                               on_chunk=chunks.append if stream else None)

    assert answer == "texto\n\n[Respuesta recortada en 450 tokens (answer_limits en config).]"
    assert not stream or "".join(chunks) == answer

    # Sin tope no hay aviso aunque Ollama diga "length" (num_ctx).
    assert provider.complete([{"role": "user", "content": "x"}]) == "texto"
