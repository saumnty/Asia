"""Citas literales de los fragmentos, verificadas por código (fase H).

El modelo copia las líneas que responden la pregunta y el código comprueba que
existan; responde solo con las que sobreviven. Es lo mismo que hace la revisión
de código con sus citas (tools/review_findings.py).
"""
import re
import textwrap
from dataclasses import dataclass

from core import prompts
from core.rag.library import FRAGMENT_HEADER
from tools.review_findings import clean_quote, locate_quote, squash

# "- [core/brain.py:40-55] línea copiada". La etiqueta es opcional: sin ella, la
# línea se busca en todos los fragmentos.
QUOTE = re.compile(r"^[\s*>-]*(?:\[([^\]\n]+)\]\s*:?\s*)?(.+)$", re.MULTILINE)
FIRST_LINE = re.compile(r":(\d+)(?:-\d+)?$")
# Lo que la redacción del modelo puede citar o nombrar, para comprobarlo.
CITED_LINES = re.compile(r"\[([\w./\\-]+\.\w+):(\d+)(?:[-–](\d+))?\]")
CITED_FILE = re.compile(r"\[([\w./\\-]+\.\w+)\]")
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
BACKTICKED = re.compile(r"`([^`\n]+)`")
WORD = re.compile(r"\w+")
CAMEL_CASE = re.compile(r"[a-z0-9][A-Z]")
FALLBACK_FRAGMENTS = 3
FALLBACK_CHARS = 600


@dataclass
class Fragment:
    tag: str
    label: str
    text: str


@dataclass(frozen=True)
class Quote:
    path: str
    line: int
    label: str
    text: str

    @property
    def cite(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


def parse_fragments(context: str) -> list:
    """Los fragmentos del contexto. La primera línea de text dice dónde vive, no es del archivo."""
    headers = list(FRAGMENT_HEADER.finditer(context))
    fragments = []

    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(context)
        text = context[header.end():end].partition("Contenido:\n")[2].strip()
        fragments.append(Fragment(header.group(1), header.group(2) or "", text))

    return fragments


def parse_quotes(response: str) -> list:
    """[(etiqueta o None, línea)] de la respuesta del modelo."""
    return [(tag, clean_quote(text)) for tag, text in QUOTE.findall(response)]


def quote_at(fragment: Fragment, number: int) -> Quote:
    """La línea number de fragment.text tal como está en el archivo, no como la copió el modelo."""
    text = fragment.text.splitlines()[number - 1].rstrip()
    first = FIRST_LINE.search(fragment.tag)

    if not first:
        return Quote(fragment.tag, None, fragment.label, text)

    # number cuenta la primera línea de text, que no es del archivo.
    return Quote(fragment.tag[:first.start()], int(first.group(1)) + number - 2, fragment.label, text)


def verify_quotes(response: str, context: str) -> list:
    """Las citas que existen en los fragmentos, sin repetir, normalizando espacios.

    Si la etiqueta es de otro fragmento, vale el fragmento donde está de verdad.
    """
    fragments = parse_fragments(context)
    verified = []

    for tag, text in parse_quotes(response):
        for fragment in sorted(fragments, key=lambda f: f.tag != tag):
            number = locate_quote(text, fragment.text)

            if number and number > 1:
                verified.append(quote_at(fragment, number))
                break

    return list(dict.fromkeys(verified))


def quotes_text(quotes: list) -> str:
    return "\n".join(f"[{quote.cite}] {quote.text.strip()}" for quote in quotes)


def unverified_tags(answer: str, quotes: list) -> list:
    """Las etiquetas [archivo:líneas] de la redacción que no están entre las verificadas."""
    verified = {(quote.path, quote.line) for quote in quotes}
    unverified = []

    for match in CITED_LINES.finditer(answer):
        path, first, last = match.group(1), int(match.group(2)), int(match.group(3) or match.group(2))

        if any((path, line) not in verified for line in range(first, last + 1)):
            unverified.append(match.group(0))

    return unverified


def is_identifier(word: str) -> bool:
    return "_" in word or bool(CAMEL_CASE.search(word))


def unknown_names(answer: str, context: str) -> list:
    """Los archivos, el código y los identificadores de la redacción que no están en los fragmentos."""
    text = CITED_LINES.sub(" ", answer)
    code = [line for block in FENCE.findall(text) for line in block.splitlines() if line.strip()]
    text = FENCE.sub(" ", text)
    code += CITED_FILE.findall(text) + BACKTICKED.findall(text)
    known = squash(context)
    words = set(WORD.findall(context))

    unknown = [item.strip() for item in code if squash(item.strip(" .,:;")) not in known]
    unknown += [word for word in WORD.findall(BACKTICKED.sub(" ", text)) if is_identifier(word) and word not in words]
    return list(dict.fromkeys(unknown))


def draft_problems(answer: str, quotes: list, context: str) -> list:
    """Por qué no se puede mostrar la redacción del modelo. Vacío si se puede."""
    return unverified_tags(answer, quotes) + unknown_names(answer, context)


def block_of(run: list) -> str:
    """Un tramo de líneas seguidas: "core/brain.py:40-45 (Brain.process)" y su texto."""
    first, last = run[0], run[-1]
    cite = first.cite if first.line == last.line else f"{first.cite}-{last.line}"
    label = f" ({first.label})" if first.label else ""
    text = textwrap.dedent("\n".join(quote.text for quote in run))
    return f"{cite}{label}\n{textwrap.indent(text, '  ')}"


def verified_lines(quotes: list) -> str:
    """Las citas verificadas por archivo, juntando las seguidas. Las escribe el código."""
    by_file = {}

    for quote in quotes:
        by_file.setdefault(quote.path, []).append(quote)

    blocks = []

    for group in by_file.values():
        runs = []

        for quote in sorted(group, key=lambda q: q.line or 0):
            if runs and quote.line and runs[-1][-1].line == quote.line - 1:
                runs[-1].append(quote)
            else:
                runs.append([quote])

        blocks += [block_of(run) for run in runs]

    return f"{prompts.VERIFIED_LINES}\n\n" + "\n\n".join(blocks)


def best_fragments(context: str) -> str:
    """Los mejores fragmentos tal cual: lo que se muestra si no hay citas verificadas."""
    blocks = []

    for fragment in parse_fragments(context)[:FALLBACK_FRAGMENTS]:
        text = fragment.text.partition("\n")[2].strip()
        cut = "…" if len(text) > FALLBACK_CHARS else ""
        blocks.append(f"[{fragment.tag}] {fragment.label}".strip() + f"\n{text[:FALLBACK_CHARS]}{cut}")

    return f"{prompts.NO_DIRECT_ANSWER}\n\n" + "\n\n".join(blocks)
