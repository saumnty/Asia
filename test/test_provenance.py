"""Paso 2 de la fase G: etiquetas de procedencia de cada fragmento."""
from types import SimpleNamespace

import pytest

import launcher
from config.settings_manager import read_json
from core.brain import Brain
from core.model_selection import StickyModel
from core.paths import DEFAULTS_FILE
from core.provenance import (
    ADJUNTO,
    ARCHIVO,
    DESCONOCIDO,
    EMOCIONAL,
    MEMORIA,
    PROYECTO,
    RAG,
    USUARIO,
    Fragment,
    chars_by_label,
    current_fragments,
    exportable_labels,
    labels_of,
    local_labels,
    most_restrictive,
    record,
    request_sources,
)
from core.session import Session
from providers.provider_router import ProviderRouter
from tools.tool_registry import ToolRegistry


class Settings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


# --- Reglas -------------------------------------------------------------------

def test_solo_usuario_es_siempre_exportable():
    assert exportable_labels(Settings()) == {USUARIO}
    assert exportable_labels(Settings(external_allow_memory=True)) == {USUARIO, MEMORIA}
    assert local_labels({USUARIO, ARCHIVO, ADJUNTO, RAG, PROYECTO, MEMORIA}, Settings()) == {
        ARCHIVO, ADJUNTO, RAG, PROYECTO, MEMORIA,
    }


def test_memoria_no_sale_por_defecto():
    assert read_json(DEFAULTS_FILE)["external_allow_memory"] is False


def test_la_mas_restrictiva():
    assert most_restrictive({USUARIO, MEMORIA}) == MEMORIA
    assert most_restrictive({USUARIO, ADJUNTO, ARCHIVO}) == ADJUNTO
    assert most_restrictive({ADJUNTO, EMOCIONAL}) == EMOCIONAL
    assert most_restrictive({USUARIO}) == USUARIO


def test_sin_registro_todo_es_desconocido_y_local():
    assert current_fragments() is None
    assert labels_of(None) == {DESCONOCIDO}
    assert local_labels({DESCONOCIDO}, Settings(external_allow_memory=True)) == {DESCONOCIDO}


def test_registro_anidado_suma_fragmentos():
    with request_sources(Fragment(USUARIO, "hola")):
        with request_sources(Fragment(ADJUNTO, "x = 1")):
            record(Fragment(ARCHIVO, "abc"), Fragment(ARCHIVO, ""))

        assert chars_by_label(current_fragments()) == {USUARIO: 4, ADJUNTO: 5, ARCHIVO: 3}

    assert current_fragments() is None


# --- Herramientas ---------------------------------------------------------------

@pytest.mark.parametrize(
    "action, label",
    [("read_file", ARCHIVO), ("read_folder_context", ARCHIVO), ("search_text", ARCHIVO),
     ("search_project_rag", RAG), ("open_app", None)],
)
def test_tool_registry_etiqueta_lo_que_lee(action, label):
    registry = ToolRegistry.__new__(ToolRegistry)
    registry.tools = {action: lambda **kwargs: "contenido"}

    with request_sources():
        registry.execute(action)
        fragments = current_fragments()

    assert fragments == ([Fragment(label, "contenido")] if label else [])


class RecordingRouter:
    def __init__(self):
        self.fragments = []

    def ask(self, prompt, review=False, domain="code", **limits):
        self.fragments.append(current_fragments())
        return "respuesta"


class OneIntent:
    def __init__(self, intent):
        self.intent = intent

    def detect(self, text):
        return self.intent


