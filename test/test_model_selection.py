from types import SimpleNamespace

import pytest

import launcher
from config.settings_manager import SettingsManager, read_json
from core.intent_engine import IntentEngine
from core.model_selection import StickyModel, classify_domain, model_for
from core.paths import DEFAULTS_FILE
from providers.ollama_models import unload_others
from providers.ollama_provider import OllamaProvider
from providers.provider_router import ProviderRouter


class Settings:
    def __init__(self, **values):
        self.values = {
            "ollama_model": "base",
            "models_by_domain": {"code": "coder", "math": "razonador", "general": "general"},
            "ollama_one_model_at_a_time": True,
            "ollama_num_ctx": 16384,
            **values,
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


# --- Dominio y modelo ---------------------------------------------------------

@pytest.mark.parametrize(
    "text, domain",
    [
        ("explica este código", "code"),
        ("def f(x):\n    return x", "code"),
        ("por qué falla moda.py", "code"),
        ("calcula la media en python", "code"),
        ("resuelve la ecuación 2x + 3 = 7", "math"),
        ("cuánto es 15 * 12", "math"),
        ("explícame la segunda ley de Newton en física", "math"),
        ("hola, ¿cómo estás?", "general"),
        ("translate this sentence to English", "general"),
    ],
)
def test_classify_domain(text, domain):
    assert classify_domain(text) == domain


def test_model_for():
    assert model_for(Settings(), "math") == "razonador"
    assert model_for(Settings(models_by_domain={}), "math") == "base"
    assert model_for(Settings(forced_model="fijo"), "math") == "fijo"


def test_defaults_sin_cambio_de_comportamiento():
    # Hasta descargar otros modelos, todos los dominios usan el mismo.
    defaults = read_json(DEFAULTS_FILE)

    assert set(defaults["models_by_domain"].values()) == {defaults["ollama_model"]}
    assert defaults["ollama_one_model_at_a_time"] is True


# --- Modelo pegajoso -----------------------------------------------------------

def test_el_chat_mantiene_el_modelo_ante_un_mensaje_suelto():
    sticky, settings = StickyModel(), Settings()

    assert sticky.choose("hola", settings) == "general"
    assert sticky.choose("cuánto es 2 + 2", settings) == "general"  # uno suelto no cambia
    assert sticky.choose("¿y qué tal el clima?", settings) == "general"
    assert sticky.choose("cuánto es 2 + 2", settings) == "general"


def test_el_chat_cambia_si_el_dominio_se_sostiene():
    sticky, settings = StickyModel(), Settings()

    sticky.choose("hola", settings)

    assert sticky.choose("resuelve la ecuación x + 1 = 2", settings) == "general"
    assert sticky.choose("ahora calcula la derivada de x^2", settings) == "razonador"
    assert sticky.choose("gracias", settings) == "razonador"


def test_cambio_de_dominio_con_el_mismo_modelo_es_inmediato():
    sticky = StickyModel()
    settings = Settings(models_by_domain={"code": "m", "math": "m", "general": "otro"})

    sticky.choose("explica este código", settings)

    assert sticky.choose("cuánto es 2 + 2", settings) == "m"
    assert sticky.domain == "math"


def test_forced_model_fija_el_modelo():
    sticky, settings = StickyModel(), Settings(forced_model="fijo")

    assert {sticky.choose(t, settings) for t in ["hola", "cuánto es 2 + 2", "def f(): pass"]} == {"fijo"}


# --- ProviderRouter -------------------------------------------------------------

class FakeProvider:
    def __init__(self):
        self.models = []

    def complete(self, messages, on_chunk=None, review=False, model=None, think=False):
        self.models.append(model)
        return "ok"


def make_router(settings):
    router = ProviderRouter.__new__(ProviderRouter)
    router.settings = settings
    router.memory = SimpleNamespace(load=lambda: {})
    router.project_memory = SimpleNamespace(load_project_summary=lambda name: "")
    router.providers = {"fake": FakeProvider()}
    router.history = []
    router.sticky_model = StickyModel()
    return router


def test_router_ask_usa_el_modelo_de_codigo_y_chat_el_pegajoso():
    router = make_router(Settings(default_provider="fake"))

    router.ask("revisa esto")
    router.chat("hola")
    router.chat("cuánto es 2 + 2")

    assert router.providers["fake"].models == ["coder", "general", "general"]


# --- Un modelo a la vez ---------------------------------------------------------

class FakeClient:
    def __init__(self, loaded=(), fail_ps=False):
        self.loaded = list(loaded)
        self.fail_ps = fail_ps
        self.unloaded = []
        self.chats = []

    def ps(self):
        if self.fail_ps:
            raise ConnectionError("sin Ollama")

        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in self.loaded])

    def generate(self, model, keep_alive=None):
        assert keep_alive == 0
        self.unloaded.append(model)

    def chat(self, model, messages, options=None, stream=False):
        self.chats.append(model)
        return {"message": {"content": '{"action": "chat", "params": {}}'}}


