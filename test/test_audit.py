"""Paso 5 de la fase G: bitácora de envíos externos, sin el texto."""
import json

from core import paths
from core.audit import prompt_hash, summary
from core.actions.confidential import confidential_command
from core.provenance import ADJUNTO, USUARIO, Fragment, request_sources
from test_confidential_policy import make_router

TEXT = "PALABRA_QUE_NO_DEBE_QUEDAR_EN_LA_BITACORA"


def entries():
    path = paths.EXTERNAL_AUDIT_FILE
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_una_linea_por_envio_externo_sin_el_texto():
    router = make_router()

    with request_sources(Fragment(USUARIO, TEXT)):
        router.ask(f"explica {TEXT}")

    [entry] = entries()
    assert set(entry) == {
        "fecha", "proveedor", "modelo", "tipos", "caracteres", "sha256",
        "autorizacion", "secretos_redactados", "respuesta",
    }
    assert entry["proveedor"] == "gemini" and entry["tipos"] == ["usuario"]
    assert entry["autorizacion"] == "exportable" and entry["respuesta"] == "ok"
    sent = router.providers["gemini"].received[0]
    assert entry["caracteres"] == sum(len(m["content"]) for m in sent)
    assert entry["sha256"] == prompt_hash(sent)
    assert TEXT not in paths.EXTERNAL_AUDIT_FILE.read_text(encoding="utf-8")


def test_lo_bloqueado_y_lo_local_no_se_registra():
    router = make_router(primary="ollama", fallback=None)

    with request_sources(Fragment(USUARIO, "hola")):
        router.ask("hola")

    router.settings.values["default_provider"] = "gemini"

    with request_sources(Fragment(ADJUNTO, "x = 1")):
        router.ask("x = 1")

    assert entries() == []


def test_autorizacion_y_fallo_quedan_registrados():
    router = make_router()

    with request_sources(Fragment(ADJUNTO, "x = 1")):
        router.ask("x = 1")

    router.prepare_authorization()
    router.send_authorized()
    router.providers["gemini"].fail = RuntimeError("caído")

    with request_sources(Fragment(USUARIO, "hola")):
        router.ask("hola")

    first, second = entries()
    assert first["autorizacion"] == "una vez" and first["tipos"] == ["adjunto"]
    assert second["respuesta"] == "error"


def test_comando_que_has_enviado_afuera():
    assert confidential_command("¿Qué has enviado afuera?") == "audit"
    assert summary().startswith("No he enviado nada afuera")

    router = make_router()

    with request_sources(Fragment(USUARIO, TEXT)):
        router.ask(TEXT)

    text = summary()
    assert text.startswith("Últimos 1 envíos externos")
    assert "gemini · usuario ·" in text and "exportable" in text
    assert TEXT not in text


def test_logs_en_gitignore():
    from core.paths import PROJECT_ROOT

    assert "logs/" in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
