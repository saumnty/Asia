"""Paso 3 de la fase G: política del router hacia proveedores externos."""
from types import SimpleNamespace

import pytest

import launcher
from config.settings_manager import SettingsManager, read_json
from core.actions.confidential import confidential_command
from core.brain import Brain
from core.confidential import OutgoingRequest, check, is_external, redact_paths
from core.intent_engine import IntentEngine
from core.model_selection import StickyModel
from core.paths import DEFAULTS_FILE, SETTINGS_FILE
from core.provenance import (
    ADJUNTO,
    ARCHIVO,
    EMOCIONAL,
    MEMORIA,
    USUARIO,
    Fragment,
    request_sources,
)
from core.rag.embedder import ExternalEmbeddingBlocked, OllamaEmbedder
from providers.provider_router import ProviderRouter


class Settings:
    def __init__(self, **values):
        self.values = {"ollama_host": "http://localhost:11434", **values}

    def get(self, key, default=None):
        return self.values.get(key, default)


# --- Qué es externo --------------------------------------------------------------

@pytest.mark.parametrize(
    "host, trusted, external",
    [
        ("http://localhost:11434", [], False),
        ("http://127.0.0.1:11434", [], False),
        ("http://[::1]:11434", [], False),
        ("http://192.168.1.50:11434", [], True),
        ("http://jetson.tailnet.ts.net:11434", [], True),
        ("http://jetson.tailnet.ts.net:11434", ["jetson.tailnet.ts.net"], False),
    ],
)
def test_ollama_externo_segun_el_host(host, trusted, external):
    settings = Settings(ollama_host=host, trusted_local_hosts=trusted)

    assert is_external("ollama", settings) is external
    assert is_external("gemini", settings) is True


def test_trusted_local_hosts_vacio_por_defecto():
    assert read_json(DEFAULTS_FILE)["trusted_local_hosts"] == []


@pytest.mark.parametrize(
    "text, expected",
    [
        (r"revisa C:\Users\santy\Downloads\practica6\moda.py ya", "revisa moda.py ya"),
        (r'explica "C:\Users\santy\Mis cosas\a b.py"', 'explica "a b.py"'),
        ("lee /home/santy/proyecto/main.py", "lee main.py"),
        ("la ruta relativa core/brain.py no cambia", "la ruta relativa core/brain.py no cambia"),
    ],
)
def test_rutas_absolutas_por_el_nombre_del_archivo(text, expected):
    assert redact_paths(text) == expected


# --- Decisión ------------------------------------------------------------------------

def request(*fragments):
    return OutgoingRequest([{"role": "user", "content": "x"}], list(fragments))


def test_check():
    settings = Settings()

    assert check(request(Fragment(USUARIO, "hola")), settings).allowed
    blocked = check(request(Fragment(USUARIO, "hola"), Fragment(ADJUNTO, "x = 1")), settings)
    assert not blocked.allowed and blocked.reason == "lleva contenido local (adjunto: 5 caracteres)"
    assert check(request(Fragment(ADJUNTO, "x = 1")), settings, authorized=True).allowed
    # Memoria: solo con external_allow_memory.
    assert not check(request(Fragment(MEMORIA, "nombre")), settings).allowed
    assert check(request(Fragment(MEMORIA, "nombre")), Settings(external_allow_memory=True)).allowed
    # Emocional: nunca, ni autorizado.
    assert not check(request(Fragment(EMOCIONAL, "triste")), settings, authorized=True).allowed
    # Modo local: ni lo tecleado.
    assert not check(request(Fragment(USUARIO, "hola")), Settings(confidential_mode="local")).allowed


# --- Router con proveedores simulados ---------------------------------------------

class FakeProvider:
    def __init__(self, fail=None):
        self.received = []
        self.fail = fail

    def complete(self, messages, on_chunk=None, review=False, model=None, think=False):
        if self.fail:
            raise self.fail

        self.received.append(messages)
        answer = f"respuesta de {self.name}"

        if on_chunk:
            on_chunk(answer)

        return answer


def make_router(primary="gemini", fallback="ollama", ollama_fail=None, memory=None, project="", **settings):
    router = ProviderRouter.__new__(ProviderRouter)
    router.settings = Settings(default_provider=primary, fallback_provider=fallback,
                               active_project="asia" if project else "", **settings)
    router.memory = SimpleNamespace(load=lambda: memory or {})
    router.project_memory = SimpleNamespace(load_project_summary=lambda name: project)
    gemini, ollama = FakeProvider(), FakeProvider(ollama_fail)
    gemini.name, ollama.name = "gemini", "ollama"
    router.providers = {"gemini": gemini, "ollama": ollama}
    router.history, router.history_labels = [], []
    router.last_fragments = router.last_request = router.pending_authorization = None
    router.confirm, router.allow_all_this_run = None, False
    router.sticky_model = StickyModel()
    return router


def sent_to_gemini(router):
    return "\n".join(m["content"] for msgs in router.providers["gemini"].received for m in msgs)


