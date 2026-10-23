import pytest

from core.brain import Brain
from tools.import_check import (
    NOT_ALLOWED,
    NOT_INSTALLED,
    ImportPolicy,
    check_imports,
    extract_imports,
    find_requirements,
    import_names_for,
    parse_requirements,
)

# Instalado en el .venv de Asia pero fuera de su requirements.txt.
INSTALLED_NOT_LISTED = "numpy"
NOT_A_PACKAGE = "paquete_inventado_xyz"


def issues(code, policy):
    return [(i.module, i.reason) for i in check_imports(code, policy).issues]


def test_extract_imports():
    code = """import os, json.decoder
from collections import abc
from . import vecino
from .. import otro
import importlib
mod = importlib.import_module("yaml.loader")
other = __import__("toml")
dynamic = importlib.import_module(name)
"""

    assert extract_imports(code) == [
        ("json", 1), ("os", 1), ("collections", 2), ("importlib", 5), ("yaml", 6), ("toml", 7),
    ]


def test_extract_imports_codigo_invalido():
    with pytest.raises(SyntaxError):
        extract_imports("def (:")


def test_parse_requirements(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text(
        "# comentario\nrequests==2.0\ngoogle-genai>=1 ; python_version>'3'\n"
        "uvicorn[standard]~=0.1\n-r otros.txt\n-e .\n\nPyYAML  # yaml\n",
        encoding="utf-8",
    )

    assert parse_requirements(path) == ["requests", "google-genai", "uvicorn", "PyYAML"]


def test_import_names_for():
    assert "google" in import_names_for("google-genai")
    assert import_names_for("Prompt-Toolkit") == {"prompt_toolkit"}
    assert import_names_for("no-instalado-xyz") == {"no_instalado_xyz"}


def test_find_requirements_no_sale_de_la_carpeta_del_usuario(tmp_path):
    project = tmp_path / "proyecto"
    (project / "src").mkdir(parents=True)
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")

    assert find_requirements(project / "src" / "a.py", project) is None

    (project / "requirements.txt").write_text("requests\n", encoding="utf-8")
    assert find_requirements(project / "src" / "a.py", project) == project / "requirements.txt"


@pytest.fixture
def project(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.34.2\n", encoding="utf-8")
    (tmp_path / "utilidades.py").write_text("", encoding="utf-8")
    (tmp_path / "paquete").mkdir()
    (tmp_path / "paquete" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "viejo.py").write_text(f"import {INSTALLED_NOT_LISTED}\nimport pandas\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "code",
    [
        "import os\nfrom pathlib import Path\nimport json",
        "import requests",
        "import utilidades\nfrom paquete import x",
        "from . import algo",
    ],
)
def test_imports_aceptados(project, code):
    policy = ImportPolicy.for_file(project / "nuevo.py", project)

    assert issues(code, policy) == []


@pytest.mark.parametrize(
    "code, expected",
    [
        (f"import {NOT_A_PACKAGE}", [(NOT_A_PACKAGE, NOT_INSTALLED)]),
        (f"import {INSTALLED_NOT_LISTED}", [(INSTALLED_NOT_LISTED, NOT_ALLOWED)]),
        (f"import os\nfrom {NOT_A_PACKAGE}.sub import x", [(NOT_A_PACKAGE, NOT_INSTALLED)]),
    ],
)
def test_imports_rechazados(project, code, expected):
    policy = ImportPolicy.for_file(project / "nuevo.py", project)

    assert issues(code, policy) == expected


def test_imports_que_el_archivo_ya_tenia_se_aceptan(project):
    # pandas no está en el .venv de Asia, pero viejo.py ya lo usaba.
    policy = ImportPolicy.for_file(project / "viejo.py", project)

    assert issues(f"import {INSTALLED_NOT_LISTED}\nimport pandas", policy) == []
    assert issues(f"import pandas\nimport {NOT_A_PACKAGE}", policy) == [(NOT_A_PACKAGE, NOT_INSTALLED)]


def test_allowed_imports_de_la_configuracion(project):
    policy = ImportPolicy.for_file(project / "nuevo.py", project, extra=[INSTALLED_NOT_LISTED])

    assert issues(f"import {INSTALLED_NOT_LISTED}", policy) == []


def test_codigo_invalido_no_pasa(project):
    report = check_imports("def (:", ImportPolicy.for_file(project / "nuevo.py", project))

    assert not report.ok
    assert "no es Python válido" in report.describe()


def test_describe_lista_lo_permitido(project):
    text = ImportPolicy.for_file(project / "viejo.py", project).describe()

    assert text.startswith("biblioteca estándar de Python, módulos del propio proyecto")
    assert "requests" in text and "pandas" in text and INSTALLED_NOT_LISTED in text


# --- Integración con generate_code y smart_refactor -------------------------

def code_response(code, path="nuevo.py", explanation="explicación"):
    return f"FILE_PATH:\n{path}\n\nCODE:\n{code}\n\nEXPLANATION:\n{explanation}"


class ScriptedRouter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def ask(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return self.responses.pop(0)


class FakeApplyTool:
    def __init__(self):
        self.proposed = []

    def propose_change(self, file_path, new_content):
        self.proposed.append((file_path, new_content))
        return "diff propuesto"


class FakeToolRegistry:
    def __init__(self):
        self.apply_tool = FakeApplyTool()

    def execute(self, action, **kwargs):
        return "contexto"

    def get_apply_changes_tool(self):
        return self.apply_tool


class FakeSettings:
    def get(self, key, default=None):
        limits = {
            "generate_code_project": {"max_files": 1, "max_chars_per_file": 10},
            "generate_code_file": 100,
        }
        return {"context_limits": limits}.get(key, default)


class FakeIntentEngine:
    def __init__(self, intent):
        self.intent = intent

    def detect(self, text):
        return self.intent


def make_brain(intent, responses):
    brain = Brain.__new__(Brain)
    brain.intent_engine = FakeIntentEngine(intent)
    brain.tool_registry = FakeToolRegistry()
    brain.provider_router = ScriptedRouter(responses)
    brain.settings = FakeSettings()
    brain.last_debug_report = None
    return brain


GOOD = "import json\n\nprint(json.dumps({}))"
BAD = f"import {NOT_A_PACKAGE}\n\nprint({NOT_A_PACKAGE}.hola())"


@pytest.fixture
def in_project(project, monkeypatch):
    monkeypatch.chdir(project)
    return project


def generate(responses, request="crea nuevo.py que imprima json"):
    return make_brain({"action": "generate_code", "params": {"request": request}}, responses)


def test_generate_code_con_imports_validos_propone_sin_reintentar(in_project):
    brain = generate([code_response(GOOD)])

    brain.process("crea nuevo.py que imprima json")

    assert len(brain.provider_router.prompts) == 1
    assert "Solo puedes importar: biblioteca estándar de Python" in brain.provider_router.prompts[0]
    assert brain.tool_registry.apply_tool.proposed == [("nuevo.py", GOOD)]


def test_generate_code_pide_reescritura_y_propone_la_corregida(in_project):
    brain = generate([code_response(BAD), code_response(GOOD)])

    brain.process("crea nuevo.py que imprima json")

    retry = brain.provider_router.prompts[1]
    assert f"import {NOT_A_PACKAGE} ({NOT_INSTALLED})" in retry
    assert brain.tool_registry.apply_tool.proposed == [("nuevo.py", GOOD)]


def test_generate_code_no_propone_si_la_reescritura_sigue_mal(in_project):
    brain = generate([code_response(BAD), code_response(f"import {INSTALLED_NOT_LISTED}")])

    result = brain.process("crea nuevo.py que imprima json")

    assert len(brain.provider_router.prompts) == 2
    assert brain.tool_registry.apply_tool.proposed == []
    assert result.startswith("No propongo el cambio para nuevo.py")
    assert f"import {INSTALLED_NOT_LISTED} ({NOT_ALLOWED})" in result
    assert "Asia no instala paquetes" in result


def test_generate_code_archivo_no_python_no_se_chequea(in_project):
    brain = generate([code_response(f"import {NOT_A_PACKAGE}", "notas.txt")], "crea notas.txt")

    brain.process("crea notas.txt")

    assert brain.tool_registry.apply_tool.proposed == [("notas.txt", f"import {NOT_A_PACKAGE}")]


def test_smart_refactor_no_propone_imports_inventados(in_project):
    (in_project / "calc.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    brain = make_brain(
        {"action": "smart_refactor", "params": {"file_path": "calc.py"}},
        [code_response(BAD, "calc.py"), code_response(BAD, "calc.py")],
    )

    result = brain.process("refactoriza calc.py")

    assert "Solo puedes importar" in brain.provider_router.prompts[0]
    assert result.startswith("No propongo el cambio para calc.py")
    assert brain.tool_registry.apply_tool.proposed == []


def test_reescritura_dice_que_libreria_usaba_y_cual_la_sustituye(in_project):
    # "genera un código en prueba.py que use la librería superjson_mega":
    # salía con json y el mensaje no nombraba superjson_mega.
    brain = generate([code_response(BAD), code_response(GOOD, explanation="Imprime un JSON.")])

    result = brain.process("crea nuevo.py que imprima json")

    assert (
        f"Aviso: el código generado usaba {NOT_A_PACKAGE} ({NOT_INSTALLED}). "
        "Se pidió una reescritura y ahora usa json en su lugar."
    ) in result
    assert result.index("Aviso:") < result.index("Imprime un JSON.")


def test_reescritura_sin_libreria_en_su_lugar(in_project):
    brain = generate([code_response(BAD), code_response("print({})")])

    result = brain.process("crea nuevo.py que imprima json")

    assert "ahora no usa ninguna librería en su lugar" in result


def test_sin_reescritura_no_hay_aviso(in_project):
    brain = generate([code_response(GOOD)])

    assert "Aviso:" not in brain.process("crea nuevo.py que imprima json")
