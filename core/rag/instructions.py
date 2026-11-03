"""ASIA.md opcional en la raíz de una fuente: notas del usuario para el modelo sobre esa fuente.

Idea de OpenCode (AGENTS.md; sst/opencode, MIT). Si los fragmentos de /buscar
vienen de una fuente con ASIA.md (vocabulario, qué carpeta es qué), el modelo
lo ve en la extracción como notas, no como fragmentos: no se cita ni cuenta
para verificar citas.
"""
import re
from pathlib import Path

from core.provenance import PUBLICA, RAG, Fragment, record

FILE_NAME = "ASIA.md"
MAX_CHARS = 2000
# "Fuente: Bolitabot (proyecto)", la línea que escribe tools/rag_tool.py en cada fragmento.
SOURCE_LINE = re.compile(r"^Fuente: (.+) \([^()\n]*\)$", re.MULTILINE)


def read_notes(source) -> str:
    """El ASIA.md de la fuente, recortado a MAX_CHARS en líneas completas; "" si no tiene."""
    if source is None or not source.path:
        return ""

    path = Path(source.path) / FILE_NAME

    try:
        if not path.is_file():
            return ""

        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit("\n", 1)[0] + f"\n[{FILE_NAME} recortado en {MAX_CHARS} caracteres]"

    return text


def source_notes(context: str, sources: list) -> str:
    """Las notas de las fuentes que aparecen en el contexto, una vez cada una.

    Se anotan en la petición en curso con la etiqueta de la fuente: locales
    salvo que la fuente sea pública.
    """
    blocks = []

    for name in dict.fromkeys(SOURCE_LINE.findall(context)):
        source = next((s for s in sources if s.name == name), None)
        notes = read_notes(source)

        if notes:
            record(Fragment(PUBLICA if source.publica else RAG, notes))
            blocks.append(f"Fuente {name}:\n{notes}")

    return "\n\n".join(blocks)