def test_contenido_local_no_sale_y_responde_el_modelo_local():
    router = make_router()

    with request_sources(Fragment(USUARIO, "explica"), Fragment(ARCHIVO, "SECRETO_DEL_ARCHIVO")):
        answer = router.ask("explica SECRETO_DEL_ARCHIVO")

    assert router.providers["gemini"].received == []
    assert answer.startswith("[Modo confidencial] No envié esto a gemini: lleva contenido local (archivo: 19 caracteres).")
    assert "Respondo con el modelo local (ollama)." in answer and answer.endswith("respuesta de ollama")
    assert '"envía esto a Gemini"' in answer


def test_lo_tecleado_si_sale_sin_rutas_ni_contexto_local():
    router = make_router(memory={"nombre": "Santiago"}, project="RESUMEN_DEL_PROYECTO")

    with request_sources(Fragment(USUARIO, "explica")):
        router.chat(r"qué hay en C:\Users\santy\proyecto\a.py?")

    sent = sent_to_gemini(router)
    assert "a.py" in sent and "santy" not in sent
    assert "Santiago" not in sent and "RESUMEN_DEL_PROYECTO" not in sent


def test_memoria_sale_solo_si_se_permite():
    router = make_router(memory={"nombre": "Santiago"}, external_allow_memory=True)

    with request_sources(Fragment(USUARIO, "hola")):
        router.chat("hola")

    assert "Santiago" in sent_to_gemini(router)


def test_historial_local_no_sale():
    router = make_router(primary="ollama", fallback=None)

    with request_sources(Fragment(USUARIO, "explica"), Fragment(ADJUNTO, "ADJUNTO_PRIVADO")):
        router.chat("explica ADJUNTO_PRIVADO", history_prompt="explica")

    router.settings.values["default_provider"] = "gemini"

    with request_sources(Fragment(USUARIO, "gracias")):
        router.chat("gracias")

    sent = sent_to_gemini(router)
    assert "gracias" in sent and "explica" not in sent and "respuesta de ollama" not in sent


def test_sin_modelo_local_lo_dice_y_no_cae_a_gemini():
    router = make_router(ollama_fail=ConnectionError("Ollama apagado"))

    with request_sources(Fragment(ADJUNTO, "x = 1")):
        answer = router.ask("explica x = 1")

    assert router.providers["gemini"].received == []
    assert "El modelo local (ollama) tampoco respondió: Ollama apagado" in answer
    assert "No se envió a ningún proveedor externo." in answer


def test_ollama_remoto_sin_local_lo_dice():
    router = make_router(primary="ollama", fallback=None, ollama_host="http://10.0.0.5:11434")

    with request_sources(Fragment(ADJUNTO, "x = 1")):
        answer = router.ask("explica x = 1")

    assert router.providers["ollama"].received == []
    assert "No hay un modelo local disponible (ollama_host apunta fuera de esta máquina)" in answer


def test_fallback_a_gemini_no_lleva_contenido_local():
    router = make_router(primary="ollama", fallback="gemini", ollama_fail=ConnectionError("caído"))

    with request_sources(Fragment(USUARIO, "explica"), Fragment(ADJUNTO, "x = 1")):
        answer = router.ask("explica x = 1")

    assert router.providers["gemini"].received == []
    assert answer == (
        "Falló ollama (caído) y no usé el fallback gemini: lleva contenido local "
        "(adjunto: 5 caracteres). No salió nada de esta máquina."
    )


def test_fallback_a_gemini_con_solo_lo_tecleado():
    router = make_router(primary="ollama", fallback="gemini", ollama_fail=ConnectionError("caído"))

    with request_sources(Fragment(USUARIO, "hola")):
        answer = router.chat("hola")

    assert answer.startswith("[Fallback: usando gemini]")
    assert router.providers["gemini"].received


# --- Autorización de una sola vez -----------------------------------------------------

def test_autorizacion_de_una_vez_muestra_tipos_y_caracteres_y_no_persiste():
    router = make_router()

    with request_sources(Fragment(USUARIO, "explica"), Fragment(ADJUNTO, "x = 1")):
        router.ask("explica x = 1")

    summary = router.prepare_authorization()

    assert summary.startswith("Saldría a gemini: adjunto: 5 caracteres, usuario: 7 caracteres")
    assert '"confirmar envío"' in summary and "no se guarda" in summary
    assert router.providers["gemini"].received == []

    assert router.send_authorized() == "respuesta de gemini"
    assert len(router.providers["gemini"].received) == 1
    # Se consumió: no se puede repetir ni vale para el siguiente mensaje.
    assert router.send_authorized().startswith("No hay ningún envío por confirmar")

    with request_sources(Fragment(ADJUNTO, "y = 2")):
        router.ask("explica y = 2")

    assert len(router.providers["gemini"].received) == 1


def test_cancelar_envio():
    router = make_router()

    with request_sources(Fragment(ADJUNTO, "x = 1")):
        router.ask("x = 1")

    router.prepare_authorization()

    assert router.cancel_authorization() == "Envío cancelado. No salió nada."
    assert router.send_authorized().startswith("No hay ningún envío por confirmar")


