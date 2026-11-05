"""De un artículo de Wikipedia en HTML a fragmentos, con una frase por línea (fase H, capa 3).

La verificación trabaja por líneas y un párrafo entero es imposible de copiar
textualmente: por eso cada frase es una línea, numerada en todo el artículo. La
estructura es la de mwoffliner: section[data-mw-section-id], anidadas, con el título
en div.mw-heading. Cada fragmento empieza por dónde vive, como los del indexador.
"""
import re

from core.rag.chunking import MAX_CHARS, Chunk

SECTION = "section[data-mw-section-id]"
HEADING = "mw-heading"
BLOCKS = ["p", "li", "tr", "dd", "dt", "pre"]
CELLS = ["th", "td"]
SEPARATOR = " > "
NOISE = "style, script, figure, sup.reference, .navbox, .noprint, .mw-editsection, .metadata"
MATH = ".mwe-math-element"
# No son contenido del artículo: lo que hay ahí son enlaces y bibliografía.
SKIPPED_SECTIONS = {"Véase también", "Notas", "Referencias", "Bibliografía", "Enlaces externos", "Fuentes"}
SENTENCE_END = re.compile(r"[.!?]\s+")
# Abreviaturas que no cierran frase ("Hospital St. Mary's" se cortaba en "St."), en
# minúsculas y sin el punto final. Además: las iniciales ("A. Fleming") y las siglas
# con puntos ("e.g.", "U.S.").
ABBREVIATIONS = {
    "p", "st", "sr", "sra", "srta", "dr", "dra", "ing", "lic", "prof", "etc", "ej", "núm", "num", "pág", "págs",
    "aprox", "av", "cf", "mr", "mrs", "ms", "jr", "vs",
}
LAST_WORD = re.compile(r"([\w.]+)\.$")
DOTTED = re.compile(r"(?:\w\.)+\w")
TEX = re.compile(r"^\{\\displaystyle\s*(.*?)\s*\}$", re.DOTALL)
SPACES = re.compile(r"\s+")


def is_abbreviation(piece: str) -> bool:
    """True si piece termina en una abreviatura, una inicial o una sigla con puntos, no en fin de frase."""
    found = LAST_WORD.search(piece)
    word = found.group(1) if found else ""
    # Una inicial es mayúscula: "3,5 m. Pesa" sí corta.
    return word.lower() in ABBREVIATIONS or (len(word) == 1 and word.isupper()) or bool(DOTTED.fullmatch(word))


def split_sentences(text: str) -> list:
    """Las frases de text: corta tras ".", "!" o "?" y un espacio, salvo tras una abreviatura."""
    sentences, start = [], 0

    for end in SENTENCE_END.finditer(text):
        piece = text[start:end.start() + 1]

        if text[end.start()] == "." and is_abbreviation(piece):
            continue

        sentences.append(piece)
        start = end.end()

    sentences.append(text[start:])
    return [sentence for sentence in sentences if sentence]


def clean(text: str) -> str:
    return SPACES.sub(" ", text.replace("﻿", "")).strip()


def tex_of(math) -> str:
    """El TeX de una fórmula: es lo único que queda legible sin la imagen."""
    formula = math.find("math")
    alt = formula.get("alttext", "") if formula else ""
    found = TEX.match(alt)
    return found.group(1) if found else alt


def block_text(block) -> str:
    if block.name != "tr":
        return clean(block.get_text())

    cells = [clean(cell.get_text()) for cell in block.find_all(CELLS, recursive=False)]
    filled = [cell for cell in cells if cell]
    return ": ".join(filled) if len(filled) == 2 else " | ".join(filled)


def section_sentences(section) -> list:
    """Las frases propias de section, sin las de las secciones anidadas."""
    sentences = []

    for block in section.find_all(BLOCKS):
        if block.find_parent("section") is not section or block.find_parent(BLOCKS):
            continue

        # Una fila no es prosa: "564 m s. n. m." no son tres frases.
        text = block_text(block)
        sentences += [text] if block.name == "tr" else split_sentences(text)

    return [sentence for sentence in sentences if sentence]


def pack(numbered: list, label: str) -> list:
    """Parte [(número, frase)] en fragmentos de MAX_CHARS como mucho, con label delante."""
    limit = MAX_CHARS - len(label) - 1
    chunks, current, size = [], [], 0

    def close():
        text = "\n".join([label, *(sentence for _, sentence in current)])
        chunks.append(Chunk(text, current[0][0], current[-1][0], label))

    for number, sentence in numbered:
        sentence = sentence[:limit]

        if current and size + len(sentence) + 1 > limit:
            close()
            current, size = [], 0

        current.append((number, sentence))
        size += len(sentence) + 1

    if current:
        close()

    return chunks


def article_chunks(title: str, html: str) -> list:
    """Los fragmentos de un artículo, por secciones. start_line cuenta frases de todo el artículo."""
    # Aquí y no arriba: solo hace falta con Wikipedia.
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    for tag in soup.select(NOISE):
        tag.decompose()

    for math in soup.select(MATH):
        math.replace_with(tex_of(math))

    for line_break in soup.select("br"):
        line_break.replace_with(" ")

    chunks, number = [], 0

    for section in soup.select(SECTION):
        path = [
            clean(heading.get_text())
            for parent in [section, *section.find_parents("section")]
            for heading in parent.find_all(class_=HEADING, recursive=False)[:1]
        ][::-1]

        if SKIPPED_SECTIONS.intersection(path):
            continue

        sentences = section_sentences(section)
        numbered = list(enumerate(sentences, number + 1))
        number += len(sentences)
        chunks += pack(numbered, SEPARATOR.join([title, *path]))

    return chunks
