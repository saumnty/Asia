"""Troceado con sentido (fase H).

- Python: una pieza por función, método y clase (ast), más lo que queda fuera
  de ellas (imports, constantes).
- .md, .rst y .tex: una pieza por sección.
- Simulink: cada bloque con código, como un .m (core/rag/simulink.py).
- El resto: bloques separados por líneas en blanco.

Una pieza de más de MAX_CHARS se parte por líneas, con solape. Cada fragmento
lleva sus líneas y lo que es ("Clase.metodo", "Sección"), que va delante del
texto al generar el embedding y al buscar por palabras: un fragmento de una
función no siempre dice dónde vive.
"""
import ast
import re
from dataclasses import dataclass

from core.rag.simulink import SUFFIX as SIMULINK_SUFFIX
from core.rag.simulink import split_blocks

MAX_CHARS = 1200
OVERLAP_LINES = 3
# Lo que no llega a esto se junta con el bloque siguiente.
MIN_BLOCK_CHARS = 200

MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
MD_FENCE = re.compile(r"^ {0,3}(`|~)\1\1")
RST_UNDERLINE = re.compile(r"""^([=\-~^"'`*+#:.])\1{2,}\s*$""")
TEX_HEADING = re.compile(r"^\s*\\(chapter|section|subsection|subsubsection)\*?\{(.+?)\}")
DOCUMENT_SUFFIXES = {".md": MD_HEADING, ".markdown": MD_HEADING, ".tex": TEX_HEADING}


@dataclass
class Piece:
    start: int
    end: int
    label: str = ""


@dataclass
class Chunk:
    text: str
    start_line: int
    end_line: int
    label: str = ""


def python_pieces(text: str, lines: list) -> list:
    """Funciones, métodos y lo demás. None si el archivo no se puede analizar."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None

    pieces, covered = [], set()

    def first_line(node):
        return min([node.lineno, *(d.lineno for d in node.decorator_list)])

    def add(node, label):
        start = first_line(node)
        pieces.append(Piece(start, node.end_lineno, label))
        covered.update(range(start, node.end_lineno + 1))

    def visit(body, prefix=""):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add(node, f"{prefix}{node.name}")
            elif isinstance(node, ast.ClassDef):
                methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                visit(methods, f"{prefix}{node.name}.")

                # La cabecera de la clase, sus atributos y lo que no sea método.
                rest = [
                    line for line in range(first_line(node), node.end_lineno + 1)
                    if line not in covered
                ]
                pieces.extend(runs(rest, f"{prefix}{node.name}"))
                covered.update(rest)

    visit(tree.body)
    outside = [i for i in range(1, len(lines) + 1) if i not in covered and lines[i - 1].strip()]
    pieces.extend(runs(outside, ""))
    return sorted(pieces, key=lambda piece: piece.start)


def runs(numbers: list, label: str) -> list:
    """Líneas seguidas en piezas; un hueco de hasta dos líneas no las separa."""
    pieces = []

    for number in numbers:
        if pieces and number - pieces[-1].end <= 3:
            pieces[-1].end = number
        else:
            pieces.append(Piece(number, number, label))

    return pieces


def document_pieces(lines: list, heading) -> list:
    """Una pieza por sección; la etiqueta es la ruta de títulos ("Voz > J2")."""
    pieces = [Piece(1, 0)]
    trail = []
    fence = None

    for number, line in enumerate(lines, 1):
        # Dentro de un bloque de código, "# comentario" no es un título.
        opening = MD_FENCE.match(line) if heading is MD_HEADING else None

        if opening and fence in (None, opening.group(1)):
            fence = None if fence else opening.group(1)
            continue

        match = None if fence else heading.match(line)

        if not match:
            continue

        level = len(match.group(1)) if heading is MD_HEADING else TEX_LEVELS[match.group(1)]
        trail = [t for t in trail if t[0] < level] + [(level, match.group(2))]
        pieces[-1].end = number - 1
        pieces.append(Piece(number, number, " > ".join(title for _, title in trail)))

    pieces[-1].end = len(lines)
    return [piece for piece in pieces if piece.end >= piece.start]


def rst_pieces(lines: list) -> list:
    """Una pieza por sección de un .rst. En rst el nivel lo da el orden en que aparece cada subrayado."""
    pieces = [Piece(1, 0)]
    trail, levels = [], []

    for index in range(1, len(lines)):
        underline, title = RST_UNDERLINE.match(lines[index]), lines[index - 1].rstrip()

        if not underline or not title or title[0].isspace() or RST_UNDERLINE.match(title):
            continue

        if len(lines[index].rstrip()) < len(title):
            continue

        over = index >= 2 and lines[index - 2].rstrip() == lines[index].rstrip()
        style = (underline.group(1), over)

        if style not in levels:
            levels.append(style)

        level = levels.index(style)
        trail = [t for t in trail if t[0] < level] + [(level, title)]
        start = index - 1 if over else index
        pieces.append(Piece(start, index + 1, " > ".join(name for _, name in trail)))

    if len(pieces) == 1:
        return None

    pieces[-1].end = len(lines)

    for piece, following in zip(pieces, pieces[1:]):
        piece.end = following.start - 1

    return [piece for piece in pieces if piece.end >= piece.start]


TEX_LEVELS = {"chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4}


def block_pieces(lines: list) -> list:
    """Bloques separados por líneas en blanco, juntando los muy cortos."""
    pieces, size = [], 0
    blank = True

    for number, line in enumerate(lines, 1):
        if not line.strip():
            blank = True
            continue

        if blank and (not pieces or size >= MIN_BLOCK_CHARS):
            pieces.append(Piece(number, number))
            size = 0

        pieces[-1].end = number
        size += len(line) + 1
        blank = False

    return pieces


def split_long(piece: Piece, lines: list) -> list:
    """Parte una pieza grande por líneas, con OVERLAP_LINES de solape."""
    chunks = []
    start = piece.start

    while True:
        size, end = 0, start - 1

        while end < piece.end and (end < start or size + len(lines[end]) + 1 <= MAX_CHARS):
            size += len(lines[end]) + 1
            end += 1

        text = "\n".join(lines[start - 1:end])[:MAX_CHARS * 2]
        chunks.append(Chunk(text, start, end, piece.label))

        if end >= piece.end:
            return chunks

        start = max(start + 1, end + 1 - OVERLAP_LINES)


def model_chunks(text: str) -> list:
    """Cada bloque de un modelo de Simulink se trocea como un .m, con su nombre de etiqueta."""
    return [
        Chunk(chunk.text, chunk.start_line, chunk.end_line, name)
        for name, script in split_blocks(text)
        for chunk in chunk_text(script, ".m")
    ]


def chunk_text(text: str, suffix: str) -> list:
    """Los fragmentos de un archivo con esa extensión."""
    lines = text.splitlines()
    suffix = suffix.lower()

    if suffix == SIMULINK_SUFFIX:
        return model_chunks(text)

    if suffix == ".py":
        pieces = python_pieces(text, lines)
    elif suffix == ".rst":
        pieces = rst_pieces(lines)
    elif suffix in DOCUMENT_SUFFIXES:
        pieces = document_pieces(lines, DOCUMENT_SUFFIXES[suffix])
    else:
        pieces = None

    if pieces is None:
        pieces = block_pieces(lines)

    chunks = []

    for piece in pieces:
        chunks += split_long(piece, lines)

    return [chunk for chunk in chunks if chunk.text.strip()]
