import hashlib

import pytest

import core.actions.models as models
import launcher
from config.settings_manager import SettingsManager
from core.actions.models import model_command
from core.brain import Brain
from core.model_selection import StickyModel
from core.paths import SETTINGS_FILE

INSTALLED = ["qwen2.5-coder:7b", "qwen3:4b", "nomic-embed-text:latest"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("¿Qué modelo estás usando?", ("show", None)),
        ("que modelo usas", ("show", None)),
        ("cuál es tu modelo", ("show", None)),
        ("modelo actual", ("show", None)),
        ("Usa el modelo de matemáticas", ("domain", "math")),
        ("usa el modelo para código", ("domain", "code")),
        ("cambia al modelo general", ("domain", "general")),
        ("pasa al modelo qwen3:4b", ("name", "qwen3:4b")),
        ("usa el modelo qwen3:4b", ("name", "qwen3:4b")),
        ("usa el modelo Qwen2.5-Coder:7b", ("name", "Qwen2.5-Coder:7b")),
        ("vuelve al modelo normal", ("reset", None)),
        ("Regresa al modelo por defecto.", ("reset", None)),
    ],
)
def test_comandos_reconocidos(text, expected):
    assert model_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "qué modelo de auto me recomiendas",
        "usa el modelo MVC en mi proyecto",
        "explica el modelo de datos de core/brain.py",
        "usa el modelo de matemáticas para resolver 2 + 2",
    ],
)
def test_otras_frases_no_son_comandos(text):
    assert model_command(text) is None


class NoIntentEngine:
    def detect(self, text):
        raise AssertionError(f"el IntentEngine recibió {text!r}")


class FakeRouter:
    def __init__(self):
        self.sticky_model = StickyModel()


@pytest.fixture
def brain(monkeypatch):
    monkeypatch.setattr(models, "installed_models", lambda host=None: list(INSTALLED))
    b = Brain.__new__(Brain)
    b.intent_engine = NoIntentEngine()
    b.settings = SettingsManager()
    b.provider_router = FakeRouter()
    before = SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None
    yield b
    # Nada se escribe en settings.json: los cambios son de la sesión.
    assert (SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None) == before


def test_mostrar_modelos(brain):
    message = brain.process("¿qué modelo estás usando?")

    assert message.startswith("Chat: qwen2.5-coder:7b (dominio general).")
    assert "Acciones de código: qwen2.5-coder:7b." in message
    assert "Detección de intención: qwen2.5-coder:7b." in message
    assert "matemáticas = qwen3:4b" in message


def test_usar_el_modelo_de_matematicas_dura_la_sesion(brain):
    message = brain.process("usa el modelo de matemáticas")

    assert message.startswith("Uso el modelo de matemáticas (qwen3:4b) en el chat")
    assert SettingsManager.overrides == {"forced_domain": "math"}
    assert brain.process("qué modelo usas").startswith("Chat: qwen3:4b (dominio matemáticas con razonamiento).")

    # El chat queda en math aunque el mensaje sea de charla.
    sticky = StickyModel()
    assert sticky.choose("hola", SettingsManager()) == "qwen3:4b" and sticky.domain == "math"


def test_volver_al_modelo_normal(brain):
    brain.process("usa el modelo de matemáticas")
    SettingsManager.set_overrides({**SettingsManager.overrides, "stream_output": False})

    message = brain.process("vuelve al modelo normal")

    assert message.startswith("Vuelvo al modelo normal.")
    # Solo se quitan los valores de modelo; los demás flags de la sesión siguen.
    assert SettingsManager.overrides == {"stream_output": False}


def test_fijar_un_modelo_por_nombre(brain):
    brain.process("usa el modelo qwen3:4b")

    assert SettingsManager.overrides == {"forced_model": "qwen3:4b"}
    assert "Fijado en esta sesión: qwen3:4b (para todo)." in brain.process("modelo actual")


@pytest.mark.parametrize(
    "text, missing",
    [
        ("usa el modelo llama3.2:3b", "llama3.2:3b"),
        ("usa el modelo de matemáticas", "deepseek-r1:7b"),
    ],
)
def test_modelo_no_descargado_dice_cual_falta(brain, text, missing):
    SettingsManager.set_overrides({"models_by_domain": {"math": "deepseek-r1:7b"}})

    message = brain.process(text)

    assert message.startswith(f"El modelo {missing} no está descargado en Ollama")
    assert "qwen2.5-coder:7b, qwen3:4b" in message and f"ollama pull {missing}" in message
    assert "forced_model" not in SettingsManager.overrides and "forced_domain" not in SettingsManager.overrides


def test_sin_ollama_no_se_puede_comprobar_y_se_acepta(brain, monkeypatch):
    monkeypatch.setattr(models, "installed_models", lambda host=None: None)

    brain.process("usa el modelo qwen3:4b")

    assert SettingsManager.overrides == {"forced_model": "qwen3:4b"}


def test_help_documenta_model_y_los_comandos(capsys):
    with pytest.raises(SystemExit):
        launcher.build_parser().parse_args(["--help"])

    out = capsys.readouterr().out
    assert "--model NOMBRE" in out and "debe estar descargado" in out
    for command in ["¿qué modelo estás usando?", "usa el modelo de matemáticas", "vuelve al modelo normal"]:
        assert command in out
    assert "dura solo la sesión" in out
