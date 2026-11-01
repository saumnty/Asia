"""La biblioteca: fuentes con nombre, una colección por fuente (fase H).

Cada fuente es un proyecto, un reporte o unas notas, en
data/biblioteca/fuentes.json. La búsqueda recorre todas, salvo que la pregunta
diga "en <fuente>".
"""
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath

from core import paths
from core.atomic_write import write_json_atomic
from core.rag.tokens import without_accents
from core.rag.vector_store import safe_collection_name

KINDS = ("proyecto", "reporte", "notas", "documentacion")
DEFAULT_KIND = "proyecto"
LANGUAGES = ("es", "en")
DEFAULT_LANGUAGE, ENGLISH_SOURCE = LANGUAGES
ORIGIN_PREFIX = "Página: "
FRAGMENT_HEADER = re.compile(r"^--- \[(.+?)\](?: (.+))? ---$", re.MULTILINE)
REFUSAL = re.compile(
    r"\bno (lo |la |se )?(encontr|encuentr|hay informacion|tengo informacion|dispongo|puedo (responder|determinar))"
    r"|fragmentos( \w+)? no (responden|contienen|mencionan|incluyen|dicen|hablan|tienen)"
)
# Con esto ya hay algo de contenido: es una respuesta parcial.
PARTIAL = re.compile(r"\[[^\]]+:\d|\bpero\b|\bsin embargo\b")
MAX_TRANSLATION_CHARS = 300
REFUSAL_MAX_CHARS = 300
REFUSAL_OPENING = 150


@dataclass
class Source:
    name: str
    kind: str
    path: str
    collection: str
    fragments: int = 0
    indexed: str = ""
    # Para documentación con página pública: "https://docs.ros.org/en/jazzy/{}.html".
    url: str = ""
    license: str = ""
    # Solo se consulta con "en <fuente>".
    named_only: bool = False
    language: str = DEFAULT_LANGUAGE


class Library:
    def __init__(self, path=None):
        self.path = path or paths.SOURCES_FILE

    def all(self) -> list:
        if not self.path.exists():
            return []

        return [Source(**source) for source in json.loads(self.path.read_text(encoding="utf-8"))]

    def get(self, name: str):
        return next((s for s in self.all() if s.name.lower() == name.lower()), None)

    def save(
        self, name: str, kind: str, path: str, fragments: int, url: str = "", license: str = "",
        named_only: bool = False, language: str = DEFAULT_LANGUAGE,
    ) -> Source:
        """Añade la fuente o actualiza la que ya tiene ese nombre."""
        source = Source(
            name, kind, path, safe_collection_name(name), fragments,
            datetime.now().isoformat(timespec="seconds"), url, license, named_only, language,
        )
        sources = [s for s in self.all() if s.name.lower() != name.lower()] + [source]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, [asdict(s) for s in sources])
        return source


def source_pattern(source) -> str:
    return rf"\ben\s+(?:la\s+fuente\s+|el\s+proyecto\s+|las\s+notas\s+|el\s+reporte\s+)?{re.escape(source.name)}\b"


def named_in_question(question: str, sources: list):
    """La fuente de "en <fuente>" en la pregunta, o None."""
    for source in sorted(sources, key=lambda s: -len(s.name)):
        if re.search(source_pattern(source), question, re.IGNORECASE):
            return source

    return None


def without_source(question: str, source) -> str:
    """La pregunta sin "en <fuente>": el nombre de la fuente no es lo que se busca."""
    return " ".join(re.sub(source_pattern(source), " ", question, flags=re.IGNORECASE).split())


def searched_sources(question: str, sources: list) -> list:
    """Las fuentes que consulta una pregunta: la de "en <fuente>" o todas las generales."""
    named = named_in_question(question, sources)
    return [named] if named else [source for source in sources if not source.named_only]


def needs_translation(question: str, sources: list) -> bool:
    """True si consulta una fuente en inglés. Un nombre suelto se dice igual en los dos idiomas."""
    is_english = any(source.language == ENGLISH_SOURCE for source in searched_sources(question, sources))
    return is_english and len(question.split()) > 1


def clean_translation(answer: str) -> str:
    """La primera línea de la traducción del modelo, sin comillas. Vacía si no parece una pregunta."""
    lines = [line.strip(" \t\"'`*") for line in answer.splitlines() if line.strip()]
    return lines[0] if lines and len(lines[0]) <= MAX_TRANSLATION_CHARS else ""


def is_refusal(answer: str) -> bool:
    """True si la respuesta entera es una negativa, no si le falta una parte."""
    text = without_accents(answer.strip().lower())

    if len(text) > REFUSAL_MAX_CHARS or PARTIAL.search(text):
        return False

    return bool(REFUSAL.search(text[:REFUSAL_OPENING]))


def citation(metadata: dict) -> str:
    """"core/brain.py:40-55". Los índices viejos no guardan líneas."""
    file_path = metadata.get("relative_path") or metadata.get("file_path", "archivo desconocido")
    start, end = metadata.get("start_line"), metadata.get("end_line")

    if not start:
        return file_path

    return f"{file_path}:{start}" if start == end else f"{file_path}:{start}-{end}"


def origin_of(relative_path: str, url: str, license: str) -> str:
    """La página pública de un archivo: "https://.../Tutorials/Foo.html · CC BY 4.0"."""
    if not url:
        return ""

    page = url.format(PurePosixPath(relative_path).with_suffix("").as_posix())
    return f"{page} · {license}" if license else page


def fragment_header(metadata: dict) -> str:
    """"--- [core/brain.py:40-55] Brain.process ---": la etiqueta que cita el modelo."""
    label = f" {metadata['label']}" if metadata.get("label") else ""
    return f"--- [{citation(metadata)}]{label} ---"
