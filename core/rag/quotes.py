"""Citas literales de los fragmentos, verificadas por código (fase H).

El modelo copia las líneas que responden la pregunta y el código comprueba que
existan; responde solo con las que sobreviven. Es lo mismo que hace la revisión
de código con sus citas (tools/review_findings.py).
"""
import re
import textwrap
from dataclasses import dataclass

from core import prompts
from core.rag.library import FRAGMENT_HEADER, ORIGIN_PREFIX
from tools.review_findings import clean_quote, locate_quote, squash

# "- [core/brain.py:40-55] línea copiada". La etiqueta es opcional: sin ella, la
# línea se busca en todos los fragmentos.
QUOTE = re.compile(r"^[\s*>-]*(?:\[([^\]\n]+)\]\s*:?\s*)?(.+)$", re.MULTILINE)
FIRST_LINE = re.compile(r":(\d+)(?:-\d+)?$")
# Lo que la redacción del modelo puede citar o nombrar, para comprobarlo.
CITED_LINES = re.compile(r"[\[`]([\w./\\-]+\.\w+):(\d+)(?:[-–](\d+))?[\]`]")
CITED_FILE = re.compile(r"\[([\w./\\-]+\.\w+)\]")
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
FENCE_BLOCK = re.compile(r"(```[^\n]*\n.*?```)", re.DOTALL)
BACKTICKED = re.compile(r"`([^`\n]+)`")
DOUBLE_QUOTED = re.compile(r'["“]([^"”\n]+)["”]')
WORD = re.compile(r"\w+")
FILE_PATH = re.compile(r"[\w./\\-]+\.\w+")
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?!\w)")
TIME_UNITS = r"segundos?|seg|s|minutos?|min|horas?|h|milisegundos?|ms"
# "3 segundos": el número puede estar en la línea sin que la línea diga segundos.
TIMED = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)\s*({TIME_UNITS})\b", re.IGNORECASE)
TIME_UNIT = re.compile(rf"\b(?:{TIME_UNITS})\b|_(?:s|ms)\b", re.IGNORECASE)
# "drop_client se define en...": decirlo exige citar su definición, no una llamada.
DEFINES = re.compile(r"\bdefin\w*|\bse encuentra\b|\bdeclar\w*|\bimplementad\w*", re.IGNORECASE)
# "Frase. [a.py:4] Otra.": la etiqueta es de la frase de antes.
TAG_AFTER_END = re.compile(rf"([.!?])((?:\s*{CITED_LINES.pattern})+)")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
LIST_MARKER = re.compile(r"\s*(?:\d+[.)]\s+|[-*]\s+)?")
CAMEL_CASE = re.compile(r"[a-z][a-z0-9]*[A-Z]")
# Una línea de código suelta, no una frase.
CODE_LINE = re.compile(r"\s*(?:import|from|def|class|return|if|for|while)\b|\s*[\w.]+\s*=[^=]")
MIN_DRAFT_WORDS = 4
FALLBACK_FRAGMENTS = 3
FALLBACK_CHARS = 600
# Por qué se elimina una frase.
BAD_TAG = "etiqueta"
UNKNOWN_NAME = "nombre"
UNKNOWN_FIGURE = "dato"
NOT_DEFINED = "definición"


@dataclass
class Fragment:
    tag: str
    label: str
    text: str
    origin: str = ""


