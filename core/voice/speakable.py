"""Lo que se lee en voz alta de una respuesta.

Solo el texto normal: sin bloques de código, tablas, rutas, URLs ni marcas de
markdown. Si había código o tablas, se añade "te dejo el código en
pantalla" (o "la tabla"). La respuesta completa se sigue mostrando.
"""
import re

FENCE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
INDENTED_CODE = re.compile(r"^(?: {4}|\t)\S")
URL = re.compile(r"https?://\S+|www\.\S+")
WINDOWS_PATH = re.compile(r'"?[A-Za-z]:[\\/][^\s"]*"?')
SLASHED_PATH = re.compile(r"(?<![\w])(?:\.{0,2}/)?(?:[\w.-]+[\\/])+[\w.-]+")
INLINE_CODE = re.compile(r"`([^`\n]*)`")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
HEADER = re.compile(r"^\s{0,3}#{1,6}\s*")
BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
QUOTE = re.compile(r"^\s*>\s?")
EMPHASIS = re.compile(r"(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1")


def to_speakable(text: str) -> str:
    """Texto para leer en voz alta."""
    had_code = bool(FENCE.search(text or ""))
    text = FENCE.sub("\n", text or "")
    lines = []
    had_table = False

    for line in text.splitlines():
        if TABLE_LINE.match(line) or TABLE_RULE.match(line):
            had_table = True
            continue

        if INDENTED_CODE.match(line):
            had_code = True
            continue

        line = HEADER.sub("", line)
        line = BULLET.sub("", line)
        line = QUOTE.sub("", line)
        lines.append(line)

    text = "\n".join(lines)
    text = LINK.sub(r"\1", text)
    text = URL.sub("", text)
    # Código en línea: se lee si es una palabra; una ruta o expresión, no.
    text = INLINE_CODE.sub(lambda m: m.group(1) if re.fullmatch(r"[\w áéíóúñü-]+", m.group(1)) else "", text)
    text = WINDOWS_PATH.sub("", text)
    text = SLASHED_PATH.sub("", text)
    text = EMPHASIS.sub(r"\2", text)
    text = re.sub(r"[*_#`|]+", " ", text)
    text = sentences(text)

    notes = [what for what, had in (("el código", had_code), ("la tabla", had_table)) if had]

    if notes:
        note = f"Te dejo {' y '.join(notes)} en pantalla."
        text = f"{text} {note}".strip()

    return text


def sentences(text: str) -> str:
    """Una sola línea, con punto entre las líneas que no lo tenían (para las pausas)."""
    parts = []

    for line in text.splitlines():
        line = " ".join(line.split()).strip(" ,;")

        if not line:
            continue

        if line[-1] not in ".!?:…":
            line += "."

        parts.append(line)

    return re.sub(r"\s+([.,;:!?])", r"\1", " ".join(parts))
