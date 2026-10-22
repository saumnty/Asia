"""Contexto de debug_project con presupuesto de tokens, y citas comprobadas.

Antes, debug_project juntaba 7 búsquedas y los primeros 25 archivos del
recorrido: en C:\\Asia eran ~19 500 tokens, más que ollama_num_ctx=16384, y
Ollama descartaba el principio del prompt (las instrucciones y el problema).
Ahora los archivos se ordenan por coincidencias, se agregan mientras quepan
y los que no caben se nombran en el reporte. El problema va al principio y
también al final del prompt: si algo se recortara, el final se conserva.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.paths import iter_files
from providers.ollama_provider import CHARS_PER_TOKEN, RESPONSE_RESERVE_TOKENS
from tools.review_findings import clean_quote, locate_quote

# Búsquedas fijas que ya hacía debug_project, para bugs de respuestas None,
# duplicadas o impresas en la terminal.
GENERIC_SEARCHES = [
    "return None",
    "print(",
    "provider_router.ask",
    "brain.process",
    "generate_code",
    "apply_change",
]

# Líneas de evidencia por término y largo máximo de cada una.
EVIDENCE_LINES_PER_TERM = 8
EVIDENCE_LINE_CHARS = 160

# Parte del espacio libre que pueden ocupar las líneas de evidencia; el
# resto queda para el contenido de los archivos.
EVIDENCE_SHARE = 0.35

MAX_CHARS_PER_FILE = 1200

# Líneas de contexto alrededor de cada coincidencia, y lo que suma el prefijo
# "123 | " y el salto de línea a cada una.
SNIPPET_RADIUS = 3
SNIPPET_LINE_OVERHEAD = 10

# Tope propio del prompt (context_limits.debug_project_tokens), además de
# ollama_num_ctx: con el prompt entero de ~15 000 tokens qwen2.5-coder:7b
# tardaba 330 s y no seguía el formato pedido.
DEFAULT_PROMPT_TOKENS = 6000
TRUNCATED_MARK = "\n... [archivo recortado]"

# Archivos omitidos que se nombran en el reporte; del resto solo el número.
MAX_OMITTED_LISTED = 10

IDENTIFIER = re.compile(r"[A-Za-z_][\w.]*")


def issue_terms(issue: str) -> list[str]:
    """Palabras del problema que parecen código: None, ProviderRouter, main.py.

    Cuentan las que tienen mayúscula, dígito, "_" o "."; la primera palabra
    no, porque suele ser el verbo con mayúscula inicial ("Encuentra...").
    """
    terms = []

    for word in IDENTIFIER.findall(issue)[1:]:
        word = word.rstrip(".")

        if len(word) >= 3 and any(c.isupper() or c.isdigit() or c in "_." for c in word):
            terms.append(word)

    return list(dict.fromkeys(terms))


@dataclass
class FileHits:
    relative: str
    content: str
    issue_hits: int = 0
    generic_hits: int = 0
    lines: dict = field(default_factory=dict)

    @property
    def issue_terms_found(self) -> int:
        return sum(1 for term in self.lines if term not in GENERIC_SEARCHES)

    @property
    def total(self) -> int:
        return self.issue_hits + self.generic_hits


def scan(base: Path, terms: list[str], ignored_dirs, extensions) -> list[FileHits]:
    """Archivos de base con las líneas donde aparece cada término.

    Ordenados por cuántos términos distintos del problema aparecen (un
    archivo con "Asia" y "None" antes que uno con 150 "return None"), después
    por coincidencias con el problema, por las búsquedas fijas y por ruta.
    """
    issue = set(terms) - set(GENERIC_SEARCHES)
    files = []

    for path in iter_files(base, ignored_dirs):
        if path.suffix.lower() not in extensions:
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        hits = FileHits(relative=path.relative_to(base).as_posix(), content=content)

        for number, line in enumerate(content.splitlines(), start=1):
            lowered = line.lower()

            for term in terms:
                if term.lower() in lowered:
                    hits.lines.setdefault(term, []).append((number, line.strip()))

                    if term in issue:
                        hits.issue_hits += 1
                    else:
                        hits.generic_hits += 1

        files.append(hits)

    return sorted(files, key=lambda f: (-f.issue_terms_found, -f.issue_hits, -f.generic_hits, f.relative))


def evidence_lines(files: list[FileHits], terms: list[str]) -> list[str]:
    lines = []

    for term in terms:
        found = [
            f"{f.relative}:{number}: {text[:EVIDENCE_LINE_CHARS]}"
            for f in files
            for number, text in f.lines.get(term, [])
        ][:EVIDENCE_LINES_PER_TERM]

        lines.append(f"--- Búsqueda: {term} ---")
        lines += found or ["(sin coincidencias)"]

    return lines


def snippet_lines(f: FileHits) -> list[int]:
    """Números de línea a mostrar: SNIPPET_RADIUS alrededor de cada
    coincidencia, primero las del problema, hasta MAX_CHARS_PER_FILE."""
    lines = f.content.splitlines()
    issue = [n for term, hits in f.lines.items() if term not in GENERIC_SEARCHES for n, _ in hits]
    generic = [n for term, hits in f.lines.items() if term in GENERIC_SEARCHES for n, _ in hits]
    chosen = set()
    used = 0

    for hit in dict.fromkeys(issue + generic):
        window = range(max(1, hit - SNIPPET_RADIUS), min(len(lines), hit + SNIPPET_RADIUS) + 1)
        new = [n for n in window if n not in chosen]
        cost = sum(len(lines[n - 1]) + SNIPPET_LINE_OVERHEAD for n in new)

        if used + cost > MAX_CHARS_PER_FILE:
            continue

        chosen.update(new)
        used += cost

    return sorted(chosen)


def file_chunk(f: FileHits) -> str:
    """Fragmentos numerados alrededor de las coincidencias.

    Antes iban los primeros 1200 caracteres: en archivos largos, el código
    que coincidía con el problema quedaba fuera. Sin coincidencias, el
    principio del archivo.
    """
    numbers = snippet_lines(f)

    if not numbers:
        content = f.content

        if len(content) > MAX_CHARS_PER_FILE:
            content = content[:MAX_CHARS_PER_FILE] + TRUNCATED_MARK

        return f"\n--- Archivo: {f.relative} ({f.total} coincidencias) ---\n{content}"

    lines = f.content.splitlines()
    width = len(str(numbers[-1]))
    shown = []

    for previous, number in zip([None] + numbers, numbers):
        if previous is not None and number != previous + 1:
            shown.append("...")

        shown.append(f"{number:>{width}} | {lines[number - 1]}")

    return (
        f"\n--- Archivo: {f.relative} ({f.total} coincidencias; "
        f"fragmentos alrededor de ellas, con número de línea) ---\n" + "\n".join(shown)
    )


@dataclass
class DebugContext:
    prompt: str
    files: list[FileHits]
    included: list[str]
    omitted: list[str]
    limit_tokens: int
    limit_name: str


def prompt_limit(settings) -> tuple[int, str]:
    """Tokens que pueden ocupar los mensajes (sistema + prompt) y de dónde sale
    el límite: ollama_num_ctx menos la reserva de respuesta, o el tope propio."""
    room = settings.get("ollama_num_ctx") - RESPONSE_RESERVE_TOKENS
    own = settings.get("context_limits", {}).get("debug_project_tokens", DEFAULT_PROMPT_TOKENS)

    if own < room:
        return own, "context_limits.debug_project_tokens"

    return room, "ollama_num_ctx"


def prompt_budget_chars(limit_tokens: int, system_chars: int) -> int:
    """Caracteres del prompt para que, con el de sistema, la estimación del
    provider (CHARS_PER_TOKEN) no pase de limit_tokens."""
    return int(limit_tokens * CHARS_PER_TOKEN) - system_chars


def build_debug_context(issue, base: Path, settings, render, system_chars=0) -> DebugContext:
    """render(evidence, context) arma el prompt; aquí se decide qué entra.

    Primero las líneas de evidencia (hasta EVIDENCE_SHARE del espacio libre),
    después los archivos con coincidencias en orden, mientras quepan.
    """
    limit_tokens, limit_name = prompt_limit(settings)
    words = issue_terms(issue)
    terms = words + [s for s in GENERIC_SEARCHES if s not in words]

    # Solo código y sin carpetas de pruebas: el golden JSON, las pruebas y el
    # ROADMAP tenían más coincidencias que el código y llenaban el prompt.
    files = scan(base, terms, settings.ignored_dirs(include_tests=True), settings.code_extensions())

    budget = prompt_budget_chars(limit_tokens, system_chars)
    free = budget - len(render("", ""))

    evidence = []
    used = 0

    for line in evidence_lines(files, terms):
        if used + len(line) + 1 > free * EVIDENCE_SHARE:
            break

        evidence.append(line)
        used += len(line) + 1

    evidence_text = "\n".join(evidence)
    free -= len(evidence_text)

    with_hits = [f for f in files if f.total] or files
    chunks, included, omitted = [], [], []

    for f in with_hits:
        chunk = file_chunk(f)

        if len(chunk) + 1 <= free:
            chunks.append(chunk)
            included.append(f.relative)
            free -= len(chunk) + 1
        else:
            omitted.append(f.relative)

    return DebugContext(
        prompt=render(evidence_text, "\n".join(chunks)),
        files=files,
        included=included,
        omitted=omitted,
        limit_tokens=limit_tokens,
        limit_name=limit_name,
    )


def context_note(ctx: DebugContext) -> str:
    note = f"Archivos leídos ({len(ctx.included)}, por coincidencias con el problema): {', '.join(ctx.included) or 'ninguno'}."

    if ctx.omitted:
        listed = ", ".join(ctx.omitted[:MAX_OMITTED_LISTED])
        more = len(ctx.omitted) - MAX_OMITTED_LISTED
        note += (
            f"\nOmitidos por el límite de contexto ({ctx.limit_name}, {ctx.limit_tokens} tokens): "
            f"{len(ctx.omitted)} archivos con coincidencias: {listed}"
            + (f" y {more} más." if more > 0 else ".")
        )

    return note


# --- Citas de la sección EVIDENCIA ------------------------------------------

SECTION = re.compile(
    r"^[\s*#]*(SUMMARY|SUSPECT_FILES|LIKELY_CAUSE|EVIDENCIA|RECOMMENDED_NEXT_STEP)[\s*]*:?[\s*]*$",
    re.IGNORECASE | re.MULTILINE,
)
# "ruta | cita" (lo pedido) o "ruta:línea: cita" (el formato de las líneas
# de evidencia, que el modelo copia a menudo), con viñeta o número delante.
BULLET = r"^\s*(?:[*\-]|\d+[.)])?\s*`?"
CITATION = re.compile(BULLET + r"([^\s|`]+?)`?(?::(\d+))?\s*\|\s*(.+)$")
COLON_CITATION = re.compile(BULLET + r"([^\s|`:]+):(\d+):\s*(.+)$")
# "ruta:línea" sola, con la cita en la línea siguiente.
PATH_ONLY = re.compile(BULLET + r"([^\s|`:]+):(\d+)`?:?\s*$")


def join_split_citations(lines: list[str]) -> list[str]:
    joined = []

    for line in lines:
        previous = PATH_ONLY.match(joined[-1]) if joined else None

        if previous and not PATH_ONLY.match(line):
            joined[-1] = f"{previous.group(1)}:{previous.group(2)}: {line.strip()}"
        else:
            joined.append(line)

    return joined


def find_file(raw: str, files: list[FileHits]) -> FileHits | None:
    wanted = raw.replace("\\", "/").lstrip("./").lower()

    for f in files:
        relative = f.relative.lower()

        if relative == wanted or wanted.endswith("/" + relative) or relative.endswith("/" + wanted):
            return f

    return None


def check_citation(line: str, files: list[FileHits]) -> str:
    match = CITATION.match(line) or COLON_CITATION.match(line)

    if not match:
        return f"{line.strip()}  [sin formato ruta | cita: no comprobada]"

    raw_path, hint, quote = match.group(1), match.group(2), clean_quote(match.group(3))
    f = find_file(raw_path, files)

    if f is None:
        return f"- {raw_path} | {quote}  [el archivo no está entre los analizados: descartada]"

    number = locate_quote(quote, f.content, int(hint) if hint else None)

    if number is None:
        return f"- {f.relative} | {quote}  [la cita NO está en el archivo: descartada]"

    return f"- {f.relative}:{number} | {quote}  [cita encontrada en el archivo]"


def verify_citations(response: str, files: list[FileHits]) -> str:
    """Comprueba sin LLM cada cita de EVIDENCIA contra el archivo completo.

    Las que no existen quedan marcadas como descartadas; el resto del
    diagnóstico no se comprueba.
    """
    sections = list(SECTION.finditer(response))
    evidence = next((s for s in sections if s.group(1).upper() == "EVIDENCIA"), None)

    if evidence is None:
        return response + "\n\nEVIDENCIA (comprobada sin LLM):\nel modelo no citó líneas; no hay nada comprobado."

    following = [s.start() for s in sections if s.start() > evidence.start()]
    end = following[0] if following else len(response)
    lines = join_split_citations([line for line in response[evidence.end():end].splitlines() if line.strip()])
    checked = [check_citation(line, files) for line in lines] or ["el modelo no citó líneas; no hay nada comprobado."]

    return (
        response[:evidence.start()].rstrip()
        + "\n\nEVIDENCIA (cada cita comprobada sin LLM contra el archivo):\n"
        + "\n".join(checked)
        + "\n\n"
        + response[end:].lstrip("\n")
    ).rstrip()
