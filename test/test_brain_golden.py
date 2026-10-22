"""Caracterización de Brain.process: prompts, llamadas y respuestas.

Cada caso pasa por Brain.process con dobles que registran todo: el prompt
exacto que llega al LLM (y si es revisión), las llamadas a tools, memoria y
ajustes, y lo que devuelve. El resultado se compara con
test/golden/brain_process.json, generado con el código anterior al refactor
de la fase E. Si un prompt cambia en un carácter, falla.

Para regenerar a propósito (solo si el cambio de comportamiento es deseado):
    $env:ASIA_UPDATE_GOLDEN = "1"; .venv\\Scripts\\python.exe -m pytest test/test_brain_golden.py
"""
import json
import os
from pathlib import Path

import pytest

from core.brain import Brain
from tools.sandbox import PendingRun, RunResult

GOLDEN = Path(__file__).parent / "golden" / "brain_process.json"

A_PY = 'def f():\n    print("hola")\n    return None\n'

CODE_OK = "FILE_PATH:\na.py\n\nCODE:\ndef f():\n    print('hola')\n    return 1\n\nEXPLANATION:\nlimpio"
CODE_SAME = f"FILE_PATH:\na.py\n\nCODE:\n{A_PY}\nEXPLANATION:\nigual"
CODE_RAISE = "FILE_PATH:\na.py\n\nCODE:\ndef f():\n    raise ValueError()\n\nEXPLANATION:\ncambia"
CODE_BAD_IMPORT = "FILE_PATH:\na.py\n\nCODE:\nimport paquete_inventado_xyz\n\nEXPLANATION:\nmal"
CODE_RE = "FILE_PATH:\nnuevo.py\n\nCODE:\nx = re.compile('a')\n\nEXPLANATION:\nusa re"
CODE_PROTECTED = "FILE_PATH:\ncore/brain.py\n\nCODE:\nx = 1\n\nEXPLANATION:\ntoca brain"


def step(text, action=None, **params):
    return {"text": text, "intent": None if action is None else {"action": action, "params": params}}