def test_unload_others_descarga_los_demas():
    client = FakeClient(["qwen2.5-coder:7b", "nomic-embed-text:latest", "otro:3b"])

    assert unload_others(client, "qwen2.5-coder:7b", Settings()) == ["nomic-embed-text:latest", "otro:3b"]


def test_unload_others_mismo_modelo_sin_tag():
    client = FakeClient(["nomic-embed-text:latest"])

    assert unload_others(client, "nomic-embed-text", Settings()) == []


def test_unload_others_desactivado_o_sin_ollama():
    assert unload_others(FakeClient(["a:1"]), "b:1", Settings(ollama_one_model_at_a_time=False)) == []
    assert unload_others(FakeClient(fail_ps=True), "b:1", Settings()) == []


def test_ollama_provider_usa_el_modelo_de_la_llamada_y_descarga_el_anterior():
    provider = OllamaProvider.__new__(OllamaProvider)
    provider.settings = Settings()
    provider.client = FakeClient(["coder"])

    provider.complete([{"role": "user", "content": "hola"}], model="general")
    provider.complete([{"role": "user", "content": "hola"}])

    assert provider.client.chats == ["general", "base"]
    assert provider.client.unloaded == ["coder", "coder"]


def test_intent_engine_descarga_otros_antes_de_clasificar():
    engine = IntentEngine.__new__(IntentEngine)
    engine.settings = Settings(intent_model="coder")
    engine.client = FakeClient(["general"])

    assert engine.detect("hola") == {"action": "chat", "params": {}}
    assert engine.client.unloaded == ["general"] and engine.client.chats == ["coder"]


# --- Flag --model ---------------------------------------------------------------

def test_flag_model_fija_el_modelo_de_la_sesion(monkeypatch):
    monkeypatch.setattr(launcher, "installed_models", lambda: ["qwen2.5-coder:7b", "qwen3:4b"])
    parser = launcher.build_parser()

    args = parser.parse_intermixed_args(["--model", "qwen3:4b", "hola"])

    assert launcher.session_overrides(args, parser) == {"forced_model": "qwen3:4b"}


def test_flag_model_no_descargado_es_error(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "installed_models", lambda: ["qwen2.5-coder:7b"])
    parser = launcher.build_parser()
    args = parser.parse_intermixed_args(["--model", "llama3.2:3b", "hola"])

    with pytest.raises(SystemExit):
        launcher.session_overrides(args, parser)

    assert "el modelo llama3.2:3b no está descargado en Ollama (descargados: qwen2.5-coder:7b)" in capsys.readouterr().err


def test_flag_model_sin_tag(monkeypatch):
    monkeypatch.setattr(launcher, "installed_models", lambda: ["nomic-embed-text:latest"])
    parser = launcher.build_parser()
    args = parser.parse_intermixed_args(["--model", "nomic-embed-text", "hola"])

    assert launcher.session_overrides(args, parser) == {"forced_model": "nomic-embed-text"}


# --- Código que parece matemáticas no va a "math" -------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "calcula el promedio en python",
        "calcula el promedio de una lista",
        "escribe una función que calcule la derivada",
        "suma 3 + 4 y guárdalo en una variable",
        "for i in range(10): total += i",
        "cómo sumo los elementos de un array",
        "cuánto es 2 + 2 en javascript",
        "calcula la desviación estándar de un DataFrame de pandas",
        "haz un bucle que sume del 1 al 100",
        "print(2**10)",
        "numpy.mean de [1,2,3]",
        "la ecuación de una recta en C++",
    ],
)
def test_codigo_con_palabras_de_matematicas_es_code(text):
    assert classify_domain(text) == "code"


