"""Salidas de herramientas largas: al prompt va el principio y el resto a un archivo.

Idea de OpenCode (sst/opencode, MIT). Una búsqueda de texto de un nombre
común o un script que imprime mucho llenaban el contexto del modelo; antes se
cortaban (el sandbox) o entraban enteras (search_text). Ahora entra el
principio, en líneas completas, con un aviso de dónde está la salida entera.
Los archivos se borran a los RETENTION_DAYS días.
"""
import re
import time
from datetime import datetime

from core import paths

RETENTION_DAYS = 7
NOTICE = "[Salida recortada: {shown} de {total} líneas. Completa en {path}]"
UNSAFE = re.compile(r"[^\w-]+")


def clip(text: str, max_chars: int, label: str) -> str:
    """text si cabe en max_chars; si no, el principio y el aviso, con el texto entero guardado."""
    if not text or len(text) <= max_chars:
        return text

    head = text[:max_chars]

    # Líneas completas, salvo que la primera ya no quepa.
    if "\n" in head:
        head = head[:head.rindex("\n")]

    path = save_full(text, label)
    notice = NOTICE.format(shown=len(head.splitlines()), total=len(text.splitlines()), path=shown_path(path))
    return f"{head}\n{notice}"


def save_full(text: str, label: str):
    folder = paths.TOOL_OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    prune(folder)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = folder / f"{stamp}-{UNSAFE.sub('_', label)[:40]}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def prune(folder, now=None):
    """Borra las salidas de más de RETENTION_DAYS días."""
    limit = (now or time.time()) - RETENTION_DAYS * 86400

    for old in folder.glob("*.txt"):
        try:
            if old.stat().st_mtime < limit:
                old.unlink()
        except OSError:
            pass


def shown_path(path) -> str:
    """Relativa al proyecto si está dentro (data/salidas/...)."""
    try:
        return path.relative_to(paths.PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)