def test_brain_process_etiqueta_usuario_y_archivo(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    brain = Brain.__new__(Brain)
    brain.intent_engine = OneIntent({"action": "explain_file", "params": {"file_path": str(target)}})
    brain.provider_router = RecordingRouter()
    brain.settings = Settings(context_limits={"explain_file": 100})
    registry = ToolRegistry.__new__(ToolRegistry)
    registry.tools = {"read_file_preview": lambda file_path, max_chars: "x = 1\n"}
    brain.tool_registry = registry

    brain.process(f"explica {target}")

    assert labels_of(brain.provider_router.fragments[0]) == {USUARIO, ARCHIVO}


def test_ask_project_memory_etiqueta_proyecto():
    brain = Brain.__new__(Brain)
    brain.intent_engine = OneIntent({"action": "ask_project_memory", "params": {"question": "qué falta"}})
    brain.provider_router = RecordingRouter()
    brain.settings = Settings(active_project="asia")
    brain.project_memory = SimpleNamespace(load_project_summary=lambda name: "resumen del proyecto")

    brain.process("según mi proyecto, qué falta")

    assert labels_of(brain.provider_router.fragments[0]) == {USUARIO, PROYECTO}


# --- Launcher: tecleado, pegado, stdin y @ruta -----------------------------------

class ChatRouter:
    def __init__(self):
        self.fragments = []

    def chat(self, prompt, on_chunk=None, history_prompt=None):
        self.fragments.append(current_fragments())
        return "ok"


class FakeBrain:
    def __init__(self):
        self.settings = Settings(attachment_max_chars=1000)
        self.provider_router = ChatRouter()

    def process(self, text):
        return None


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(Session, "user_cwd", tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def chunks(values):
    values = iter(values)

    def read(prompt):
        try:
            return next(values)
        except StopIteration:
            raise EOFError

    return read


@pytest.mark.parametrize(
    "reads, labels",
    [
        # Tecleado, aunque tenga varias líneas: usuario.
        (["hola, ¿cómo estás?"], {USUARIO}),
        (["primera línea\nsegunda línea"], {USUARIO}),
        # Bloque << ... FIN: adjunto, con o sin instrucción.
        (["explica esto <<", "def f(): pass", "FIN"], {USUARIO, ADJUNTO}),
        (["<<", "def f(): pass", "FIN"], {ADJUNTO}),
        # @ruta: adjunto.
        (["explica @a.py"], {USUARIO, ADJUNTO}),
    ],
)
def test_etiquetas_del_modo_interactivo(cwd, reads, labels):
    brain = FakeBrain()

    launcher.interactive_mode(brain, read=chunks(reads))

    assert labels_of(brain.provider_router.fragments[0]) == labels


class FakeStdin:
    def __init__(self, data):
        import io

        self.buffer = io.BytesIO(data)

    def isatty(self):
        return False


@pytest.mark.parametrize("argv, labels", [(["explica", "esto"], {USUARIO, ADJUNTO}), ([], {ADJUNTO})])
def test_stdin_es_adjunto(cwd, argv, labels):
    brain = FakeBrain()

    launcher.main(argv, stdin=FakeStdin(b"def f(): pass\n"), brain_factory=lambda: brain)

    assert labels_of(brain.provider_router.fragments[0]) == labels


# --- Historial: cada turno hereda la etiqueta más restrictiva ---------------------

class FakeProvider:
    def __init__(self):
        self.fragments = []

    def complete(self, messages, on_chunk=None, review=False, model=None, think=False, max_tokens=None):
        return "respuesta"


def make_router(memory=None, project=""):
    router = ProviderRouter.__new__(ProviderRouter)
    router.settings = Settings(default_provider="fake", active_project="asia" if project else "")
    router.memory = SimpleNamespace(load=lambda: memory or {})
    router.project_memory = SimpleNamespace(load_project_summary=lambda name: project)
    router.providers = {"fake": FakeProvider()}
    router.history, router.history_labels = [], []
    router.last_fragments = None
    router.sticky_model = StickyModel()
    return router


def test_historial_hereda_la_etiqueta_mas_restrictiva():
    router = make_router()

    with request_sources(Fragment(USUARIO, "hola")):
        router.chat("hola")

    with request_sources(Fragment(USUARIO, "explica"), Fragment(ADJUNTO, "x = 1")):
        router.chat("explica\nx = 1", history_prompt="explica")

    assert router.history_labels == [USUARIO, USUARIO, ADJUNTO, ADJUNTO]
    # El siguiente mensaje lleva el historial con sus etiquetas.
    with request_sources(Fragment(USUARIO, "y ahora?")):
        router.chat("y ahora?")

    assert labels_of(router.last_fragments) == {USUARIO, ADJUNTO}


def test_memoria_y_proyecto_del_prompt_de_sistema():
    router = make_router(memory={"nombre": "Santiago"}, project="resumen")

    with request_sources(Fragment(USUARIO, "hola")):
        router.chat("hola")

    assert labels_of(router.last_fragments) == {USUARIO, MEMORIA, PROYECTO}
    # Una respuesta con memoria y proyecto en el contexto no queda como "usuario".
    assert router.history_labels == [PROYECTO, PROYECTO]


def test_chat_sin_registro_es_desconocido():
    router = make_router()

    router.chat("hola")

    assert labels_of(router.last_fragments) == {DESCONOCIDO}
