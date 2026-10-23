from core.brain import Brain, wants_unverified
from core.paths import DEFAULTS_FILE
from config.settings_manager import read_json
from providers.ollama_provider import OllamaProvider
from core.model_selection import StickyModel
from providers.provider_router import ProviderRouter
from tools.debug_agent_tool import DebugAgentTool

CONTENT = """for col in df.columns:
    if df[col].isnull().any():
        moda = df[col].mode().iloc[0]
with open(nombre_archivo, "w", encoding="utf-8") as f:
    f.write("x")
"""

RESPONSE = """HALLAZGO:
LINEA: 9
CITA: with open(nombre_archivo, "w", encoding="utf-8") as f:
CLAIM: trunca el original; un fallo a medias lo deja corrupto

HALLAZGO:
LINEA: 4
CITA: valor = meta[col]
CLAIM: KeyError
"""


class FakeToolRegistry:
    def __init__(self):
        self.calls = []

    def execute(self, action, **kwargs):
        self.calls.append(action)
        return CONTENT


class FakeProviderRouter:
    def __init__(self):
        self.calls = []

    def ask(self, prompt, review=False):
        self.calls.append((prompt, review))
        return RESPONSE


def make_tool():
    return DebugAgentTool(FakeToolRegistry(), FakeProviderRouter())


def test_review_file_deep_verifica_citas_y_no_usa_analisis_estatico():
    tool = make_tool()

    report = tool.review_file_deep("moda.py")

    assert tool.tool_registry.calls == ["read_file"]
    prompt, review = tool.provider_router.calls[0]
    assert review is True
    assert "Hallazgos estáticos" not in prompt
    assert "3 |         moda = df[col].mode().iloc[0]" in prompt
    assert "no encontré problemas" in prompt.lower()
    assert "mode().iloc[0]" in prompt  # ejemplo negativo de moda.py

    assert "1. Línea 4: `with open(" in report
    assert "KeyError" not in report
    assert "Descartados por cita no encontrada: 1" in report


def test_review_file_deep_muestra_sin_verificar_si_se_pide():
    report = make_tool().review_file_deep("moda.py", show_unverified=True)

    assert "SIN VERIFICAR" in report
    assert "KeyError" in report


def test_review_file_deep_archivo_inexistente():
    tool = make_tool()
    tool.tool_registry.execute = lambda action, **kwargs: "No encontré el archivo: x"

    assert tool.review_file_deep("x.py") == "No pude leer el archivo: x.py"
    assert tool.provider_router.calls == []


def test_review_project_files_un_reporte_verificado_por_archivo():
    tool = make_tool()

    report = tool.review_project_files(["a.py", "b.py"], max_chars=100)

    assert tool.tool_registry.calls == ["read_file_preview", "read_file_preview"]
    assert [review for _, review in tool.provider_router.calls] == [True, True]
    assert report.count("Citas encontradas en el archivo (análisis del modelo, no verificado):") == 2
    assert "FILE: a.py" in report and "FILE: b.py" in report
    assert "CONFIRMED_ISSUES" not in report


class FakeClient:
    def __init__(self):
        self.options = None

    def chat(self, model, messages, options, stream=False):
        self.options = options
        return {"message": {"content": "ok"}}


class FakeSettings:
    values = {
        "ollama_model": "m",
        "ollama_num_ctx": 4096,
        "ollama_temperature": 0.1,
        "ollama_repeat_penalty": 1.15,
    }

    def get(self, key, default=None):
        return self.values.get(key, default)


def make_ollama():
    provider = OllamaProvider.__new__(OllamaProvider)
    provider.settings = FakeSettings()
    provider.client = FakeClient()
    return provider


def test_ollama_opciones_de_revision_solo_con_review():
    provider = make_ollama()
    messages = [{"role": "user", "content": "hola"}]

    provider.complete(messages)
    assert provider.client.options == {"num_ctx": 4096}

    provider.complete(messages, review=True)
    assert provider.client.options == {
        "num_ctx": 4096,
        "temperature": 0.1,
        "repeat_penalty": 1.15,
    }


class FakeProvider:
    def __init__(self):
        self.reviews = []

    def complete(self, messages, on_chunk=None, review=False, model=None, think=False):
        self.reviews.append(review)
        return "ok"


