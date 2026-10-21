"""Hallazgos de revisión con cita verificable.

El LLM devuelve cada hallazgo con línea, cita literal y claim. Aquí, sin LLM,
se comprueba que la cita exista en el archivo, se corrige la línea con la
real y se eliminan los repetidos. En las pruebas con qwen2.5-coder:7b los
hallazgos sin cita real eran inventados y los repetidos inflaban el reporte.
"""
import re
from difflib import SequenceMatcher


NO_FINDINGS_MARK = "SIN_HALLAZGOS"

# Una cita más corta (sin espacios) coincide con casi cualquier archivo.
MIN_QUOTE_CHARS = 8

# Claims con este parecido (0..1) sobre la misma línea se toman como repetidos.
SIMILAR_CLAIM_RATIO = 0.8

# Con "si no hay problemas responde solo SIN_HALLAZGOS" al final, el modelo
# respondía eso siempre, sin revisar. Pedir primero un análisis línea por
# línea lo obliga a mirar el código antes de decidir.
FINDING_FORMAT = f"""Responde en dos partes.

ANALISIS:
recorre el archivo de arriba abajo y piensa, para cada operación, qué pasa si falla o si los datos son extremos.

HALLAZGOS:
un bloque como este por cada problema real que encontraste en el análisis:

HALLAZGO:
LINEA: número de línea
CITA: una línea copiada literalmente del archivo, sin el número de línea
CLAIM: qué falla, en qué caso concreto y por qué

Si el análisis no encontró ninguno, termina con {NO_FINDINGS_MARK}."""

HONESTY_RULES = """Reglas:
- "No encontré problemas" es una respuesta válida y preferible a inventar uno.
- Cada hallazgo debe citar una línea que exista en el archivo. Sin cita, no hay hallazgo.
- Un hallazgo solo vale si puedes describir el caso concreto en que falla.
- No repitas el mismo hallazgo con otras palabras.
- No reportes estilo, nombres ni logging como bugs.

Ejemplos de hallazgos FALSOS que no debes reportar:
- "moda = df[col].mode().iloc[0]" dentro de "if df[col].isnull().any():" no falla por falta de faltantes: el if ya garantiza que la columna tiene faltantes.
- "meta[col]" dentro de "for col in meta.names():" no lanza KeyError: la clave sale del mismo objeto que se indexa.
- "df[col]" dentro de "for col in df.columns:" no lanza KeyError por la misma razón."""


def numbered(content: str) -> str:
    """Contenido con número de línea, para que el LLM cite la línea correcta."""
    lines = content.splitlines()
    width = len(str(len(lines)))
    return "\n".join(
        f"{number:>{width}} | {line}"
        for number, line in enumerate(lines, start=1)
    )


def squash(text: str) -> str:
    """Texto sin espacios: la cita se compara sin importar la indentación."""
    return re.sub(r"\s+", "", text)


def clean_quote(quote: str) -> str:
    quote = quote.strip().strip("`").strip()

    # El LLM a veces copia también el prefijo "19 | " de numbered().
    quote = re.sub(r"^\d+\s*\|\s?", "", quote)

    if len(quote) >= 2 and quote[0] == quote[-1] and quote[0] in "\"'":
        quote = quote[1:-1]

    return quote.strip()


# Inicio de un hallazgo: un bloque "HALLAZGO:" o un elemento de lista
# numerada, que es lo que qwen2.5-coder:7b escribe a menudo en su lugar.
ITEM_START = re.compile(r"^[\s*#>-]*(HALLAZGO\b[^\n]*|\d+[.)]\s[^\n]*)$", re.IGNORECASE | re.MULTILINE)
FINDINGS_HEADER = re.compile(r"^[\s*#]*HALLAZGOS[\s*]*:?[\s*]*$", re.IGNORECASE | re.MULTILINE)
FIELD = re.compile(r"^[\s*\-]*(L[IÍ]NEA|CITA|CLAIM)[\s*]*:[\s*]*(.*)$", re.IGNORECASE)


