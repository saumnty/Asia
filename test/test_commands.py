"""Comandos de sesión con "/": una tabla para /opciones, --help y el despacho."""
import pytest

import launcher
from config.settings_manager import SettingsManager
from core.commands import COMMANDS, GROUPS, options_text, resolve
from core.confidential import current_mode
from core.paths import SETTINGS_FILE
from core.session import Session
from test_confidencial import TTY, interactive, make_brain


@pytest.fixture
def settings_untouched():
    before = SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None
    yield
    assert (SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None) == before


# --- La tabla ------------------------------------------------------------------------

def test_grupos_pedidos():
    for group in ("modos", "modelos", "archivos y adjuntos", "confidencialidad", "tiempos", "salir"):
        assert group in GROUPS


def test_cada_comando_tiene_ejemplo_y_empieza_con_barra():
    for command in COMMANDS:
        assert command.example
        assert command.syntax or command.slash.startswith("/")


def test_opciones_lista_todo_por_grupos():
    text = options_text()

    for group in GROUPS:
        assert f"\n{group}:" in text

    for command in COMMANDS:
        assert command.slash in text and command.example in text


def test_help_sale_de_la_misma_tabla(capsys):
    with pytest.raises(SystemExit):
        launcher.build_parser().parse_args(["--help"])

    out = capsys.readouterr().out
    assert options_text() in out.replace("\r\n", "\n")


@pytest.mark.parametrize(
    "text, phrase",
    [
        ("/modo local", "modo local"),
        ("/MODO Abierto", "modo abierto"),
        ("/modelo", "que modelo estas usando"),
        ("/modelo normal", "vuelve al modelo normal"),
        ("/modelo matemáticas", "usa el modelo matemáticas"),
        ("/modelo Qwen3:4B", "usa el modelo Qwen3:4B"),
        ("/confirmar envío", "confirmar envio"),
        ("/confirmar envio", "confirmar envio"),
        ("/tiempos", "muestra tiempos"),
        ("/sin tiempos", "oculta tiempos"),
        ("/confirmar ejecución", "confirmar ejecucion"),
    ],
)
def test_resolve(text, phrase):
    assert resolve(text).phrase == phrase


@pytest.mark.parametrize("text", ["hola", "/home/santy/a.py explica", "/tmp/x", "explica /modo local", "/a\n/b"])
def test_no_es_comando(text):
    assert resolve(text) is None


def test_comando_desconocido():
    assert resolve("/nada").unknown == "/nada"


# --- De punta a punta ----------------------------------------------------------------

@pytest.mark.parametrize(
    "lines, mode",
    [
        (["/modo local"], "local"),
        (["modo local"], "local"),
        (["/modo abierto"], "abierto"),
        (["/modo abierto", "/modo normal"], "normal"),
        (["modo abierto", "modo normal"], "normal"),
    ],
)
def test_modos_con_barra_y_con_frase(capsys, lines, mode):
    brain = make_brain()

    interactive(brain, [*lines, "salir"], capsys)

    assert current_mode(SettingsManager()) == mode


def test_modelo_con_barra_y_alias(capsys, monkeypatch, settings_untouched):
    brain = make_brain()
    monkeypatch.setattr(type(brain), "installed", lambda self: ["qwen3:4b", "qwen2.5-coder:7b"])

    out = interactive(brain, ["/modelo qwen3:4b", "/modelo", "/modelo normal", "usa el modelo de matemáticas", "salir"], capsys)

    assert "Uso qwen3:4b en el chat y en las acciones" in out
    assert "Fijado en esta sesión: qwen3:4b" in out
    assert "Vuelvo al modelo normal." in out
    assert SettingsManager.overrides.get("forced_domain") == "math"


def test_proveedor_con_barra_va_directo_a_la_accion(capsys, settings_untouched):
    brain = make_brain()

    out = interactive(brain, ["/proveedor gemini", "salir"], capsys)

    assert "Provider cambiado a: gemini (solo en esta sesión)" in out
    assert SettingsManager.overrides["default_provider"] == "gemini"


def test_opciones_y_desconocido_no_llaman_al_modelo(capsys):
    brain = make_brain()

    out = interactive(brain, ["/opciones", "/nada", "salir"], capsys)

    assert "Comandos de sesión" in out and "/modo abierto" in out
    assert "No conozco el comando /nada. Escribe /opciones" in out
    assert all(p.received == [] for p in brain.provider_router.providers.values())


@pytest.mark.parametrize("command", ["/salir", "salir", "exit", "quit", "/SALIR"])
def test_salir(capsys, command):
    brain = make_brain()

    out = interactive(brain, [command, "hola"], capsys)

    assert out.rstrip().endswith("Asia apagada.")
    assert brain.provider_router.providers["ollama"].received == []


@pytest.mark.parametrize("command", ["/carpeta", "cwd", "donde estoy"])
def test_carpeta(capsys, tmp_path, monkeypatch, command):
    monkeypatch.setattr(Session, "user_cwd", tmp_path)

    out = interactive(make_brain(), [command, "salir"], capsys)
    assert f"Carpeta desde donde llamaste a Asia: {tmp_path}" in out

    launcher.main([command], stdin=TTY, brain_factory=make_brain)
    assert f"Carpeta desde donde llamaste a Asia: {tmp_path}" in capsys.readouterr().out


def test_mensaje_de_arranque(capsys):
    out = interactive(make_brain(), ["salir"], capsys)

    first = out.splitlines()[:3]
    assert first[0] == "Asia iniciada"
    assert first[1].startswith("Modelo: ollama/") and first[1].endswith("· modo normal")
    assert first[2] == "Escribe /opciones para ver los comandos."


def test_mensaje_de_arranque_con_gemini_y_modo_abierto(capsys):
    SettingsManager.set_overrides({"default_provider": "gemini", "gemini_model": "gemini-x", "open_mode_default": True})

    out = interactive(make_brain(), ["salir"], capsys)

    assert "Modelo: gemini/gemini-x · modo abierto" in out