@dataclass(frozen=True)
class Quote:
    path: str
    line: int
    label: str
    text: str
    origin: str = ""

    @property
    def cite(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


def parse_fragments(context: str) -> list:
    """Los fragmentos del contexto. La primera línea de text dice dónde vive, no es del archivo."""
    headers = list(FRAGMENT_HEADER.finditer(context))
    fragments = []

    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(context)
        head, _, text = context[header.end():end].partition("Contenido:\n")
        origin = next((line.removeprefix(ORIGIN_PREFIX) for line in head.splitlines() if line.startswith(ORIGIN_PREFIX)), "")
        fragments.append(Fragment(header.group(1), header.group(2) or "", text.strip(), origin))

    return fragments


def parse_quotes(response: str) -> list:
    """[(etiqueta o None, línea)] de la respuesta del modelo."""
    return [(tag, clean_quote(text)) for tag, text in QUOTE.findall(response)]


def quote_at(fragment: Fragment, number: int) -> Quote:
    """La línea number de fragment.text tal como está en el archivo, no como la copió el modelo."""
    text = fragment.text.splitlines()[number - 1].rstrip()
    first = FIRST_LINE.search(fragment.tag)

    if not first:
        return Quote(fragment.tag, None, fragment.label, text, fragment.origin)

    # number cuenta la primera línea de text, que no es del archivo.
    return Quote(fragment.tag[:first.start()], int(first.group(1)) + number - 2, fragment.label, text, fragment.origin)


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


def is_thin(answer: str) -> bool:
    """True si la redacción no llega a una frase: es solo una etiqueta o una línea de código."""
    text = BACKTICKED.sub(" ", FENCE.sub(" ", CITED_FILE.sub(" ", CITED_LINES.sub(" ", answer))))
    lines = [line for line in text.splitlines() if line.strip()]

    if len(WORD.findall(text)) < MIN_DRAFT_WORDS:
        return True

    return len(lines) == 1 and bool(CODE_LINE.match(lines[0]))


def without_tags(text: str) -> str:
    return CITED_FILE.sub(" ", CITED_LINES.sub(" ", text))


def prose_sentences(text: str):
    """Las frases de un tramo sin bloques de código; el número de una lista no acaba una frase."""
    for line in TAG_AFTER_END.sub(r"\2\1", text).splitlines():
        if line.strip():
            marker = LIST_MARKER.match(line).group()
            first, *rest = SENTENCE_END.split(line[len(marker):])
            yield marker + first
            yield from rest


def draft_sentences(answer: str) -> list:
    """Las frases de la redacción. Un bloque de código o una etiqueta suelta son de la frase de antes."""
    sentences = []

    def attach(text):
        if sentences:
            sentences[-1] += f"\n{text}"
        else:
            sentences.append(text)

    for i, part in enumerate(FENCE_BLOCK.split(answer)):
        if i % 2:
            attach(part)
            continue

        for sentence in prose_sentences(part):
            if WORD.search(without_tags(sentence)):
                sentences.append(sentence)
            else:
                attach(sentence)

    return sentences


def cited_lines(sentence: str, quotes: list) -> tuple:
    """(las líneas verificadas que cita la frase, sus etiquetas que no tocan ninguna)."""
    own, unverified = [], []

    for match in CITED_LINES.finditer(sentence):
        path, first, last = match.group(1), int(match.group(2)), int(match.group(3) or match.group(2))
        found = [quote for quote in quotes if quote.path == path and quote.line and first <= quote.line <= last]
        own += found

        if not found:
            unverified.append(match.group(0))

    own += [quote for quote in quotes if not quote.line and quote.path in CITED_FILE.findall(sentence)]
    return own, unverified


def is_identifier(word: str) -> bool:
    # Solo camelCase: "PowerShell" o "ChromaDB" son nombres, no código.
    return "_" in word or bool(CAMEL_CASE.match(word))


def unknown_names(answer: str, context: str) -> list:
    """Los archivos, el código y los identificadores de la redacción que no están en los fragmentos."""
    text = CITED_LINES.sub(" ", answer)
    code = [line for block in FENCE.findall(text) for line in block.splitlines() if line.strip()]
    text = FENCE.sub(" ", text)
    code += CITED_FILE.findall(text) + BACKTICKED.findall(text)
    known = squash(context)
    words = set(WORD.findall(context))

    # "os.replace()" nombra lo que el código llama con argumentos.
    unknown = [item.strip() for item in code if squash(item.strip(" .,:;").removesuffix("()")) not in known]
    unknown += [word for word in WORD.findall(BACKTICKED.sub(" ", text)) if is_identifier(word) and word not in words]
    # Palabra entera: "w" no está en "write".
    unknown += [item for item in DOUBLE_QUOTED.findall(text) if not re.search(rf"(?<!\w){re.escape(item)}(?!\w)", context)]
    return list(dict.fromkeys(unknown))


def prose_of(sentence: str) -> str:
    """La frase sin etiquetas, sin número de lista y sin código, que se comprueba como nombre."""
    text = BACKTICKED.sub(" ", FENCE.sub(" ", without_tags(sentence)))
    return LIST_MARKER.sub("", text, count=1)


def unknown_figures(sentence: str, own: list) -> list:
    """Los números que no están en las líneas citadas y las unidades de tiempo que esas líneas no dicen."""
    prose = prose_of(sentence)
    lines = "\n".join(quote.text for quote in own)
    known = set(NUMBER.findall(lines)) | {str(quote.line) for quote in own}
    unknown = [number for number in NUMBER.findall(prose) if number not in known]

    if not TIME_UNIT.search(lines):
        unknown += [f"{number} {unit}" for number, unit in TIMED.findall(prose)]

    return unknown


def is_defined(name: str, own: list) -> bool:
    name = re.escape(name)
    definition = rf"\b(?:def|class)\s+{name}\b|\b{name}[\"']?\s*[:=]"
    return any(re.search(definition, quote.text) for quote in own)


def undefined_names(sentence: str, own: list) -> list:
    """Los nombres que la frase dice definidos sin que ninguna línea citada los defina."""
    prose = prose_of(sentence)

    if not DEFINES.search(prose):
        return []

    names = [item.removesuffix("()") for item in BACKTICKED.findall(without_tags(sentence))]
    names = [name for name in names if WORD.fullmatch(name)]
    names += [word for word in WORD.findall(FILE_PATH.sub(" ", prose)) if is_identifier(word)]
    return [name for name in dict.fromkeys(names) if not is_defined(name, own)]


def sentence_problems(sentence: str, quotes: list) -> list:
    """[(motivo, detalle)] por los que la frase no se muestra. Se comprueba solo contra sus líneas citadas."""
    own, unverified = cited_lines(sentence, quotes)
    problems = [(BAD_TAG, tag) for tag in unverified]

    if not own:
        return problems or [(BAD_TAG, "sin etiqueta")]

    known = "\n".join(f"{quote.path} {quote.label} {quote.text}" for quote in own)
    problems += [(UNKNOWN_NAME, name) for name in unknown_names(sentence, known)]
    problems += [(UNKNOWN_FIGURE, figure) for figure in unknown_figures(sentence, own)]
    problems += [(NOT_DEFINED, name) for name in undefined_names(sentence, own)]
    return problems


def check_draft(answer: str, quotes: list) -> tuple:
    """(frases que se muestran, [(frase eliminada, sus problemas)])."""
    kept, removed = [], []

    for sentence in draft_sentences(answer):
        problems = sentence_problems(sentence, quotes)

        if problems:
            removed.append((sentence, problems))
        else:
            kept.append(sentence)

    return kept, removed


def block_of(run: list) -> str:
    """Un tramo de líneas seguidas: "core/brain.py:40-45 (Brain.process)" y su texto."""
    first, last = run[0], run[-1]
    cite = first.cite if first.line == last.line else f"{first.cite}-{last.line}"
    # En una página web, los números de línea no significan nada para quien lee.
    cite = first.origin or cite
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
            # Con la misma etiqueta: los bloques de un modelo numeran sus líneas por separado.
            run = next((r for r in runs if quote.line and r[-1].line == quote.line - 1 and r[-1].label == quote.label), None)

            if run:
                run.append(quote)
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
        place = f"[{fragment.origin or fragment.tag}] {fragment.label}".strip()
        blocks.append(f"{place}\n{text[:FALLBACK_CHARS]}{cut}")

    return f"{prompts.NO_DIRECT_ANSWER}\n\n" + "\n\n".join(blocks)
