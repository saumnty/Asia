"""La biblioteca: fuentes con nombre, una colección por fuente (fase H).

Cada fuente es un proyecto, un reporte o unas notas, en
data/biblioteca/fuentes.json. La búsqueda recorre todas, salvo que la pregunta
diga "en <fuente>".
"""
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime

from core import paths
from core.atomic_write import write_json_atomic
from core.rag.vector_store import safe_collection_name

KINDS = ("proyecto", "reporte", "notas")
DEFAULT_KIND = "proyecto"


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


def named_in_question(question: str, sources: list):
    """La fuente de "en <fuente>" en la pregunta, o None."""
    for source in sorted(sources, key=lambda s: -len(s.name)):
        pattern = rf"\ben\s+(?:la\s+fuente\s+|el\s+proyecto\s+|las\s+notas\s+|el\s+reporte\s+)?{re.escape(source.name)}\b"

        if re.search(pattern, question, re.IGNORECASE):
            return source

    return None


def citation(metadata: dict) -> str:
    """"core/brain.py, líneas 40–55". Los índices viejos no guardan líneas."""
    file_path = metadata.get("relative_path") or metadata.get("file_path", "archivo desconocido")
    start, end = metadata.get("start_line"), metadata.get("end_line")

    if not start:
        return file_path

    lines = f"línea {start}" if start == end else f"líneas {start}–{end}"
    return f"{file_path}, {lines}"
