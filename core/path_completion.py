"""Autocompletado de rutas al escribir @ en la CLI (prompt_toolkit).

path_completions no depende de prompt_toolkit; AttachmentCompleter lo adapta.
Las rutas se completan contra la carpeta del usuario (Session.get_user_cwd).
"""
import os
import re
from pathlib import Path


# Último @ruta (o @"ruta con espacios" sin cerrar) antes del cursor.
PARTIAL_PATTERN = re.compile(r'(?:^|\s)@("[^"]*|[^\s"]*)$')

MAX_COMPLETIONS = 50


def partial_attachment(text_before_cursor: str) -> str | None:
    """Lo escrito después del último @, o None si el cursor no está en un @ruta."""
    match = PARTIAL_PATTERN.search(text_before_cursor)
    return match.group(1) if match else None


def path_completions(partial: str, cwd: Path) -> list[str]:
    """Textos que reemplazan a partial: rutas que empiezan igual.

    Las carpetas terminan en "/" para seguir completando dentro. Una ruta con
    espacios va entre comillas. En Windows no se distingue mayúsculas.
    """
    raw = partial[1:] if partial.startswith('"') else partial
    folder_text, _, prefix = raw.replace("\\", "/").rpartition("/")
    folder_text = folder_text + "/" if folder_text or raw.startswith("/") else ""

    folder = Path(folder_text).expanduser() if folder_text else Path(".")

    if not folder.is_absolute():
        folder = cwd / folder

    try:
        entries = sorted(os.scandir(folder), key=lambda e: (not e.is_dir(), e.name.lower()))
    except OSError:
        return []

    fold = str.lower if os.name == "nt" else (lambda s: s)
    results = []

    for entry in entries:
        if not fold(entry.name).startswith(fold(prefix)):
            continue

        # Ocultos solo si el usuario empezó a escribir el punto.
        if entry.name.startswith(".") and not prefix.startswith("."):
            continue

        completed = folder_text + entry.name + ("/" if entry.is_dir() else "")

        if " " in completed or partial.startswith('"'):
            completed = f'"{completed}' + ("" if entry.is_dir() else '"')

        results.append(completed)

        if len(results) >= MAX_COMPLETIONS:
            break

    return results


def make_completer(get_cwd):
    """Completer de prompt_toolkit, o None si prompt_toolkit no está instalado."""
    try:
        from prompt_toolkit.completion import Completer, Completion
    except ImportError:
        return None

    class AttachmentCompleter(Completer):
        def get_completions(self, document, complete_event):
            partial = partial_attachment(document.text_before_cursor)

            if partial is None:
                return

            for text in path_completions(partial, get_cwd()):
                yield Completion(text, start_position=-len(partial))

    return AttachmentCompleter()
