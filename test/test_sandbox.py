import sys
import tempfile
from pathlib import Path

import pytest

from core.brain import Brain
from tools.sandbox import PendingRun, RunResult, SandboxRunner, format_result, sandbox_import_problems

ASIA_PREFIX = Path(sys.prefix).resolve()


def sandbox_dirs():
    return {p.name for p in Path(tempfile.gettempdir()).glob("asia_sandbox_*")}


@pytest.fixture
def runner():
    before = sandbox_dirs()
    yield SandboxRunner(timeout=5, max_output=500)
    # Cada ejecución borra su venv y su carpeta de trabajo.
    assert sandbox_dirs() == before


# --- Runner real: crea un venv desechable de verdad --------------------------

def test_ejecuta_y_devuelve_la_salida(runner):
    result = runner.run("print('hola sandbox')\n")

    assert (result.returncode, result.stdout, result.timed_out) == (0, "hola sandbox\n", False)


def test_venv_propio_sin_los_paquetes_de_asia(runner):
    # numpy está en el .venv de Asia; en el sandbox no debe verse.
    code = (
        "import sys\nprint(sys.prefix)\n"
        "try:\n    import numpy\n    print('numpy visible')\n"
        "except ModuleNotFoundError:\n    print('sin numpy')\n"
    )

    result = runner.run(code)
    prefix, numpy_line = result.stdout.splitlines()

    assert Path(prefix).resolve() != ASIA_PREFIX
    assert "asia_sandbox_" in prefix
    assert numpy_line == "sin numpy"


def test_no_hay_pip_para_instalar(runner):
    code = (
        "import subprocess, sys\n"
        "r = subprocess.run([sys.executable, '-m', 'pip', 'install', 'requests'], capture_output=True, text=True)\n"
        "print(r.returncode != 0, 'No module named pip' in r.stderr)\n"
    )

    assert runner.run(code).stdout == "True True\n"


def test_carpeta_de_trabajo_temporal_y_sin_claves(runner, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "secreto")
    monkeypatch.chdir(tmp_path)
    code = (
        "import os\nprint(os.getcwd())\nprint(os.environ.get('GEMINI_API_KEY'))\n"
        "open('salida.txt', 'w').write('x')\n"
    )

    cwd, key = runner.run(code).stdout.splitlines()

    assert "asia_sandbox_" in cwd and Path(cwd) != tmp_path
    assert key == "None"
    assert not (tmp_path / "salida.txt").exists()


def test_error_devuelve_codigo_y_traceback(runner):
    result = runner.run("def f():\n    raise ValueError('mal')\nf()\n", "calc.py")

    assert result.returncode == 1
    assert "calc.py" in result.stderr and "ValueError: mal" in result.stderr


def test_limite_de_tiempo(runner):
    runner.timeout = 1

    result = runner.run("while True:\n    pass\n")

    assert result.timed_out and result.returncode is None
    assert "se detuvo al pasar el límite de 1 s" in format_result("bucle.py", result, 1)


def test_sin_stdin(runner):
    result = runner.run("import sys\nprint(repr(sys.stdin.read()))\n")

    assert result.stdout == "''\n"


def test_salida_recortada(runner):
    result = runner.run("print('x' * 2000)\n")

    assert result.stdout.startswith("x" * 500)
    assert "[salida recortada: 2001 caracteres]" in result.stdout


# --- Imports que no existen en el sandbox ------------------------------------

def test_sandbox_import_problems():
    assert sandbox_import_problems("import os\nimport json") == []
    assert sandbox_import_problems("import numpy\nfrom utilidades import f") == [
        "línea 1: import numpy",
        "línea 2: import utilidades",
    ]
    assert sandbox_import_problems("def (:") == []


# --- Flujo en Brain: preparar, confirmar, cancelar ---------------------------

class FakeRunner:
    timeout = 20

    def __init__(self):
        self.runs = []

    def run(self, code, script_name="script.py"):
        self.runs.append((code, script_name))
        return RunResult(0, "ok\n", "", False, 0.1)


class FakeApplyTool:
    def __init__(self, pending=None):
        self.pending = pending

    def load_pending_change(self):
        return self.pending

    def apply_pending_change(self):
        return "<aplicado>"


class FakeToolRegistry:
    def __init__(self, pending=None):
        self.apply_tool = FakeApplyTool(pending)

    def get_apply_changes_tool(self):
        return self.apply_tool


class FakeSettings:
    def get(self, key, default=None):
        return default


class FakeIntentEngine:
    def __init__(self, intent=None):
        self.intent = intent
        self.calls = 0

    def detect(self, text):
        self.calls += 1
        return self.intent or {"action": "chat", "params": {}}


