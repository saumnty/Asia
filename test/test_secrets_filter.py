"""Paso 4 de la fase G: secretos en lo que sale hacia un proveedor externo."""
import pytest

from config.settings_manager import read_json
from core.paths import DEFAULTS_FILE
from core.provenance import USUARIO, Fragment, request_sources
from core.secrets_filter import redact, safe_error
from test_confidential_policy import make_router, sent_to_gemini

GOOGLE_KEY = "AIza" + "S" * 35


@pytest.mark.parametrize(
    "text, kind",
    [
        (f"mi clave es {GOOGLE_KEY}", "clave de Google/Gemini"),
        ("usa sk-proj-" + "a1B2" * 8, "clave de OpenAI"),
        ("sk-ant-api03-" + "x" * 30, "clave de Anthropic"),
        ("token ghp_" + "A" * 36, "token de GitHub"),
        ("AKIAABCDEFGHIJKLMNOP es de AWS", "clave de AWS"),
        ("xoxb-1234567890-abcdef", "token de Slack"),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123", "token Bearer"),
        ("DATABASE_PASSWORD=hunter2hunter2", "variable secreta (.env)"),
        ("contraseña: hunter2hunter2", "contraseña"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA\n-----END RSA PRIVATE KEY-----", "llave privada"),
    ],
)
def test_detecta_y_redacta(text, kind):
    redacted, found = redact(text)

    assert found and found[0] == kind
    assert f"[SECRETO REDACTADO: {kind}]" in redacted


def test_texto_normal_no_cambia():
    text = "explica la función promedio de moda.py y por qué falla con listas vacías"

    assert redact(text) == (text, [])


def test_la_clave_de_gemini_del_entorno_se_busca_tal_cual(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-rara-sin-formato-123")

    redacted, found = redact("la clave es clave-rara-sin-formato-123, ¿sirve?")

    assert "clave-rara-sin-formato-123" not in redacted
    assert "clave de Gemini del entorno" in found
    assert "clave-rara" not in safe_error(RuntimeError("401 clave-rara-sin-formato-123 inválida"))


def test_politica_por_defecto_redactar():
    assert read_json(DEFAULTS_FILE)["external_secret_policy"] == "redact"


def test_router_redacta_aunque_el_envio_sea_exportable():
    router = make_router()

    with request_sources(Fragment(USUARIO, "x")):
        answer = router.ask(f"¿por qué falla con {GOOGLE_KEY}?")

    assert GOOGLE_KEY not in sent_to_gemini(router)
    assert "[SECRETO REDACTADO: clave de Google/Gemini]" in sent_to_gemini(router)
    assert answer.startswith("[Modo confidencial] Redacté antes de enviar a gemini: clave de Google/Gemini.")


def test_router_bloquea_con_politica_block():
    router = make_router(external_secret_policy="block")

    with request_sources(Fragment(USUARIO, "x")):
        answer = router.ask(f"¿por qué falla con {GOOGLE_KEY}?")

    assert router.providers["gemini"].received == []
    assert "No envié esto a gemini: contiene secretos (clave de Google/Gemini)" in answer
    assert answer.endswith("respuesta de ollama")


def test_tambien_con_autorizacion_de_una_vez():
    router = make_router()

    with request_sources(Fragment(USUARIO, "x"), Fragment("adjunto", "TOKEN=abcdefghijk")):
        router.ask("revisa\nTOKEN=abcdefghijk")

    router.prepare_authorization()
    router.send_authorized()

    assert "abcdefghijk" not in sent_to_gemini(router)


def test_el_error_de_gemini_no_muestra_la_clave(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-rara-sin-formato-123")
    router = make_router(fallback=None)
    router.providers["gemini"].fail = RuntimeError("API key clave-rara-sin-formato-123 not valid")

    with request_sources(Fragment(USUARIO, "hola")):
        answer = router.ask("hola")

    assert "clave-rara-sin-formato-123" not in answer
    assert answer.startswith("Error usando provider gemini:")