class RouterSettings:
    def get(self, key, default=None):
        return {"default_provider": "fake", "active_project": ""}.get(key, default)


class FakeMemory:
    def load(self):
        return {}


def make_router():
    router = ProviderRouter.__new__(ProviderRouter)
    router.settings = RouterSettings()
    router.memory = FakeMemory()
    router.providers = {"fake": FakeProvider()}
    router.history = []
    router.sticky_model = StickyModel()
    return router


def test_router_pasa_review_solo_en_ask():
    router = make_router()

    router.ask("revisa", review=True)
    router.ask("resume")
    router.chat("hola")

    assert router.providers["fake"].reviews == [True, False, False]


def test_defaults_tienen_opciones_de_revision():
    defaults = read_json(DEFAULTS_FILE)

    assert defaults["ollama_temperature"] == 0.1
    assert defaults["ollama_repeat_penalty"] == 1.15


def test_wants_unverified():
    assert wants_unverified("revisa a fondo moda.py incluyendo lo sin verificar")
    assert wants_unverified("muestra todo")
    assert not wants_unverified("revisa a fondo moda.py")
    assert not wants_unverified(None)


class BrainRegistry:
    def __init__(self):
        self.kwargs = None

    def execute(self, action, **kwargs):
        self.kwargs = kwargs
        return "reporte"


class FakeIntentEngine:
    def detect(self, text):
        return {"action": "review_file_deep", "params": {"file_path": "moda.py"}}


def test_brain_review_file_deep_pasa_show_unverified():
    brain = Brain.__new__(Brain)
    brain.intent_engine = FakeIntentEngine()
    brain.tool_registry = BrainRegistry()

    assert brain.process("revisa a fondo moda.py, muestra todo") == "reporte"
    assert brain.tool_registry.kwargs == {"file_path": "moda.py", "show_unverified": True}
    assert brain.last_debug_report == "reporte"

    brain.process("revisa a fondo moda.py")
    assert brain.tool_registry.kwargs["show_unverified"] is False


TRUNCATING = """ruta = "datos.json"
datos = open(ruta).read()
with open(ruta, "w") as f:
    f.write(datos)
"""


class ContentRegistry:
    """Devuelve contenidos distintos para la vista previa y el archivo completo."""

    def __init__(self, preview, full=None):
        self.preview = preview
        self.full = full if full is not None else preview
        self.calls = []

    def execute(self, action, **kwargs):
        self.calls.append(action)
        return self.full if action == "read_file" else self.preview


class NoFindingsRouter:
    def ask(self, prompt, review=False):
        return "SIN_HALLAZGOS"


def test_review_file_deep_agrega_deteccion_automatica_en_su_seccion():
    tool = DebugAgentTool(ContentRegistry(TRUNCATING), NoFindingsRouter())

    report = tool.review_file_deep("guardar.py")

    auto, model = report.split("Citas encontradas en el archivo")
    assert "Detección automática (regla determinista con ast, sin LLM):" in auto
    assert '1. Línea 3: `with open(ruta, "w") as f:`' in auto
    assert "vacía el archivo antes de escribir" in auto
    assert "El modelo no reportó problemas" in model


def test_deteccion_automatica_solo_en_python():
    tool = DebugAgentTool(ContentRegistry(TRUNCATING), NoFindingsRouter())

    assert "Detección automática" not in tool.review_file_deep("notas.txt")


def test_review_project_files_usa_el_archivo_completo_si_la_vista_esta_recortada():
    preview = TRUNCATING[:40] + "\n\n... [archivo recortado]"
    registry = ContentRegistry(preview, full=TRUNCATING)
    tool = DebugAgentTool(registry, NoFindingsRouter())

    report = tool.review_project_files(["guardar.py"], max_chars=40)

    assert registry.calls == ["read_file_preview", "read_file"]
    assert "Detección automática" in report


def test_review_project_files_sin_recorte_no_relee():
    registry = ContentRegistry(TRUNCATING)
    tool = DebugAgentTool(registry, NoFindingsRouter())

    report = tool.review_project_files(["guardar.py"])

    assert registry.calls == ["read_file_preview"]
    assert "Detección automática" in report
