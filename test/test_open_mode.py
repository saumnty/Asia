"""Modo abierto: lo que entra al prompt sale sin pedir autorización.

launcher -> Brain -> ProviderRouter reales con proveedores simulados (ver
test_confidencial.py).
"""
import json

import pytest

import launcher
from config.settings_manager import SettingsManager, read_json
from core import paths
from core.confidential import OutgoingRequest, check, current_mode
from core.paths import DEFAULTS_FILE, SETTINGS_FILE
from core.provenance import ADJUNTO, EMOCIONAL, USUARIO, Fragment, request_sources
from test_confidencial import FILE_SECRET, TTY, gemini_text, interactive, make_brain

TYPED_PATH = r"C:\Users\alguien\proyecto\secreto.py"


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    from core.session import Session

    monkeypatch.setattr(Session, "user_cwd", tmp_path)
    (tmp_path / "datos.py").write_text(f"x = '{FILE_SECRET}'\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def settings_untouched():
    before = SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None
    yield
    assert (SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None) == before


@pytest.fixture
def gemini_default():
    SettingsManager.set_overrides({"default_provider": "gemini"})


def received(brain):
    return brain.provider_router.providers["gemini"].received


def test_open_mode_default_es_false():
    assert read_json(DEFAULTS_FILE)["open_mode_default"] is False


def test_adjunto_llega_al_proveedor_externo(cwd, capsys, settings_untouched, gemini_default):
    brain = make_brain()

    out = interactive(brain, ["/modo abierto", "explica @datos.py", "salir"], capsys)

    assert len(received(brain)) == 1
    text = gemini_text(brain)
    # El adjunto, la memoria y nada de avisos de modo confidencial.
    assert FILE_SECRET in text and "Santiago" in text
    assert "No envié esto" not in out


def test_aviso_una_sola_vez_con_lo_que_sale(cwd, capsys, gemini_default):
    brain = make_brain()

    out = interactive(brain, ["modo abierto", "hola", "modo abierto", "salir"], capsys)

    assert out.count("Modo abierto (solo en esta sesión)") == 1
    for kind in ("archivos", "adjuntos", "RAG", "proyecto", "memoria", "historial", "costo", "latencia"):
        assert kind in out
    assert "Ya estás en modo abierto" in out


def test_rutas_sin_reemplazar_solo_en_modo_abierto(cwd, capsys, gemini_default):
    normal = make_brain()
    interactive(normal, [f"qué opinas de {TYPED_PATH}", "salir"], capsys)
    assert TYPED_PATH not in gemini_text(normal) and "secreto.py" in gemini_text(normal)

    opened = make_brain()
    interactive(opened, ["modo abierto", f"qué opinas de {TYPED_PATH}", "salir"], capsys)
    assert TYPED_PATH in gemini_text(opened)


def test_historial_local_sale_en_modo_abierto(cwd, capsys, gemini_default):
    brain = make_brain()

    # El primer turno (con adjunto) lo responde el modelo local y queda en el
    # historial como local (sin el contenido del adjunto, como siempre).
    interactive(brain, ["explica @datos.py", "modo abierto", "y en una frase?", "salir"], capsys)

    [messages] = received(brain)
    contents = [m["content"] for m in messages]
    assert any("datos.py" in c and c.startswith("explica") for c in contents)
    assert any("respuesta de ollama" in c for c in contents)


@pytest.mark.parametrize("policy", ["block", "redact"])
def test_secreto_sigue_sin_salir(cwd, capsys, policy):
    SettingsManager.set_overrides({"default_provider": "gemini", "external_secret_policy": policy})
    brain = make_brain()
    key = "AIza" + "W" * 35

    out = interactive(brain, ["modo abierto", f"mi clave es {key}", "salir"], capsys)

    assert key not in gemini_text(brain)

    if policy == "block":
        assert received(brain) == []
        assert "contiene secretos (clave de Google/Gemini)" in out
    else:
        assert "[SECRETO REDACTADO: clave de Google/Gemini]" in gemini_text(brain)


def test_emocional_no_sale_ni_en_modo_abierto(cwd, capsys, gemini_default):
    brain = make_brain()
    router = brain.provider_router
    interactive(brain, ["modo abierto", "salir"], capsys)

    # Un turno emocional: lo responde el modelo local.
    with request_sources(Fragment(EMOCIONAL, "hoy me siento muy triste")):
        answer = router.chat("hoy me siento muy triste")

    assert received(brain) == []
    assert "nunca sale" in answer and "respuesta de ollama" in answer

    # Y en el historial no sale en el siguiente mensaje.
    with request_sources(Fragment(USUARIO, "hola")):
        router.chat("hola")

    assert len(received(brain)) == 1
    assert "triste" not in gemini_text(brain)


def test_check_en_modo_abierto():
    settings = {"confidential_mode": "abierto"}
    get = type("S", (), {"get": lambda self, k, d=None: settings.get(k, d)})()

    def request(*fragments):
        return OutgoingRequest([{"role": "user", "content": "x"}], list(fragments))

    assert check(request(Fragment(ADJUNTO, "a")), get).allowed
    assert not check(request(Fragment(EMOCIONAL, "a")), get).allowed


def test_no_persiste_entre_sesiones(cwd, capsys, settings_untouched):
    brain = make_brain()
    launcher.main(["--provider", "gemini", "modo abierto"], stdin=TTY, brain_factory=lambda: brain)
    assert current_mode(SettingsManager()) == "abierto"

    # Una ejecución nueva vuelve a empezar con los valores de sesión vacíos.
    other = make_brain()
    out = launcher.main(["--provider", "gemini", "explica", "@datos.py"], stdin=TTY, brain_factory=lambda: other)

    assert out is None
    assert current_mode(SettingsManager()) == "normal"
    assert received(other) == []
    assert "confidential_mode" not in read_json(SETTINGS_FILE)


def test_bitacora_registra_los_envios(cwd, capsys, gemini_default):
    brain = make_brain()

    interactive(brain, ["modo abierto", "explica @datos.py", "salir"], capsys)

    entries = [json.loads(l) for l in paths.EXTERNAL_AUDIT_FILE.read_text(encoding="utf-8").splitlines()]
    [entry] = entries
    assert entry["autorizacion"] == "modo abierto"
    assert "adjunto" in entry["tipos"] and "memoria" in entry["tipos"]
    assert FILE_SECRET not in paths.EXTERNAL_AUDIT_FILE.read_text(encoding="utf-8")


def test_el_prompt_muestra_el_modo(cwd, capsys):
    brain = make_brain()
    prompts = []
    lines = iter(["modo abierto", "modo local", "modo normal", "salir"])

    def read(prompt):
        prompts.append(prompt)
        return next(lines)

    launcher.interactive_mode(brain, read=read)

    assert prompts == ["\nTú: ", "\nTú [abierto]: ", "\nTú [local]: ", "\nTú: "]


def test_open_mode_default_true_y_modo_normal_lo_quita(cwd, capsys):
    SettingsManager.set_overrides({"default_provider": "gemini", "open_mode_default": True})
    brain = make_brain()

    interactive(brain, ["explica @datos.py", "modo normal", "explica @datos.py", "salir"], capsys)

    assert len(received(brain)) == 1
