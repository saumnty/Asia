"""Modo confidencial (fase G): qué puede salir hacia un proveedor externo.

Externo es Gemini y también Ollama cuando ollama_host no es esta máquina
(localhost, 127.0.0.1, ::1) ni un host de trusted_local_hosts (vacía por
defecto; nunca se llena sola).

Antes de un envío externo:
- Si lo que trae el mensaje (lo tecleado, los adjuntos y lo que leyeron
  las acciones) tiene contenido local, no sale: responde el modelo local.
  Solo sale con una autorización de una sola vez, y lo "emocional" nunca.
- La memoria, el resumen del proyecto y los turnos locales del historial
  son contexto de fondo del chat: no bloquean el envío, se quitan de lo
  que sale (la memoria se deja si external_allow_memory es true).
- En modo local ("modo local") no sale nada, ni lo tecleado.
- Las rutas absolutas se reemplazan por el nombre del archivo, solo en lo
  que sale.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from core.provenance import (
    NEVER_EXPORT,
    USUARIO,
    Fragment,
    chars_by_label,
    labels_of,
    local_labels,
)

EXTERNAL_PROVIDERS = {"gemini"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

LOCAL_MODE = "local"


def is_local_mode(settings) -> bool:
    return settings.get("confidential_mode") == LOCAL_MODE


def ollama_is_external(settings) -> bool:
    host = settings.get("ollama_host") or "http://localhost:11434"
    name = urlparse(host if "//" in host else f"//{host}").hostname or ""
    trusted = {h.lower() for h in settings.get("trusted_local_hosts") or []}
    return name.lower() not in LOCAL_HOSTS | trusted


def is_external(provider_name: str, settings) -> bool:
    if provider_name in EXTERNAL_PROVIDERS:
        return True

    return provider_name == "ollama" and ollama_is_external(settings)


@dataclass
class OutgoingRequest:
    """Un prompt listo para enviar.

    messages es lo completo (para el modelo local); external_messages, lo
    que puede salir sin el contexto de fondo local. turn es la procedencia
    de lo que trae este mensaje; omitted, lo que se quitó de external_messages.
    """
    messages: list
    turn: list
    external_messages: list = None
    omitted: list = field(default_factory=list)
    # Etiquetas del contexto de fondo que sí van en external_messages (memoria permitida...).
    exported_ambient: list = field(default_factory=list)

    def __post_init__(self):
        if self.external_messages is None:
            self.external_messages = self.messages


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    local: set = field(default_factory=set)


def check(request: OutgoingRequest, settings, authorized=False) -> Decision:
    """¿Puede salir request? authorized: autorización de una sola vez."""
    if is_local_mode(settings):
        return Decision(False, "estás en modo local: no sale nada de esta máquina", labels_of(request.turn))

    labels = labels_of(request.turn)
    never = labels & NEVER_EXPORT

    if never:
        return Decision(False, f"lleva contenido {describe_labels(never)}, que nunca sale", never)

    local = local_labels(labels, settings)

    if local and not authorized:
        return Decision(False, f"lleva contenido local ({describe_chars(request.turn, local)})", local)

    return Decision(True)


def describe_labels(labels) -> str:
    return ", ".join(sorted(labels))


def describe_chars(fragments, labels=None) -> str:
    counts = chars_by_label(fragments)
    return ", ".join(
        f"{label}: {count} caracteres"
        for label, count in sorted(counts.items())
        if labels is None or label in labels
    )


# --- Rutas absolutas -----------------------------------------------------------

QUOTED_WINDOWS_PATH = re.compile(r'"([A-Za-z]:[\\/][^"\r\n]*)"')
WINDOWS_PATH = re.compile(r'(?<![\w])[A-Za-z]:[\\/](?:[^\s"\'<>|*?\\/]+[\\/])*([^\s"\'<>|*?\\/]*)')
POSIX_PATH = re.compile(r'(?<![\w.~])/(?:home|Users|root|mnt|media|tmp|var|opt|srv)/(?:[^\s/"\']+/)*([^\s/"\']*)')


def basename(path: str) -> str:
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1]


def redact_paths(text: str) -> str:
    """C:\\Users\\santy\\x\\a.py -> a.py, solo en lo que sale."""
    text = QUOTED_WINDOWS_PATH.sub(lambda m: f'"{basename(m.group(1))}"', text)
    text = WINDOWS_PATH.sub(lambda m: m.group(1) or basename(m.group(0)), text)
    return POSIX_PATH.sub(lambda m: m.group(1) or basename(m.group(0)), text)


def outgoing_messages(messages: list) -> list:
    return [{**m, "content": redact_paths(m.get("content") or "")} for m in messages]


def only_user(text: str) -> list:
    """Procedencia de un texto tecleado (para llamadas como el IntentEngine)."""
    return [Fragment(USUARIO, text)]