CASES = {
    # Memoria y ajustes
    "remember": [step("recuerda que mi color es azul", "remember", key="color", value="azul")],
    "remember_sin_valor": [step("recuerda mi color", "remember", key="color")],
    "recall": [step("cuál es mi color", "recall", key="color")],
    "recall_sin_dato": [step("cuál es mi perro", "recall", key="perro")],
    "forget": [step("olvida mi color", "forget", key="color")],
    "forget_sin_dato": [step("olvida mi perro", "forget", key="perro")],
    "show_settings": [step("muestra la configuración", "show_settings")],
    "set_provider": [step("usa Gemini", "set_provider", provider=" Gemini ")],
    "set_provider_alias": [step("usa olama", "set_provider", provider="olama")],
    "set_provider_desconocido": [step("usa openai", "set_provider", provider="openai")],
    "set_provider_vacio": [step("cambia el provider", "set_provider")],
    "set_active_project": [step("cambia al proyecto BolitaBot", "set_active_project", project_name="BolitaBot")],
    "set_active_project_vacio": [step("cambia de proyecto", "set_active_project")],
    "show_active_project": [step("cuál es el proyecto activo", "show_active_project")],
    "summarize_and_save_project": [step("resume y guarda el proyecto", "summarize_and_save_project")],
    "ask_project_memory": [step("de qué trata el proyecto", "ask_project_memory", question="de qué trata")],
    "ask_project_memory_sin_resumen": [
        step("cambia al proyecto otro", "set_active_project", project_name="otro"),
        step("de qué trata el proyecto", "ask_project_memory"),
    ],
    "update_project_memory": [step("anota que falta X", "update_project_memory", note="falta X")],
    "update_project_memory_vacio": [step("anota algo", "update_project_memory")],
    # RAG, lectura y explicación
    "index_project_rag": [step("indexa el proyecto", "index_project_rag")],
    "search_project_rag": [step("dónde se usa ollama", "search_project_rag", question="dónde se usa ollama")],
    "summarize_file": [step("resume a.py", "summarize_file", file_path="a.py")],
    "summarize_file_vacio": [step("resume", "summarize_file")],
    "summarize_folder": [step("resume la carpeta src", "summarize_folder", folder_path="src")],
    "explain_file": [step("explica a.py", "explain_file", file_path="a.py")],
    "explain_file_vacio": [step("explica", "explain_file")],
    "find_references": [step("dónde se usa foo", "find_references", query="foo")],
    "find_references_vacio": [step("busca referencias", "find_references")],
    "explain_symbol": [step("explica Brain en src", "explain_symbol", symbol="Brain", folder_path="src")],
    "explain_symbol_vacio": [step("explica el símbolo", "explain_symbol")],
    "map_project": [step("mapea el proyecto", "map_project")],
    "find_dependencies": [step("quién depende de os", "find_dependencies", query="os")],
    "find_dependencies_vacio": [step("dependencias", "find_dependencies")],
    # Revisión y depuración
    "review_file": [step("revisa a.py", "review_file", file_path="a.py")],
    "review_file_vacio": [step("revisa", "review_file")],
    "review_project": [step("revisa el proyecto", "review_project")],
    "review_project_sin_sintesis": [step("revisa el proyecto sin síntesis", "review_project", folder_path=".")],
    "review_project_muestra_todo": [step("revisa src, muestra todo", "review_project", folder_path="src", synthesis=False)],
    "detect_dead_code": [step("busca código muerto", "detect_dead_code")],
    "debug_project": [step("por qué aparece None", "debug_project", issue="aparece None")],
    "review_file_deep": [step("revisa a fondo a.py", "review_file_deep", file_path="a.py")],
    "review_file_deep_muestra_todo": [step("revisa a fondo a.py, muestra todo", "review_file_deep", file_path="a.py")],
    "review_file_deep_vacio": [step("revisa a fondo", "review_file_deep")],
    # Generación y cambios
    "smart_refactor": [step("refactoriza a.py", "smart_refactor", file_path="a.py", request="refactoriza a.py")],
    "smart_refactor_sin_cambios": [step("refactoriza a.py", "smart_refactor", file_path="a.py")],
    "smart_refactor_prohibido": [step("refactoriza a.py", "smart_refactor", file_path="a.py")],
    "smart_refactor_import_malo": [step("refactoriza a.py", "smart_refactor", file_path="a.py")],
    "smart_refactor_sin_code": [step("refactoriza a.py", "smart_refactor", file_path="a.py")],
    "smart_refactor_vacio": [step("refactoriza", "smart_refactor")],
    "smart_refactor_no_existe": [step("refactoriza b.py", "smart_refactor", file_path="b.py")],
    "generate_code": [step("corrige a.py", "generate_code", request="corrige a.py")],
    "generate_code_con_diagnostico": [
        step("revisa a fondo a.py", "review_file_deep", file_path="a.py"),
        step("corrige los bugs de a.py", "generate_code", request="corrige los bugs de a.py"),
    ],
    "generate_code_sin_cambios": [step("corrige a.py", "generate_code", request="corrige a.py")],
    "generate_code_prohibido": [step("corrige a.py", "generate_code", request="corrige a.py")],
    "generate_code_agrega_re": [step("crea nuevo.py", "generate_code", request="crea nuevo.py")],
    "generate_code_protegido": [step("cambia el cerebro", "generate_code", request="cambia el cerebro")],
    "generate_code_sin_code": [step("corrige a.py", "generate_code", request="corrige a.py")],
    "apply_change": [step("confirmar cambio", "apply_change")],
    "cancel_change": [step("cancelar cambio", "cancel_change")],
    "show_pending_change": [step("muestra el cambio pendiente", "show_pending_change")],
    "open_app": [step("abre chrome", "open_app", app_name="chrome")],
    "create_file": [step("crea notas.txt con hola", "create_file", file_path="notas.txt", content="hola")],
    "read_file": [step("lee a.py", "read_file", file_path="a.py")],
    "list_folder": [step("lista la carpeta src", "list_folder", folder_path="src")],
    "append_file": [step("agrega adiós a notas.txt", "append_file", file_path="notas.txt", content="adiós")],
    "search_files": [step("busca archivos hola", "search_files", query="hola", folder_path=".")],
    "search_text": [step("busca Ollama", "search_text", query="Ollama", folder_path=".")],
    "read_file_preview": [step("vista previa de a.py", "read_file_preview", file_path="a.py", max_chars=10)],
    # Conversación y rutas inventadas
    "chat": [step("hola, ¿cómo estás?", "chat")],
    "accion_desconocida": [step("haz algo raro", "accion_que_no_existe")],
    "ruta_inventada_chat": [step("qué es una closure", "explain_file", file_path="path/to/your/file.py")],
    "ruta_inventada_pide_ruta": [step("explica este archivo", "explain_file", file_path="path/to/your/file.py")],
    "carpeta_inventada": [step("lista la carpeta", "list_folder", folder_path="path/to/folder")],
    # Sandbox
    "run_sandbox_archivo": [
        step("ejecuta s.py en el sandbox", "run_sandbox", file_path="s.py"),
        step("confirmar ejecución"),
    ],
    "run_sandbox_pendiente_y_cancelar": [
        step("prueba el cambio pendiente", "run_sandbox"),
        step("cancelar ejecución"),
        step("confirmar ejecución"),
    ],
    "run_sandbox_no_python": [step("ejecuta notas.txt", "run_sandbox", file_path="notas.txt")],
    "run_sandbox_import_malo": [step("ejecuta m.py en el sandbox", "run_sandbox", file_path="m.py")],
}

