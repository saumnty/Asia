import io

import pytest

import launcher
from core.brain import SHORTCUT_ACTIONS, Brain
from tools.sandbox import PendingRun


class NoIntentEngine:
    """Falla si se consulta: los atajos no deben pasar por el IntentEngine."""

    def detect(self, text):
        raise AssertionError(f"el IntentEngine recibió {text!r}")


class FakeApplyTool:
    def apply_pending_change(self):
        return "<aplicado>"

    def cancel_pending_change(self):
        return "<cancelado>"

    def show_pending_change(self):
        return "<pendiente>"


class FakeToolRegistry:
    def get_apply_changes_tool(self):
        return FakeApplyTool()


def make_brain(tmp_path, intent_engine=None):
    brain = Brain.__new__(Brain)
    brain.intent_engine = intent_engine or NoIntentEngine()
    brain.tool_registry = FakeToolRegistry()
    brain.pending_run = PendingRun(tmp_path / "pending_run.json")
    return brain


EXPECTED = {"apply_change": "<aplicado>", "cancel_change": "<cancelado>", "show_pending_change": "<pendiente>"}


@pytest.mark.parametrize("phrase, action", sorted(SHORTCUT_ACTIONS.items()))
def test_cada_atajo_va_a_su_accion_sin_intentengine(tmp_path, phrase, action):
    assert make_brain(tmp_path).process(phrase) == EXPECTED[action]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Confirmar cambio", "<aplicado>"),
        ("  confirmar   cambio. ", "<aplicado>"),
        ("¡Cancelar cambio!", "<cancelado>"),
        ("MUESTRA EL CAMBIO PENDIENTE", "<pendiente>"),
        ("confirmar ejecución", "No hay ninguna ejecución pendiente."),
        ("cancelar ejecucion", "No hay ninguna ejecución pendiente."),
    ],
)
def test_mayusculas_espacios_y_puntuacion(tmp_path, text, expected):
    assert make_brain(tmp_path).process(text) == expected


class RecordingIntentEngine:
    def __init__(self):
        self.texts = []

    def detect(self, text):
        self.texts.append(text)
        return {"action": "chat", "params": {}}


@pytest.mark.parametrize(
    "text",
    ["confirmar cambio por favor", "no confirmar cambio", "qué es un cambio pendiente", "salir"],
)
def test_frases_que_no_son_exactas_van_al_intentengine(tmp_path, text):
    engine = RecordingIntentEngine()

    assert make_brain(tmp_path, engine).process(text) is None
    assert engine.texts == [text]


@pytest.mark.parametrize("word", ["salir", "Salir", "exit", "quit "])
def test_jarvis_salir_no_crea_brain(word, capsys):
    def no_brain():
        raise AssertionError("no debía crearse Brain")

    stdin = io.TextIOWrapper(io.BytesIO())
    stdin.isatty = lambda: True

    assert launcher.main([word], stdin=stdin, brain_factory=no_brain) is None
    assert capsys.readouterr().out == "Asia apagada.\n"
