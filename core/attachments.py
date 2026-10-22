"""Archivos adjuntos a un mensaje: @ruta, --file ruta y entrada por stdin.

El contenido de los adjuntos va al chat, no al IntentEngine: en el mensaje que
se clasifica, @ruta se reemplaza por la ruta absoluta, así una acción como
review_file_deep lee el archivo por su cuenta y el prompt del IntentEngine no
crece con el contenido.
"""
import difflib
import locale
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# @ruta o @"ruta con espacios", solo al inicio de una palabra: así no se toma
# como adjunto el @ de un correo (usuario@dominio.com).
ATTACHMENT_PATTERN = re.compile(r'(?<!\S)@(?:"([^"]+)"|(\S+))')

# Puntuación que suele quedar pegada a la ruta al escribir ("explica @a.py,").
TRAILING_PUNCTUATION = ".,;:!?)]}"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}

STDIN_LABEL = "entrada estándar"


@dataclass
class Attachment:
    label: str
    content: str
    total_chars: int
    path: Path | None = None

    @property
    def truncated(self) -> bool:
        return len(self.content) < self.total_chars


def decode(data: bytes) -> str:
    """UTF-8 (con o sin BOM) y, si no lo es, la codificación local (cp1252).

    Los saltos de línea quedan como "\\n", igual que al leer en modo texto:
    los archivos de Windows y lo que manda PowerShell por stdin usan "\\r\\n".
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode(locale.getpreferredencoding(False), errors="replace")

    return text.replace("\r\n", "\n").replace("\r", "\n")


def make_attachment(label: str, text: str, max_chars: int, path: Path | None = None) -> Attachment:
    return Attachment(label=label, content=text[:max_chars], total_chars=len(text), path=path)


class MissingAttachment(str):
    """Aviso de un adjunto que no existe. El launcher no envía el mensaje:
    sin el archivo, el modelo respondería sobre algo que no vio."""


MAX_SUGGESTIONS = 5


def suggest_paths(raw: str, cwd: Path) -> list[str]:
    """Archivos de la carpeta de raw cuyo nombre empieza igual o se parece.

    "mod" -> "moda.py"; "src/ap.py" -> "src/app.py". Primero los que empiezan
    igual (sin distinguir mayúsculas) y después los parecidos (difflib).
    """
    folder_text, _, name = raw.replace("\\", "/").rpartition("/")
    folder = resolve(folder_text or ".", cwd)

    try:
        entries = sorted(
            (e.name + ("/" if e.is_dir() else "") for e in os.scandir(folder) if not e.name.startswith(".")),
            key=str.lower
        )
    except OSError:
        return []

    by_lower = {entry.lower(): entry for entry in entries}
    lowered = name.lower()
    starts = [entry for entry in entries if lowered and entry.lower().startswith(lowered)]
    close = [by_lower[e] for e in difflib.get_close_matches(lowered, by_lower, n=MAX_SUGGESTIONS, cutoff=0.6)]

    prefix = folder_text + "/" if folder_text else ""
    unique = list(dict.fromkeys(starts + close))[:MAX_SUGGESTIONS]

    return [prefix + entry for entry in unique]


def missing_warning(raw: str, cwd: Path) -> MissingAttachment:
    message = f"No encontré el archivo adjunto: {raw}"
    suggestions = [
        "@" + (f'"{s}"' if " " in s else s)
        for s in suggest_paths(raw, cwd)
    ]

    if suggestions:
        message += f"\n  ¿Quisiste decir {', '.join(suggestions)}?"

    return MissingAttachment(message)


def read_attachment(path: Path, max_chars: int) -> Attachment | str:
    """Lee path como texto. Devuelve un aviso (str) si no se puede adjuntar."""
    if path.is_dir():
        return f"{path} es una carpeta; solo se adjuntan archivos."

    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return f"{path} es una imagen; las imágenes necesitan un modelo con visión (todavía no soportado)."

    data = path.read_bytes()

    # Un byte nulo al principio casi siempre es un binario (exe, zip, pdf...).
    if b"\0" in data[:8192]:
        return f"{path} parece un archivo binario; no se adjunta."

    return make_attachment(str(path), decode(data), max_chars, path=path)


def resolve(raw: str, cwd: Path) -> Path:
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else cwd / path).resolve()


def quote_path(path: Path) -> str:
    text = str(path)
    return f'"{text}"' if " " in text else text


def extract_attachments(text: str, cwd: Path, max_chars: int):
    """Busca @ruta en text.

    Devuelve (texto, adjuntos, avisos). En texto cada @ruta encontrada queda
    como la ruta absoluta; las que no existen se dejan tal cual, con un aviso.
    Un archivo nombrado dos veces se adjunta una sola vez.
    """
    attachments = []
    warnings = []
    seen = set()

    def replace(match):
        raw = match.group(1) or match.group(2)
        suffix = ""

        candidates = [(raw, "")]
        stripped = raw.rstrip(TRAILING_PUNCTUATION)

        if match.group(2) and stripped and stripped != raw:
            candidates.append((stripped, raw[len(stripped):]))

        for candidate, suffix in candidates:
            path = resolve(candidate, cwd)

            if path.exists():
                break
        else:
            warnings.append(missing_warning(raw, cwd))
            return match.group(0)

        if path not in seen:
            seen.add(path)
            result = read_attachment(path, max_chars)

            if isinstance(result, str):
                warnings.append(result)
            else:
                attachments.append(result)

        return quote_path(path) + suffix

    return ATTACHMENT_PATTERN.sub(replace, text), attachments, warnings


def file_attachments(paths, cwd: Path, max_chars: int):
    """Adjuntos de --file. Devuelve (adjuntos, avisos)."""
    attachments = []
    warnings = []

    for raw in paths:
        path = resolve(raw, cwd)

        if not path.exists():
            warnings.append(missing_warning(raw, cwd))
            continue

        result = read_attachment(path, max_chars)

        if isinstance(result, str):
            warnings.append(result)
        else:
            attachments.append(result)

    return attachments, warnings


def truncation_warnings(attachments) -> list[str]:
    return [
        f"[Aviso] {a.label}: se adjuntaron {len(a.content)} de {a.total_chars} "
        "caracteres (attachment_max_chars en config)."
        for a in attachments
        if a.truncated
    ]


def build_chat_prompt(text: str, attachments) -> str:
    """Mensaje para el chat con el contenido de los adjuntos al final."""
    if not attachments:
        return text

    parts = [text, "", "Archivos adjuntos:"]

    for a in attachments:
        cut = " (recortado)" if a.truncated else ""
        parts += [f"--- {a.label}{cut} ---", a.content, f"--- fin de {a.label} ---"]

    return "\n".join(parts)


def history_prompt(text: str, attachments) -> str:
    """Lo que se guarda en el historial del chat: sin el contenido.

    Con el contenido completo, unos pocos adjuntos llenarían la ventana de
    contexto y Ollama recortaría el principio (el prompt de sistema). Para
    volver a preguntar por el archivo hay que adjuntarlo otra vez.
    """
    if not attachments:
        return text

    names = ", ".join(f"{a.label} ({a.total_chars} caracteres)" for a in attachments)
    return f"{text}\n\n[Adjuntos no incluidos en el historial: {names}]"


def read_stdin(stream=None) -> bytes | None:
    """Contenido de stdin si viene de una tubería o redirección; None si es la terminal."""
    stream = stream or sys.stdin

    if stream is None or stream.isatty():
        return None

    return stream.buffer.read()