# Respuestas del LLM por caso (en orden); el resto recibe "respuesta-llm".
RESPONSES = {
    "smart_refactor": [CODE_OK],
    "smart_refactor_sin_cambios": [CODE_SAME],
    "smart_refactor_prohibido": [CODE_RAISE],
    "smart_refactor_import_malo": [CODE_BAD_IMPORT, CODE_BAD_IMPORT],
    "smart_refactor_sin_code": ["no sé"],
    "generate_code": [CODE_OK],
    "generate_code_con_diagnostico": [CODE_OK],
    "generate_code_sin_cambios": [CODE_SAME],
    "generate_code_prohibido": [CODE_RAISE],
    "generate_code_agrega_re": [CODE_RE],
    "generate_code_protegido": [CODE_PROTECTED],
    "generate_code_sin_code": ["no sé"],
}

PENDING_CHANGE = {"file_path": "p.py", "new_content": "print('pendiente')\n"}


class Recorder:
    def __init__(self):
        self.events = []

    def add(self, *event):
        self.events.append(list(event))


class FakeIntentEngine:
    def __init__(self, steps):
        self.intents = [s["intent"] for s in steps if s["intent"] is not None]

    def detect(self, text):
        return self.intents.pop(0)


class FakeRouter:
    provider_factories = {"ollama": None, "gemini": None}

    def __init__(self, recorder, responses):
        self.recorder = recorder
        self.responses = list(responses)

    def ask(self, prompt, review=False):
        self.recorder.add("ask", prompt, review)
        return self.responses.pop(0) if self.responses else "respuesta-llm"


class FakeApplyTool:
    def __init__(self, recorder):
        self.recorder = recorder

    def propose_change(self, file_path, new_content):
        self.recorder.add("propose_change", file_path, new_content)
        return f"<diff {file_path}>"

    def apply_pending_change(self):
        self.recorder.add("apply_pending_change")
        return "<aplicado>"

    def cancel_pending_change(self):
        self.recorder.add("cancel_pending_change")
        return "<cancelado>"

    def show_pending_change(self):
        self.recorder.add("show_pending_change")
        return "<pendiente>"

    def load_pending_change(self):
        return PENDING_CHANGE


class FakeToolRegistry:
    def __init__(self, recorder):
        self.recorder = recorder
        self.apply_tool = FakeApplyTool(recorder)

    def execute(self, action, **kwargs):
        self.recorder.add("tool", action, sorted((k, repr(v)) for k, v in kwargs.items()))

        if action == "select_project_files":
            return ["a.py", "src/b.py"]

        if action in ("read_file", "read_file_preview"):
            return A_PY

        return f"<{action}>"

    def get_apply_changes_tool(self):
        return self.apply_tool


