"""Secretos en lo que sale hacia un proveedor externo (fase G, paso 4).

Se revisa todo envío externo, aunque esté autorizado: claves de API,
tokens, contraseñas de un .env y llaves privadas. Según
external_secret_policy se redactan (por defecto) o se bloquea el envío.
La clave de Gemini del entorno se busca además tal cual: no debe aparecer
en un prompt, en un mensaje de error ni en la bitácora.
"""
import os
import re

REDACTED = "[SECRETO REDACTADO: {kind}]"

# Variables de entorno cuyo valor nunca debe salir en un prompt ni en un error.
SECRET_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

PATTERNS = [
    ("llave privada", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL)),
    ("clave de Google/Gemini", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("clave de Anthropic", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("clave de OpenAI", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("token de GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}|\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("clave de AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token de Slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("token Bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    # Línea de un .env: NOMBRE_CON_KEY/TOKEN/SECRET/PASSWORD = valor.
    ("variable secreta (.env)", re.compile(
        r"(?m)^[ \t]*(?:export[ \t]+)?[A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD)[A-Za-z0-9_]*"
        r"[ \t]*=[ \t]*\S+")),
    ("contraseña", re.compile(
        r"(?i)\b(?:password|passwd|pwd|contrase[nñ]a|clave|secret|api[_-]?key|token)\b[ \t]*[:=][ \t]*"
        r"['\"]?[^\s'\"]{6,}")),
]


def env_secrets() -> list[str]:
    return [v for v in (os.environ.get(name, "") for name in SECRET_ENV_VARS) if len(v) >= 8]


def redact(text: str) -> tuple[str, list[str]]:
    """Texto con los secretos redactados y la lista de tipos encontrados."""
    found = []

    for value in env_secrets():
        if value in text:
            found.append("clave de Gemini del entorno")
            text = text.replace(value, REDACTED.format(kind="clave de Gemini del entorno"))

    for kind, pattern in PATTERNS:
        def replace(match, kind=kind):
            found.append(kind)
            return REDACTED.format(kind=kind)

        text = pattern.sub(replace, text)

    return text, found


def redact_messages(messages: list) -> tuple[list, list[str]]:
    result, found = [], []

    for message in messages:
        content, kinds = redact(message.get("content") or "")
        result.append({**message, "content": content})
        found += kinds

    return result, found


def safe_error(error) -> str:
    """Texto de un error sin secretos (p. ej. la clave de Gemini)."""
    return redact(str(error))[0]


def describe(found: list[str]) -> str:
    counts = {}

    for kind in found:
        counts[kind] = counts.get(kind, 0) + 1

    return ", ".join(f"{kind} ×{n}" if n > 1 else kind for kind, n in counts.items())