def parse_item(item: str) -> dict | None:
    fields = {}
    current = None
    loose = []

    for line in item.splitlines():
        match = FIELD.match(line)

        if match:
            current = match.group(1).upper().replace("Í", "I")
            fields[current] = match.group(2).strip()
        elif current and line.strip():
            fields[current] += "\n" + line.strip()
        else:
            loose.append(line)

    text = "\n".join(loose)
    line_match = re.search(r"\d+", fields.get("LINEA", "")) or re.search(
        r"l[ií]nea\W{0,3}(\d+)", item, re.IGNORECASE
    )
    quote = fields.get("CITA", "")

    # Sin campo CITA, la cita es el primer bloque de código o `fragmento`.
    if not quote:
        code = re.search(r"```\w*\n(.*?)```", item, re.DOTALL) or re.search(r"`([^`\n]+)`", text)
        quote = code.group(1) if code else ""

    claim = fields.get("CLAIM", "")

    if not claim:
        claim = re.sub(r"```.*?```|`[^`\n]+`", "", text, flags=re.DOTALL)
        claim = re.sub(r"^[\s*#>-]*(HALLAZGO\b\W*|\d+[.)]\s*)", "", claim.strip(), flags=re.IGNORECASE)
        claim = re.sub(r"\*\*l[ií]nea\W{0,3}\d+\W*\*\*\s*:?", "", claim, flags=re.IGNORECASE)
        claim = " ".join(claim.split()).strip(" :-")

    quote = clean_quote(quote)
    claim = claim.strip()

    if not (claim or quote):
        return None

    return {
        "line": int(line_match.group(line_match.lastindex or 0)) if line_match else None,
        "quote": quote,
        "claim": claim,
    }


def parse_findings(response: str) -> list[dict]:
    """Hallazgos del LLM como [{"line", "quote", "claim"}].

    Acepta los bloques HALLAZGO pedidos y también listas numeradas con la
    cita entre backticks. Si hay una sección HALLAZGOS después del análisis,
    solo se lee esa: el análisis enumera también lo que el modelo descartó.
    """
    headers = list(FINDINGS_HEADER.finditer(response))

    if headers:
        response = response[headers[-1].end():]

    starts = [match.start() for match in ITEM_START.finditer(response)]
    findings = []

    for start, end in zip(starts, starts[1:] + [len(response)]):
        finding = parse_item(response[start:end])

        if finding:
            findings.append(finding)

    return findings


def locate_quote(quote: str, content: str, hint: int | None = None) -> int | None:
    """Línea (1..n) donde está la cita, comparando sin espacios.

    Si la cita aparece varias veces, se elige la más cercana a la línea que
    dio el LLM. La cita puede abarcar varias líneas.
    """
    target = squash(quote)

    if len(target) < MIN_QUOTE_CHARS:
        return None

    squashed = ""
    line_of_char = []

    for number, line in enumerate(content.splitlines(), start=1):
        part = squash(line)
        squashed += part
        line_of_char.extend([number] * len(part))

    matches = [
        line_of_char[match.start()]
        for match in re.finditer(re.escape(target), squashed)
    ]

    if not matches:
        return None

    if hint is None:
        return matches[0]

    return min(matches, key=lambda number: abs(number - hint))


def is_duplicate(finding: dict, kept: list[dict]) -> bool:
    claim = squash(finding["claim"].lower())

    quote = squash(finding["quote"])

    for other in kept:
        if quote and quote == squash(other["quote"]):
            return True

        other_claim = squash(other["claim"].lower())

        if claim and SequenceMatcher(None, claim, other_claim).ratio() >= SIMILAR_CLAIM_RATIO:
            return True

    return False


def verify_findings(findings: list[dict], content: str) -> dict:
    """Separa hallazgos verificados (cita encontrada) y descartados.

    Los verificados llevan la línea real de la cita; los repetidos se
    eliminan, tanto entre verificados como entre los no verificados.
    """
    verified = []
    unverified = []
    discarded = 0
    duplicates = 0

    for finding in findings:
        line = locate_quote(finding["quote"], content, finding["line"])
        target = verified if line is not None else unverified

        if line is None:
            discarded += 1
        finding = {**finding, "line": line if line is not None else finding["line"]}

        if is_duplicate(finding, target):
            duplicates += 1
            continue

        target.append(finding)

    return {
        "verified": verified,
        "unverified": unverified,
        "discarded": discarded,
        "duplicates": duplicates,
    }


def format_finding(number: int, finding: dict) -> str:
    line = finding["line"] if finding["line"] is not None else "?"
    claim = finding["claim"].replace("\n", "\n   ")
    return f"{number}. Línea {line}: `{finding['quote']}`\n   {claim}"


def render_report(file_path: str, response: str, content: str, show_unverified=False) -> str:
    """Reporte de un archivo a partir de la respuesta del LLM."""
    result = verify_findings(parse_findings(response), content)
    verified = result["verified"]
    unverified = result["unverified"]

    parts = [f"FILE: {file_path}", "", "VERIFICADO (cita encontrada):"]

    if verified:
        parts += [format_finding(n, f) for n, f in enumerate(verified, start=1)]
    else:
        parts.append("No encontré problemas verificables.")

    if show_unverified and unverified:
        parts += ["", "SIN VERIFICAR (cita no encontrada en el archivo):"]
        parts += [format_finding(n, f) for n, f in enumerate(unverified, start=1)]

    parts += [
        "",
        f"Descartados por cita no encontrada: {result['discarded']}",
        f"Duplicados eliminados: {result['duplicates']}",
    ]

    return "\n".join(parts)