class FakeMemory:
    def __init__(self, recorder):
        self.recorder = recorder
        self.data = {"color": "azul"}

    def remember(self, key, value):
        self.recorder.add("remember", key, value)
        self.data[key] = value

    def recall(self, key):
        return self.data.get(key)

    def forget(self, key):
        self.recorder.add("forget", key)
        return self.data.pop(key, None) is not None


class FakeProjectMemory:
    def __init__(self, recorder):
        self.recorder = recorder

    def save_project_summary(self, name, summary):
        self.recorder.add("save_project_summary", name, summary)

    def load_project_summary(self, name):
        return "Resumen de asia" if name == "asia" else None

    def append_project_note(self, name, note):
        self.recorder.add("append_project_note", name, note)


class FakeSettings:
    def __init__(self, recorder):
        self.recorder = recorder
        self.values = {
            "default_provider": "ollama",
            "fallback_provider": "ollama",
            "stream_output": False,
            "ollama_model": "qwen2.5-coder:7b",
            "active_project": "Asia",
            "provider_aliases": {"olama": "ollama"},
            "project_aliases": {"bolitabot": "pt"},
            "review_project_synthesis": True,
            "allowed_imports": [],
            "sandbox_timeout": 20,
            "context_limits": {
                "summarize_file": 6000,
                "explain_file": 8000,
                "review_file": 10000,
                "generate_code_file": 12000,
                "review_project_file": 3000,
                "review_project_files": 15,
                "summarize_folder": {"max_files": 12, "max_chars_per_file": 1200},
                "save_project_summary": {"max_files": 15, "max_chars_per_file": 1500},
                "map_project": {"max_files": 30, "max_chars_per_file": 800},
                "generate_code_project": {"max_files": 25, "max_chars_per_file": 800},
            },
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.recorder.add("settings.set", key, value)
        self.values[key] = value


class FakeRunner:
    timeout = 20

    def __init__(self, recorder):
        self.recorder = recorder

    def run(self, code, script_name="script.py"):
        self.recorder.add("sandbox.run", code, script_name)
        return RunResult(0, "salida\n", "", False, 0.25)


def run_case(name, steps, folder):
    recorder = Recorder()
    brain = Brain.__new__(Brain)
    brain.intent_engine = FakeIntentEngine(steps)
    brain.provider_router = FakeRouter(recorder, RESPONSES.get(name, []))
    brain.tool_registry = FakeToolRegistry(recorder)
    brain.memory = FakeMemory(recorder)
    brain.project_memory = FakeProjectMemory(recorder)
    brain.settings = FakeSettings(recorder)
    brain.last_debug_report = None
    brain.pending_run = PendingRun(folder / "pending_run.json")
    runner = FakeRunner(recorder)
    brain.sandbox = lambda: runner

    results = []

    for s in steps:
        recorder.add("process", s["text"])
        results.append(brain.process(s["text"]))

    return {"results": results, "events": recorder.events}


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text(A_PY, encoding="utf-8")
    (tmp_path / "s.py").write_text("print('sandbox')\n", encoding="utf-8")
    (tmp_path / "m.py").write_text("import numpy\n", encoding="utf-8")
    (tmp_path / "notas.txt").write_text("hola\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_golden(project):
    # Ida y vuelta por JSON: así las tuplas quedan como listas, igual que en el archivo.
    actual = json.loads(json.dumps(
        {name: run_case(name, steps, project) for name, steps in CASES.items()},
        ensure_ascii=False
    ))

    if os.environ.get("ASIA_UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert sorted(actual) == sorted(expected)

    for name in CASES:
        assert actual[name] == expected[name], name


def test_golden_tiene_un_caso_por_accion_de_la_lista_del_intentengine():
    """Ninguna acción que el IntentEngine puede devolver queda sin caracterizar."""
    from core.intent_engine import IntentEngine
    import inspect, re

    source = inspect.getsource(IntentEngine.detect)
    listed = re.search(r"Acciones disponibles:\n(.*?)\n\nFormato", source, re.DOTALL).group(1)
    actions = {a.strip().strip(",") for a in listed.split("\n") if a.strip()}
    covered = {s["intent"]["action"] for steps in CASES.values() for s in steps if s["intent"]}

    assert actions - covered == set()
