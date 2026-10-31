"""Reflexión dentro de la sesión (fase R).

El resumen de la sesión se genera al cerrarla y se guarda en
data/reflexion/ultima_sesion.json: abrir Asia solo lee ese archivo y los
pendientes, sin esperar al modelo.
"""
import json
import re
from datetime import datetime

from core import paths
from core.atomic_write import write_json_atomic
from core.tasks import TaskList, numbered

SENTENCE_END = re.compile(r"(?<=[^\d\s][.!?…])\s+")
OPENING_SENTENCES = 2


def first_sentences(text: str, count: int) -> str:
    return " ".join(SENTENCE_END.split(text.strip())[:count])


def save_summary(text: str, source: str, messages: int):
    """source: "modelo" o "simple" (sin modelo, ver simple_summary)."""
    paths.SESSION_SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(paths.SESSION_SUMMARY_FILE, {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "resumen": text,
        "origen": source,
        "mensajes": messages,
    })


def load_summary():
    """El resumen guardado, o None si no hay o no se puede leer."""
    try:
        return json.loads(paths.SESSION_SUMMARY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def opening_text() -> str:
    """Lo que se muestra al abrir Asia; "" si no hay nada."""
    parts = []
    summary = load_summary()

    if summary and summary.get("resumen"):
        date = summary.get("fecha", "").replace("T", " ")[:16]
        parts.append(f"Sesión anterior ({date}): {first_sentences(summary['resumen'], OPENING_SENTENCES)}")

    try:
        tasks = TaskList().open_tasks()
    except (OSError, ValueError):
        tasks = []

    if tasks:
        parts.append(f"Pendientes:\n{numbered(tasks)}")

    return "\n".join(parts)
