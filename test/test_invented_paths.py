import pytest

from core.brain import MISSING_FILE_MESSAGE, Brain, drop_invented_paths, path_in_text
from core.paths import PROJECT_ROOT


class FakeIntentEngine:
    def __init__(self, intent):
        self.intent = intent

    def detect(self, text):
        return self.intent


class FakeToolRegistry:
    def __init__(self):
        self.calls = []

    def execute(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return "contenido"


class FakeRouter:
    def __init__(self):
        self.prompts = []

    def ask(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return "explicación"


class FakeSettings:
    def get(self, key, default=None):
        return {"context_limits": {"explain_file": 100}}.get(key, default)


def make_brain(action, params):
    brain = Brain.__new__(Brain)
    brain.intent_engine = FakeIntentEngine({"action": action, "params": params})
    brain.tool_registry = FakeToolRegistry()
    brain.provider_router = FakeRouter()
    brain.settings = FakeSettings()
    return brain


PLACEHOLDERS = [
    "path/to/your/file.py", "path_to_your_file.py", "ruta/al/archivo.py", "example.py",
    # Visto con qwen2.5-coder:7b para "explica este archivo".
    "ruta/al/archivo",
]


@pytest.mark.parametrize("placeholder", PLACEHOLDERS)
def test_ruta_inventada_sin_archivo_en_el_mensaje_es_chat(placeholder):
    brain = make_brain("explain_file", {"file_path": placeholder})

    assert brain.process("explícame qué es una closure en Python") is None
    assert brain.tool_registry.calls == []
    assert brain.provider_router.prompts == []


@pytest.mark.parametrize("placeholder", PLACEHOLDERS)
@pytest.mark.parametrize(
    "text",
    ["explica este archivo", "qué hace el script?", "explica el módulo de memoria"],
)
def test_ruta_inventada_hablando_de_un_archivo_pide_la_ruta(placeholder, text):
    brain = make_brain("explain_file", {"file_path": placeholder})

    assert brain.process(text) == MISSING_FILE_MESSAGE
    assert brain.tool_registry.calls == []


@pytest.mark.parametrize("action", ["create_file", "read_file", "review_file_deep", "smart_refactor"])
def test_otras_acciones_tampoco_usan_la_ruta_inventada(action):
    brain = make_brain(action, {"file_path": "path/to/your/file.py", "content": "x"})

    assert brain.process("crea un archivo con hola mundo") == MISSING_FILE_MESSAGE
    assert brain.tool_registry.calls == []


def test_ruta_del_mensaje_si_se_usa(monkeypatch):
    monkeypatch.chdir(PROJECT_ROOT)
    brain = make_brain("explain_file", {"file_path": "core/brain.py"})

    assert brain.process("explica core/brain.py") == "explicación"
    assert brain.tool_registry.calls[0][1]["file_path"] == "core/brain.py"


def test_carpeta_inventada_pasa_a_la_carpeta_actual():
    brain = make_brain("list_folder", {"folder_path": "path/to/your/folder"})

    brain.process("lista la carpeta")

    assert brain.tool_registry.calls == [("list_folder", {"folder_path": "."})]


@pytest.mark.parametrize(
    "value, text",
    [
        ("core/brain.py", "explica core/brain.py"),
        ("core/brain.py", "explica brain.py"),
        ("core\\brain.py", "explica core/brain.py"),
        ("C:\\Users\\ana\\moda.py", "revisa a fondo C:\\Users\\ana\\moda.py"),
        ("pruebas", "revisa la carpeta pruebas"),
        ("core/utils", "revisa utils"),
        ('"mis notas/a.txt"', 'lee "mis notas/a.txt"'),
    ],
)
def test_path_in_text_acepta(value, text, monkeypatch):
    monkeypatch.chdir(PROJECT_ROOT)

    assert path_in_text(value, text)


@pytest.mark.parametrize(
    "value, text",
    [
        ("path/to/your/file.py", "explica este archivo"),
        ("path_to_your_file.py", "explica el archivo"),
        # "archivo" sale del mensaje, pero la ruta no existe.
        ("ruta/al/archivo", "explica este archivo"),
        ("core/brain.py", "explica cerebro.py"),
        # "brain.py" dentro de otra palabra no cuenta.
        ("brain.py", "explica mybrain.py"),
        # Nombre sin extensión: solo si el archivo existe.
        ("no_existe/brain.py", "explica el archivo brain"),
        ("", "explica"),
    ],
)
def test_path_in_text_rechaza(value, text):
    assert not path_in_text(value, text)


def test_nombre_sin_extension_si_el_archivo_existe(monkeypatch):
    monkeypatch.chdir(PROJECT_ROOT)

    assert path_in_text("core/brain.py", "explica el archivo brain")


def test_drop_invented_paths_no_modifica_el_original():
    params = {"file_path": "path/to/your/file.py", "folder_path": "."}

    cleaned, missing = drop_invented_paths("explica", params)

    assert cleaned == {"folder_path": "."}
    assert missing is True
    assert params == {"file_path": "path/to/your/file.py", "folder_path": "."}