def test_emocional_nunca_ni_autorizado():
    router = make_router()

    with request_sources(Fragment(EMOCIONAL, "me siento mal")):
        router.ask("me siento mal")

    assert "nunca sale de esta máquina" in router.prepare_authorization()
    assert router.providers["gemini"].received == []


@pytest.mark.parametrize("answer, sent", [(True, 1), (False, 0), ("all", 2)])
def test_allow_external_confirma_cada_envio(answer, sent):
    router = make_router(allow_external=True)
    summaries = []
    router.confirm = lambda summary: summaries.append(summary) or answer

    for _ in range(2):
        with request_sources(Fragment(ADJUNTO, "x = 1")):
            router.ask("x = 1")

    assert len(router.providers["gemini"].received) == {True: 2, False: 0, "all": 2}[answer]
    # Con "todos" se pregunta una sola vez.
    assert len(summaries) == (1 if answer == "all" else 2)
    assert summaries[0].startswith("Saldría a gemini: adjunto: 5 caracteres")


def test_allow_external_no_es_el_valor_por_defecto():
    router = make_router()
    router.confirm = lambda summary: True

    with request_sources(Fragment(ADJUNTO, "x = 1")):
        router.ask("x = 1")

    assert router.providers["gemini"].received == []


# --- Comandos de sesión -------------------------------------------------------------

@pytest.mark.parametrize(
    "text, name",
    [("Envía esto a Gemini", "authorize"), ("confirmar envío", "confirm"), ("cancelar envío", "cancel"),
     ("modo local", "local"), ("Modo normal.", "normal"), ("envía esto a gemini por favor", None)],
)
def test_comandos_confidenciales(text, name):
    assert confidential_command(text) == name


class NoIntentEngine:
    def detect(self, text):
        raise AssertionError(f"el IntentEngine recibió {text!r}")


def make_brain(router):
    brain = Brain.__new__(Brain)
    brain.intent_engine = NoIntentEngine()
    brain.settings = SettingsManager()
    brain.provider_router = router
    return brain


def test_modo_local_y_modo_normal():
    router = make_router()
    router.settings = SettingsManager()
    SettingsManager.set_overrides({"default_provider": "gemini", "fallback_provider": "ollama"})
    brain = make_brain(router)

    assert brain.process("modo local").startswith("Modo local: no sale nada")

    with request_sources(Fragment(USUARIO, "hola")):
        answer = router.ask("hola")

    assert router.providers["gemini"].received == []
    assert "estás en modo local" in answer
    assert "modo local" in brain.process("envía esto a Gemini")

    assert brain.process("modo normal").startswith("Modo normal")

    with request_sources(Fragment(USUARIO, "hola")):
        router.ask("hola")

    assert len(router.providers["gemini"].received) == 1


def test_cambiar_provider_dura_la_sesion_y_no_escribe_settings():
    before = SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None
    brain = Brain.__new__(Brain)
    brain.settings = SettingsManager()
    brain.provider_router = SimpleNamespace(provider_factories=ProviderRouter.provider_factories)

    message = brain.handle_set_provider("cambia el provider a gemini", {"provider": "gemini"})

    assert message.startswith("Provider cambiado a: gemini (solo en esta sesión)")
    assert SettingsManager.overrides["default_provider"] == "gemini"
    assert (SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None) == before


# --- Ollama remoto: IntentEngine y RAG ----------------------------------------------

class CountingClient:
    def __init__(self):
        self.calls = 0

    def chat(self, **kwargs):
        self.calls += 1
        return {"message": {"content": '{"action": "chat", "params": {}}'}}


def test_intent_engine_remoto_no_manda_contenido_local():
    engine = IntentEngine.__new__(IntentEngine)
    engine.settings = Settings(ollama_host="http://10.0.0.5:11434", intent_model="m")
    engine.client = CountingClient()

    with request_sources(Fragment(USUARIO, "explica"), Fragment(ADJUNTO, "x = 1")):
        assert engine.detect("explica") == {"action": "chat", "params": {}}

    assert engine.client.calls == 0


def test_embedder_remoto_no_indexa(monkeypatch):
    SettingsManager.set_overrides({"ollama_host": "http://10.0.0.5:11434"})

    with pytest.raises(ExternalEmbeddingBlocked):
        OllamaEmbedder().embed("contenido del archivo")

    SettingsManager.set_overrides({"ollama_host": "http://10.0.0.5:11434", "trusted_local_hosts": ["10.0.0.5"]})
    assert OllamaEmbedder().external is False


def test_help_documenta_allow_external_y_provider_permanente(capsys):
    with pytest.raises(SystemExit):
        launcher.build_parser().parse_args(["--help"])

    out = capsys.readouterr().out
    assert "--allow-external" in out and "envía esto a Gemini" in out and "modo local" in out
    assert 'edita "default_provider" en config/settings.json' in out