def make_brain(tmp_path, intent=None, pending_change=None):
    brain = Brain.__new__(Brain)
    brain.intent_engine = FakeIntentEngine(intent)
    brain.tool_registry = FakeToolRegistry(pending_change)
    brain.settings = FakeSettings()
    brain.pending_run = PendingRun(tmp_path / "pending_run.json")
    brain.runner = FakeRunner()
    brain.sandbox = lambda: brain.runner
    return brain


def test_cambio_pendiente_se_prepara_y_no_se_ejecuta(tmp_path):
    pending = {"file_path": "pruebas/x.py", "new_content": "print('nuevo')\n"}
    brain = make_brain(tmp_path, {"action": "run_sandbox", "params": {}}, pending)

    message = brain.process("prueba el cambio pendiente")

    assert "Ejecución preparada: cambio pendiente para pruebas/x.py (1 líneas)" in message
    assert "puede leer o modificar tus archivos" in message
    assert 'Escribe "confirmar ejecución"' in message
    assert brain.runner.runs == []
    assert brain.pending_run.load()["code"] == "print('nuevo')\n"


def test_confirmar_ejecuta_la_copia_guardada_sin_llamar_al_llm(tmp_path):
    script = tmp_path / "script.py"
    script.write_text("print(1)\n", encoding="utf-8")
    brain = make_brain(tmp_path, {"action": "run_sandbox", "params": {"file_path": str(script)}})
    brain.process(f"ejecuta {script} en el sandbox")

    # El archivo cambia después de preparar: se ejecuta lo que se mostró.
    script.write_text("print('otra cosa')\n", encoding="utf-8")
    calls_before = brain.intent_engine.calls
    result = brain.process("Confirmar ejecución.")

    assert brain.intent_engine.calls == calls_before
    assert brain.runner.runs == [("print(1)\n", "script.py")]
    assert result.startswith(f"Resultado del sandbox ({script}): código de salida 0")
    assert brain.pending_run.load() is None


def test_confirmar_dos_veces_no_repite(tmp_path):
    brain = make_brain(tmp_path, pending_change=None)
    brain.prepare_run("a.py", "a.py", "print(1)\n")

    brain.process("confirmar ejecución")

    assert brain.process("confirmar ejecucion") == "No hay ninguna ejecución pendiente."
    assert len(brain.runner.runs) == 1


def test_cancelar(tmp_path):
    brain = make_brain(tmp_path)
    brain.prepare_run("a.py", "a.py", "print(1)\n")

    assert brain.process("cancelar ejecución") == "Ejecución cancelada."
    assert brain.process("confirmar ejecución") == "No hay ninguna ejecución pendiente."
    assert brain.runner.runs == []


@pytest.mark.parametrize("text", ["confirmar cambio", "confirmar", "ejecuta", "sí, confirmar ejecución ya"])
def test_otras_frases_no_ejecutan(tmp_path, text):
    brain = make_brain(tmp_path)
    brain.prepare_run("a.py", "a.py", "print(1)\n")

    brain.process(text)

    assert brain.runner.runs == []
    assert brain.pending_run.load() is not None


def test_imports_fuera_de_stdlib_no_se_preparan(tmp_path):
    pending = {"file_path": "moda.py", "new_content": "import pandas as pd\nprint(pd)\n"}
    brain = make_brain(tmp_path, {"action": "run_sandbox", "params": {}}, pending)

    message = brain.process("prueba el cambio pendiente")

    assert "el sandbox solo tiene la biblioteca estándar" in message
    assert "línea 1: import pandas" in message
    assert brain.pending_run.load() is None


def test_solo_archivos_python(tmp_path):
    notes = tmp_path / "notas.txt"
    notes.write_text("hola", encoding="utf-8")
    brain = make_brain(tmp_path, {"action": "run_sandbox", "params": {"file_path": str(notes)}})

    assert "Solo ejecuto archivos .py" in brain.process(f"ejecuta {notes}")
    assert brain.pending_run.load() is None


def test_sin_cambio_pendiente_ni_archivo(tmp_path):
    brain = make_brain(tmp_path, {"action": "run_sandbox", "params": {}})

    assert "No hay un cambio pendiente que probar" in brain.process("prueba el cambio pendiente")


def test_ruta_inventada_usa_el_cambio_pendiente(tmp_path):
    pending = {"file_path": "x.py", "new_content": "print(1)\n"}
    brain = make_brain(tmp_path, {"action": "run_sandbox", "params": {"file_path": "path/to/your/file.py"}}, pending)

    assert "Ejecución preparada: cambio pendiente para x.py" in brain.process("prueba el código propuesto")
