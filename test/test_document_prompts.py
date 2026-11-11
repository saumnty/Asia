"""explain_file y summarize_file: plantilla de documento y tope de la respuesta."""
from types import SimpleNamespace

import pytest

from config.settings_manager import SettingsManager
from core.actions.explore import ExploreActions
from core.actions.voice import VOICE_SETTING
from core.confidential import OutgoingRequest
from core.voice.speakable import to_speakable
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

    assert set(limits) == {"explain_file", "summarize_file", "chat", "session_summary", "search_quotes", "search_answer"}
    assert all(limits[a]["tokens"] > 0 for a in ("search_quotes", "search_answer"))
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


# --- Con la voz activa -------------------------------------------------------------

@pytest.fixture
def voice_on():
    # conftest vacía los overrides en cada prueba.
    SettingsManager.set_overrides({VOICE_SETTING: True})


@pytest.mark.parametrize("action, more", [
    ("explain_file", "Para la explicación completa: explica core/brain.py a fondo."),
    ("summarize_file", "Para el resumen completo: resume core/brain.py a fondo."),
])
def test_con_voz_una_respuesta_corta_y_la_larga_en_pantalla(voice_on, action, more):
    actions = Actions("def f():\n    return 1\n")

    answer = getattr(actions, f"handle_{action}")("explica core/brain.py", {"file_path": "core/brain.py"})

    [(prompt, kwargs)] = actions.provider_router.calls
    assert "1 a 3 frases, en un solo párrafo, sin listas" in prompt and "Clases principales" not in prompt
    # Al modelo ya cargado (qwen3, "general"): cabe en su contexto (brief_domain).
    assert kwargs == {"max_tokens": SettingsManager().get("answer_limits")[action]["voice_tokens"], "domain": "general"}
    assert kwargs["max_tokens"] == 150
    assert answer == f"respuesta\n\n[{more}]"
    # La línea de cómo pedir la larga solo se ve: no se lee.
    assert to_speakable(answer) == "respuesta."


@pytest.mark.parametrize("action", ["explain_file", "summarize_file"])
def test_con_voz_a_fondo_vale_la_plantilla_larga(voice_on, action):
    actions = Actions("def f():\n    return 1\n")

    answer = getattr(actions, f"handle_{action}")("explica core/brain.py a fondo", {"file_path": "core/brain.py"})

    [(prompt, kwargs)] = actions.provider_router.calls
    assert "1 a 3 frases" not in prompt and answer == "respuesta"
    assert kwargs == {"max_tokens": SettingsManager().get("answer_limits")[action]["tokens"]}


@pytest.mark.parametrize("action", ["explain_file", "summarize_file"])
def test_sin_voz_nada_cambia(action):
    actions = Actions("def f():\n    return 1\n")

    answer = getattr(actions, f"handle_{action}")("explica core/brain.py", {"file_path": "core/brain.py"})

    [(prompt, kwargs)] = actions.provider_router.calls
    assert "1 a 3 frases" not in prompt and answer == "respuesta"


@pytest.mark.parametrize("action", ["explain_file", "summarize_file"])
def test_con_voz_si_no_cabe_en_el_contexto_de_qwen3_va_al_7b(voice_on, action):
    # 2400 caracteres caben en los 4096 de qwen3; 13 200 (~4800 tokens con el margen) no.
    small = Actions("x = 1\n" * 400)
    big = Actions("x = 1\n" * 2200)

    getattr(small, f"handle_{action}")("explica core/brain.py", {"file_path": "core/brain.py"})
    getattr(big, f"handle_{action}")("explica core/brain.py", {"file_path": "core/brain.py"})

    assert small.provider_router.calls[0][1]["domain"] == "general"
    assert big.provider_router.calls[0][1]["domain"] == "code"


def test_brief_domain_lee_el_contexto_del_modelo_y_la_configuracion(voice_on):
    actions = Actions()
    prompt = "a" * 9000  # ~2727 tokens estimados, ~3270 con el margen

    assert actions.brief_domain(prompt, 150) == "general"
    assert actions.brief_domain(prompt, 900) == "code"  # 3270 + 900 > 4096

    SettingsManager.set_overrides({VOICE_SETTING: True, "voice_brief_domain": "code"})
    assert actions.brief_domain("corto", 150) == "code"


class FolderActions(Actions):
    def __init__(self):
        super().__init__()
        self.read = []
        self.tool_registry = SimpleNamespace(execute=lambda *a, **k: self.read.append(k) or "archivo.py: x = 1")

    def limit(self, name):
        return {"max_files": 12, "max_chars_per_file": 1200}


def test_carpeta_con_voz_breve_con_menos_de_cada_archivo(voice_on):
    actions = FolderActions()

    answer = actions.handle_summarize_folder("resume la carpeta docs", {"folder_path": "docs"})

    [(prompt, kwargs)] = actions.provider_router.calls
    assert actions.read[0]["max_chars_per_file"] == SettingsManager().get("context_limits")["summarize_folder_voice"]["max_chars_per_file"] == 250
    assert "1 a 3 frases" in prompt and "Ruta de la carpeta:\ndocs" in prompt
    assert kwargs == {"max_tokens": 150, "domain": "general"}
    assert answer == "respuesta\n\n[Para el resumen completo: resume la carpeta docs a fondo.]"


@pytest.mark.parametrize("text", ["resume la carpeta docs", "resume la carpeta docs a fondo"])
def test_carpeta_sin_voz_o_a_fondo_como_siempre(text):
    if "a fondo" in text:
        SettingsManager.set_overrides({VOICE_SETTING: True})
    actions = FolderActions()

    answer = actions.handle_summarize_folder(text, {"folder_path": "docs"})

    [(prompt, kwargs)] = actions.provider_router.calls
    assert actions.read[0]["max_chars_per_file"] == 1200 and "1 a 3 frases" not in prompt
    assert kwargs == {} and answer == "respuesta"


def test_voice_brief_de_archivo_sigue_igual():
    from core import prompts

    assert "Ruta del archivo:\nx.py" in prompts.voice_brief("Resume este archivo", "x.py", "")
