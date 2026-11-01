"""La biblioteca: fuentes con nombre, una colección por fuente (fase H).

Cada fuente es un proyecto, un reporte o unas notas, en
data/biblioteca/fuentes.json. La búsqueda recorre todas, salvo que la pregunta
diga "en <fuente>".
"""
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from core import paths, prompts
from core.atomic_write import write_json_atomic
from core.rag.vector_store import safe_collection_name

KINDS = ("proyecto", "reporte", "notas")
DEFAULT_KIND = "proyecto"
CITE_PREFIX = "Cita: "


@dataclass
class Source:
    name: str
    kind: str
    path: str
    collection: str
    fragments: int = 0
    indexed: str = ""


class Library:
    def __init__(self, path=None):
        self.path = path or paths.SOURCES_FILE

    def all(self) -> list:
        if not self.path.exists():
            return []

        return [Source(**source) for source in json.loads(self.path.read_text(encoding="utf-8"))]

    def get(self, name: str):
        return next((s for s in self.all() if s.name.lower() == name.lower()), None)

    def save(self, name: str, kind: str, path: str, fragments: int) -> Source:
        """Añade la fuente o actualiza la que ya tiene ese nombre."""
        source = Source(
            name, kind, path, safe_collection_name(name), fragments,
            datetime.now().isoformat(timespec="seconds"),
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


def sources_footer(context: str, answer: str) -> str:
    """La lista "Fuentes:" de una respuesta, sacada de los fragmentos y no del modelo.

    Solo los archivos que la respuesta menciona; si no menciona ninguno, todos los
    consultados. Así una cita nunca es inventada. "" si la respuesta no usa fragmentos.
    """
    cites = list(dict.fromkeys(line.removeprefix(CITE_PREFIX) for line in context.splitlines() if line.startswith(CITE_PREFIX)))

    if not cites or prompts.NOT_FOUND.lower().rstrip(".") in answer.lower():
        return ""

    def mentioned(cite):
        return Path(cite.split(",")[0]).name.lower() in answer.lower()

    used = [cite for cite in cites if mentioned(cite)] or cites
    return "\n\nFuentes:\n" + "\n".join(f"- {cite}" for cite in used)


def citation(metadata: dict) -> str:
    """"core/brain.py, líneas 40–55". Los índices viejos no guardan líneas."""
    file_path = metadata.get("relative_path") or metadata.get("file_path", "archivo desconocido")
    start, end = metadata.get("start_line"), metadata.get("end_line")

    if not start:
        return file_path

    lines = f"línea {start}" if start == end else f"líneas {start}–{end}"
    label = f" ({metadata['label']})" if metadata.get("label") else ""
    return f"{file_path}, {lines}{label}"
