"""Atajos sin IntentEngine para órdenes inequívocas."""
import sys
from pathlib import Path

import pytest

from core.fixed_intents import fixed_intent

sys.path.insert(0, str(Path(__file__).parent / "manual"))
from check_intents import EXPECTED, FIXED_CASES, MESSAGES  # noqa: E402


@pytest.mark.parametrize(
    "text, name",
    [
        ("abre el bloc de notas", "bloc de notas"),
        ("Abre Chrome", "chrome"),
        ("abrir spotify", "spotify"),
        ("ábreme la calculadora", "calculadora"),
        ("abre notepad++", "notepad++"),
        ("abre whatsapp.", "whatsapp"),
        ("abre visual studio code", "visual studio code"),
    ],
)
def test_abre_x(text, name):
    assert fixed_intent(text) == {"action": "open_app", "params": {"app_name": name}}


@pytest.mark.parametrize(
    "text",
    [
        "abre el archivo notas",
        "abre la carpeta pruebas",
        "abre core/brain.py",
        "abre a.py",
        "abre @a.py",
        "abre chrome y busca gatos",
        "abre chrome en incógnito",
        "abre la página de google",
        "abre google.com",
        "abre una ventana nueva de chrome con mi correo",
        "abre el proyecto",
        "abre",
        "por favor abre chrome",
        "abre esto <<",
    ],
)
def test_ante_la_duda_intent_engine(text):
    assert fixed_intent(text) is None


@pytest.mark.parametrize(
    "text, action",
    [
        ("muestra el proyecto activo", "show_active_project"),
        ("¿Qué proyecto está activo?", "show_active_project"),
        ("proyecto activo", "show_active_project"),
        ("qué provider estás usando?", "show_settings"),
        ("muestra la configuración", "show_settings"),
        ("prueba el cambio pendiente", "run_sandbox"),
    ],
)
def test_consultas_fijas(text, action):
    assert fixed_intent(text) == {"action": action, "params": {}}


@pytest.mark.parametrize("text", ["muestra el proyecto activo y su resumen", "cambia el proyecto activo a pt"])
def test_consultas_parecidas_van_al_intent_engine(text):
    assert fixed_intent(text) is None


def test_misma_accion_que_check_intents():
    expected = dict(zip(MESSAGES, EXPECTED)) | FIXED_CASES

    for message, action in expected.items():
        fixed = fixed_intent(message)

        if fixed:
            assert fixed["action"] == action, message


def test_brain_usa_el_atajo_sin_intent_engine(monkeypatch):
    from core.brain import Brain

    brain = Brain.__new__(Brain)
    calls = []
    brain.intent_engine = type("I", (), {"detect": lambda self, t: calls.append(t) or {"action": "chat"}})()
    brain.settings = type("S", (), {"get": lambda self, k, d=None: {"active_project": "asia"}.get(k, d)})()
    monkeypatch.setattr(Brain, "app_names", lambda self: [])

    assert brain.process("muestra el proyecto activo") == "Proyecto activo: asia"
    assert calls == []


@pytest.mark.parametrize(
    "text, question",
    [
        ("busca en la biblioteca cómo se crea un nodo en ROS 2", "cómo se crea un nodo en ROS 2"),
        ("Oye Asia, busca en mis fuentes qué es un launch file.", "qué es un launch file"),
        ("busca cómo se configura Gazebo en la documentación", "cómo se configura Gazebo"),
        ("búscame en la biblioteca, ¿cómo se lanza un nodo?", "cómo se lanza un nodo"),
        ("¿puedes buscar en Wikipedia quién pintó la Mona Lisa?", "quién pintó la Mona Lisa en wikipedia"),
        ("busca en la documentación de ROS 2 cómo se crea un nodo", "cómo se crea un nodo en ROS 2"),
        ("consulta en la documentación que te di cómo uso rclpy?", "cómo uso rclpy"),
    ],
)
def test_busca_en_la_biblioteca(text, question):
    assert fixed_intent(text) == {"action": "search_project_rag", "params": {"question": question}}


@pytest.mark.parametrize(
    "text",
    ["busca la palabra Ollama en el proyecto", "busca en la biblioteca", "busca TODO en core",
     "qué hay en la biblioteca", "busca en la biblioteca\ny esto"],
)
def test_lo_que_no_es_buscar_en_la_biblioteca(text):
    fixed = fixed_intent(text)
    assert fixed is None or fixed["action"] != "search_project_rag"


def test_brain_manda_la_biblioteca_a_buscar_sin_intent_engine(monkeypatch):
    from core.brain import Brain

    brain = Brain.__new__(Brain)
    calls, searched = [], []
    brain.intent_engine = type("I", (), {"detect": lambda self, t: calls.append(t) or {"action": "search_text"}})()
    brain.settings = type("S", (), {"get": lambda self, k, d=None: d})()
    monkeypatch.setattr(Brain, "app_names", lambda self: [])
    monkeypatch.setattr(Brain, "handle_search_project_rag", lambda self, text, params: searched.append(params) or "ok")

    assert brain.process("busca en wikipedia qué es un grafo bipartito") == "ok"
    assert searched == [{"question": "qué es un grafo bipartito en wikipedia"}] and calls == []


@pytest.mark.parametrize(
    "text, path",
    [("Revisa el archivo core/timing.py.", "core/timing.py"), ("revisa timing.py", "timing.py"),
     ("Oye Asia, revisa launcher.py", "launcher.py"), ("revísame el archivo docs/DEMO.md", "docs/DEMO.md")],
)
def test_revisa_el_archivo(text, path):
    assert fixed_intent(text) == {"action": "review_file", "params": {"file_path": path}}


@pytest.mark.parametrize(
    "text", ["revisa a fondo moda.py", "revisa la carpeta pruebas", "revisa core/brain.py y luego explícalo",
             "revisa el proyecto"],
)
def test_otras_revisiones_van_al_intent_engine(text):
    assert fixed_intent(text) is None
