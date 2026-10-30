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
# Avisos de Asia entre corchetes ("[Respuesta recortada en 150 tokens ...]").
NOTICE = re.compile(r"^\s*\[[^\]]*\]\s*$")


def to_speakable(text: str, note=True) -> str:
    """Texto para leer en voz alta.

    note=False: sin "te dejo el código en pantalla" (la lectura frase por
    frase lo dice una vez al final, con screen_note).
    """
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

        if NOTICE.match(line):
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

    if note:
        text = f"{text} {note_for(had_code, had_table)}".strip()

    return text


def note_for(had_code: bool, had_table: bool) -> str:
    notes = [what for what, had in (("el código", had_code), ("la tabla", had_table)) if had]
    return f"Te dejo {' y '.join(notes)} en pantalla." if notes else ""


def screen_note(text: str) -> str:
    """"Te dejo el código (y la tabla) en pantalla." si la respuesta los tenía; si no, ""."""
    text = text or ""
    lines = FENCE.sub("\n", text).splitlines()
    had_code = bool(FENCE.search(text)) or any(INDENTED_CODE.match(line) for line in lines)
    had_table = any(TABLE_LINE.match(line) or TABLE_RULE.match(line) for line in lines)
    return note_for(had_code, had_table)


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