@pytest.mark.parametrize(
    "text",
    [
        "resuelve 3x + 2 = 11",
        "calcula el 15% de 200",
        "deriva x^2 + 3x",
        "integral de sen(x)",
        "f(x) = x^2, ¿cuál es su derivada?",
        "raíz(16) + log(100)",
        "calcula la probabilidad de sacar dos seises",
    ],
)
def test_matematicas_sin_codigo_sigue_siendo_math(text):
    assert classify_domain(text) == "math"


# --- Modo de razonamiento -----------------------------------------------------

from providers.ollama_models import ThinkFilter, strip_think, think_kwargs
from core.model_selection import thinks


class ShowClient(FakeClient):
    def __init__(self, capabilities, loaded=()):
        super().__init__(loaded)
        self.capabilities = capabilities
        self.kwargs = []

    def show(self, model):
        return SimpleNamespace(capabilities=self.capabilities)

    def chat(self, model, messages, options=None, stream=False, **kwargs):
        self.chats.append(model)
        self.kwargs.append(kwargs)
        content = '<think>\nrazono...\n</think>\n\n{"action": "recall", "params": {"key": "nombre"}}'

        if stream:
            return iter([{"message": {"content": part}} for part in ["<thi", "nk>x</th", "ink>\n\nHola", " mundo"]])

        return {"message": {"content": content}}


def test_think_solo_a_modelos_que_lo_soportan():
    assert think_kwargs(ShowClient(["completion", "thinking"]), "razona:4b", False) == {"think": False}
    assert think_kwargs(ShowClient(["completion"]), "noraz:7b", True) == {}


def test_strip_think_y_filtro_de_streaming():
    assert strip_think("<think>\na\n</think>\n\nhola") == "hola"

    visible = ThinkFilter()
    out = "".join(visible.feed(part) for part in ["<thi", "nk>x</th", "ink>\n\nHola", " mundo"]) + visible.flush()

    assert out == "Hola mundo"
    keep = ThinkFilter()
    assert keep.feed("a < b") + keep.flush() == "a < b"


def test_thinks_solo_en_think_domains():
    settings = Settings(think_domains=["math"])

    assert thinks(settings, "math") and not thinks(settings, "general") and not thinks(settings, "code")


def test_intent_engine_sin_razonamiento_y_json_intacto():
    engine = IntentEngine.__new__(IntentEngine)
    engine.settings = Settings(intent_model="think-intent:4b")
    engine.client = ShowClient(["thinking"])

    assert engine.detect("cómo me llamo") == {"action": "recall", "params": {"key": "nombre"}}
    assert engine.client.kwargs == [{"think": False}]


def test_provider_pasa_think_y_no_devuelve_el_razonamiento():
    provider = OllamaProvider.__new__(OllamaProvider)
    provider.settings = Settings()
    provider.client = ShowClient(["thinking"])
    chunks = []

    answer = provider.complete([{"role": "user", "content": "x"}], model="think-prov:4b", think=True)
    streamed = provider.complete([{"role": "user", "content": "x"}], on_chunk=chunks.append, model="think-prov:4b")

    assert "<think>" not in answer and "razono" not in answer
    assert streamed == "".join(chunks) == "Hola mundo"
    assert provider.client.kwargs == [{"think": True}, {"think": False}]


def test_router_activa_think_solo_en_math():
    class ThinkProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.thinks = []

        def complete(self, messages, on_chunk=None, review=False, model=None, think=False):
            self.thinks.append(think)
            return "ok"

    router = make_router(Settings(default_provider="fake", think_domains=["math"],
                                  models_by_domain={"code": "c", "math": "m", "general": "m"}))
    router.providers["fake"] = ThinkProvider()

    router.ask("revisa esto")
    router.chat("hola")
    router.chat("resuelve 3x + 2 = 11")

    assert router.providers["fake"].thinks == [False, False, True]
