"""Procedencia del contenido que entra a un prompt (fase G, modo confidencial).

Cada fragmento lleva una etiqueta:

- "usuario": lo que el usuario tecleó. Siempre exportable.
- "memoria": memory.json (va entero en el prompt de sistema del chat).
  Exportable solo con external_allow_memory (por defecto false).
- "archivo", "adjunto", "rag", "proyecto": locales. Solo salen con una
  autorización de una sola vez.
- "emocional": nunca sale, ni con autorización. Reservada para uso futuro.

Las herramientas que leen contenido lo anotan en el registro de la
petición en curso (una ContextVar que abre Brain.process o el launcher);
el router lo consulta antes de llamar a un proveedor externo. Lo que llega
al router sin registro se trata como local: si se olvida etiquetar algo,
no sale.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

USUARIO = "usuario"
MEMORIA = "memoria"
ARCHIVO = "archivo"
ADJUNTO = "adjunto"
RAG = "rag"
PROYECTO = "proyecto"
EMOCIONAL = "emocional"
# Contenido que llegó al router sin registro de procedencia.
DESCONOCIDO = "desconocido"

LOCAL_LABELS = {ARCHIVO, ADJUNTO, RAG, PROYECTO, DESCONOCIDO}
NEVER_EXPORT = {EMOCIONAL}

# Orden de más a menos restrictiva, para heredar la más restrictiva.
RESTRICTIVENESS = [EMOCIONAL, DESCONOCIDO, ADJUNTO, ARCHIVO, RAG, PROYECTO, MEMORIA, USUARIO]

# Herramientas que devuelven contenido de archivos o del índice RAG.
TOOL_LABELS = {
    "read_file": ARCHIVO,
    "read_file_preview": ARCHIVO,
    "read_folder_context": ARCHIVO,
    "search_text": ARCHIVO,
    "search_files": ARCHIVO,
    "analyze_static": ARCHIVO,
    "analyze_folder_static": ARCHIVO,
    "select_project_files": ARCHIVO,
    "detect_dead_code": ARCHIVO,
    "review_project_files": ARCHIVO,
    "review_file_deep": ARCHIVO,
    "debug_project": ARCHIVO,
    "search_project_rag": RAG,
}


@dataclass(frozen=True)
class Fragment:
    label: str
    text: str


_current: ContextVar = ContextVar("asia_prompt_sources", default=None)


@contextmanager
def request_sources(*fragments: Fragment):
    """Abre el registro de una petición (un mensaje del usuario).

    Si ya hay uno abierto (el launcher lo abre y Brain.process vuelve a
    entrar), se reutiliza: los fragmentos de las dos capas se suman.
    """
    if _current.get() is not None:
        record(*fragments)
        yield _current.get()
        return

    token = _current.set(list(fragments))

    try:
        yield _current.get()
    finally:
        _current.reset(token)


def record(*fragments: Fragment):
    """Anota fragmentos en la petición en curso (sin registro abierto, nada)."""
    current = _current.get()

    if current is not None:
        current.extend(f for f in fragments if f.text)


def record_tool_result(action: str, result):
    label = TOOL_LABELS.get(action)

    if label and isinstance(result, str):
        record(Fragment(label, result))


def current_fragments() -> list[Fragment] | None:
    """Fragmentos de la petición en curso, o None si no hay registro."""
    current = _current.get()
    return None if current is None else list(current)


def labels_of(fragments) -> set[str]:
    if fragments is None:
        return {DESCONOCIDO}

    return {f.label for f in fragments}


def chars_by_label(fragments) -> dict[str, int]:
    counts = {}

    for f in fragments or []:
        counts[f.label] = counts.get(f.label, 0) + len(f.text)

    return counts


def most_restrictive(labels) -> str:
    labels = set(labels) or {USUARIO}

    for label in RESTRICTIVENESS:
        if label in labels:
            return label

    return DESCONOCIDO


def exportable_labels(settings) -> set[str]:
    """Etiquetas que pueden salir sin autorización."""
    labels = {USUARIO}

    if settings.get("external_allow_memory", False):
        labels.add(MEMORIA)

    return labels


def local_labels(labels, settings) -> set[str]:
    """Las etiquetas de labels que no pueden salir sin autorización."""
    return set(labels) - exportable_labels(settings)
