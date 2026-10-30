"""Paso 6 de la fase G: los casos del modo confidencial de punta a punta.

launcher -> Brain -> ProviderRouter reales, con los ajustes de sesión de
verdad (SettingsManager) y un proveedor externo simulado que registra todo
lo que recibe. Ollama también es simulado.
"""
import json
from types import SimpleNamespace

import pytest

import launcher
from config.settings_manager import SettingsManager
from core import paths
from core.brain import Brain
from core.model_selection import StickyModel
from core.paths import SETTINGS_FILE
from core.session import Session
from providers.provider_router import ProviderRouter

FILE_SECRET = "CONTENIDO_PRIVADO_DEL_ARCHIVO"


class FakeProvider:
    def __init__(self, name, fail=None):
        self.name = name
        self.fail = fail
        self.received = []

    def complete(self, messages, on_chunk=None, review=False, model=None, think=False, max_tokens=None):
        if self.fail:
            raise self.fail

        self.received.append(messages)
        answer = f"respuesta de {self.name}"

        # Con stream_output (settings.json real) la respuesta va por on_chunk.
        if on_chunk:
            on_chunk(answer)

        return answer


class ChatIntent:
    def detect(self, text):
        return {"action": "chat", "params": {}}


def make_brain(ollama_fail=None):
    router = ProviderRouter.__new__(ProviderRouter)
    router.settings = SettingsManager()
    router.memory = SimpleNamespace(load=lambda: {"nombre": "Santiago"})
    router.project_memory = SimpleNamespace(load_project_summary=lambda name: "")
    router.providers = {"gemini": FakeProvider("gemini"), "ollama": FakeProvider("ollama", ollama_fail)}
    router.history, router.history_labels = [], []
    router.last_fragments = router.last_request = router.pending_authorization = None
    router.confirm, router.allow_all_this_run = None, False
    router.sticky_model = StickyModel()

    brain = Brain.__new__(Brain)
    brain.intent_engine = ChatIntent()
    brain.settings = SettingsManager()
    brain.provider_router = router
    return brain


def gemini_text(brain):
    return "\n".join(m["content"] for msgs in brain.provider_router.providers["gemini"].received for m in msgs)


TTY = SimpleNamespace(isatty=lambda: True)


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(Session, "user_cwd", tmp_path)
    (tmp_path / "datos.py").write_text(f"x = '{FILE_SECRET}'\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def settings_untouched():
    before = SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None
    yield
    assert (SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None) == before


def run(argv, brain, capsys):
    launcher.main(argv, stdin=TTY, brain_factory=lambda: brain)
    return capsys.readouterr().out


def interactive(brain, lines, capsys):
    lines = iter(lines)

    def read(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    launcher.interactive_mode(brain, read=read)
    return capsys.readouterr().out


# (a) Un prompt con un archivo adjunto no llega al proveedor externo.
def test_a_adjunto_no_llega_al_proveedor_externo(cwd, capsys, settings_untouched):
    brain = make_brain()

    out = run(["--provider", "gemini", "explica", "@datos.py"], brain, capsys)

    assert brain.provider_router.providers["gemini"].received == []
    assert "[Modo confidencial] No envié esto a gemini: lleva contenido local (adjunto:" in out
    assert "respuesta de ollama" in out


# (b) El fallback no filtra contenido local.
def test_b_fallback_no_filtra_contenido_local(cwd, capsys, settings_untouched):
    SettingsManager.set_overrides({"fallback_provider": "gemini"})
    brain = make_brain(ollama_fail=ConnectionError("Ollama apagado"))

    out = interactive(brain, ["explica @datos.py", "salir"], capsys)

    assert brain.provider_router.providers["gemini"].received == []
    assert "Falló ollama (Ollama apagado) y no usé el fallback gemini: lleva contenido local" in out
    assert "No salió nada de esta máquina." in out


# (c) La autorización de una vez no persiste.
def test_c_autorizacion_de_una_vez_no_persiste(cwd, capsys, settings_untouched):
    SettingsManager.set_overrides({"default_provider": "gemini"})
    brain = make_brain()

    out = interactive(brain, [
        "explica @datos.py", "envía esto a Gemini", "confirmar envío",
        "explica @datos.py", "confirmar envío", "salir",
    ], capsys)

    received = brain.provider_router.providers["gemini"].received
    assert len(received) == 1 and FILE_SECRET in gemini_text(brain)
    assert "Saldría a gemini: adjunto:" in out
    assert out.count("No envié esto a gemini") == 2
    assert "No hay ningún envío por confirmar" in out
    # Nada de la autorización queda en la configuración de la sesión ni en disco.
    assert "allow_external" not in SettingsManager.overrides

    # Una sesión nueva tampoco lo hereda.
    other = make_brain()
    interactive(other, ["explica @datos.py", "salir"], capsys)
    assert other.provider_router.providers["gemini"].received == []


# (d) Un secreto en el texto se bloquea (o se redacta, según la política).
@pytest.mark.parametrize("policy", ["block", "redact"])
def test_d_secreto_en_el_texto(cwd, capsys, settings_untouched, policy):
    SettingsManager.set_overrides({"default_provider": "gemini", "external_secret_policy": policy})
    brain = make_brain()
    key = "AIza" + "Q" * 35

    out = interactive(brain, [f"por qué no funciona mi clave {key}", "salir"], capsys)

    assert key not in gemini_text(brain)

    if policy == "block":
        assert brain.provider_router.providers["gemini"].received == []
        assert "contiene secretos (clave de Google/Gemini)" in out
    else:
        assert "[SECRETO REDACTADO: clave de Google/Gemini]" in gemini_text(brain)
        assert "Redacté antes de enviar a gemini" in out


# (e) La bitácora no contiene texto.
def test_e_bitacora_sin_texto(cwd, capsys, settings_untouched):
    SettingsManager.set_overrides({"default_provider": "gemini"})
    brain = make_brain()
    typed = "PALABRA_TECLEADA_QUE_NO_DEBE_QUEDAR"

    out = interactive(brain, [
        typed, "explica @datos.py", "envía esto a Gemini", "confirmar envío",
        "qué has enviado afuera", "salir",
    ], capsys)

    log = paths.EXTERNAL_AUDIT_FILE.read_text(encoding="utf-8")
    entries = [json.loads(line) for line in log.splitlines()]
    assert [e["autorizacion"] for e in entries] == ["exportable", "una vez"]
    assert typed not in log and FILE_SECRET not in log and "Santiago" not in log
    assert "Últimos 2 envíos externos" in out


# (f) En modo local nada sale.
def test_f_modo_local_nada_sale(cwd, capsys, settings_untouched):
    SettingsManager.set_overrides({"default_provider": "gemini"})
    brain = make_brain()

    out = interactive(brain, [
        "modo local", "hola, solo texto", "explica @datos.py", "envía esto a Gemini", "salir",
    ], capsys)

    assert brain.provider_router.providers["gemini"].received == []
    assert out.count("estás en modo local") == 2
    assert "Estás en modo local: no envío nada afuera." in out
    assert not paths.EXTERNAL_AUDIT_FILE.exists()
