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


# --- Mensajes de varias líneas (código pegado sin <<) -------------------------

PASTED = (
    "explica esto\n"
    "def suma(valores):\n"
    "    resultado = []\n"
    "    for v in valores:\n"
    "        resultado.append(v * 2)\n"
    "    return resultado"
)


@pytest.mark.parametrize(
    "action, params",
    [
        ("explain_file", {}),
        ("explain_file", {"file_path": "path/to/your/file.py"}),
        ("summarize_file", {}),
        ("review_file", {}),
        ("review_file_deep", {"file_path": "suma.py"}),
        ("smart_refactor", {"request": "explica esto"}),
        ("read_file_preview", {"file_path": "codigo.py"}),
    ],
)
def test_varias_lineas_sin_ruta_valida_van_al_chat(action, params):
    # "resultado.append" parece un nombre de archivo para FILE_WORDS y la
    # acción de archivo sin ruta respondía "Necesito la ruta del archivo".
    brain = make_brain(action, params)

    assert brain.process(PASTED) is None
    assert brain.tool_registry.calls == []
    assert brain.provider_router.prompts == []


@pytest.mark.parametrize(
    "action, params, expected",
    [
        ("explain_file", {"file_path": "ruta/al/archivo.py"}, MISSING_FILE_MESSAGE),
        ("explain_file", {}, "Necesito la ruta del archivo."),
        ("review_file_deep", {}, "Necesito la ruta del archivo para revisarlo profundamente."),
    ],
)
def test_mensaje_corto_que_habla_de_un_archivo_sigue_pidiendo_la_ruta(action, params, expected):
    assert make_brain(action, params).process("explica este archivo") == expected


def test_varias_lineas_con_ruta_valida_usa_la_accion(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    brain = make_brain("explain_file", {"file_path": str(target)})

    assert brain.process(f"explica {target}\nen detalle\npor favor") == "explicación"
