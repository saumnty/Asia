"""Un nombre de archivo suelto ("explica timing.py") se busca en la carpeta de Asia.

Por voz no se dicen las carpetas ("core barra timing punto py" se transcribe mal), y
un archivo que no está en la carpeta abierta daba "no existe". Con una sola
coincidencia se usa esa ruta; con varias, se pregunta cuál, como "¿Abro X? s/N" en
open_app: la pregunta vale solo para el mensaje siguiente.
"""
import os
import re
from pathlib import Path

# Lo que nunca es "el archivo" del que se habla: entornos, cachés y datos privados.
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "dist", "build", ".idea", ".vscode", "data", "memory", "logs",
}
MAX_MATCHES = 6
# Para que un nombre en la raíz de un disco no recorra miles de carpetas.
MAX_DIRS = 5000
BARE_NAME = re.compile(r"[^\\/:]+\.[A-Za-z0-9]{1,8}")
ORDINALS = {
    "1": 1, "uno": 1, "el uno": 1, "primero": 1, "el primero": 1, "la primera": 1, "primera": 1,
    "2": 2, "dos": 2, "el dos": 2, "segundo": 2, "el segundo": 2, "la segunda": 2, "segunda": 2,
    "3": 3, "tres": 3, "el tres": 3, "tercero": 3, "el tercero": 3, "la tercera": 3, "tercera": 3,
    "4": 4, "cuatro": 4, "el cuatro": 4, "cuarto": 4, "el cuarto": 4,
    "5": 5, "cinco": 5, "el cinco": 5, "quinto": 5, "el quinto": 5,
    "6": 6, "seis": 6, "el seis": 6, "sexto": 6, "el sexto": 6,
}
CANCEL = {"n", "no", "no gracias", "nada", "ninguno", "ninguna", "cancela", "cancelar", "dejalo", "olvidalo"}


def is_bare_name(value) -> bool:
    """"timing.py" sí; "core/timing.py", "C:\\x.py" o "timing" no."""
    return isinstance(value, str) and bool(BARE_NAME.fullmatch(value.strip()))


def find_named(root, name: str, limit: int = MAX_MATCHES + 1) -> list:
    """Rutas relativas a root (con "/") de los archivos que se llaman name, sin mirar mayúsculas.

    Las de menos carpetas primero, y luego por orden alfabético.
    """
    root = Path(root)
    wanted = name.strip().lower()
    found = []
    visited = 0

    for folder, dirs, files in os.walk(root):
        visited += 1
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        found += [Path(folder, f).relative_to(root).as_posix() for f in files if f.lower() == wanted]

        if visited >= MAX_DIRS:
            break

    found.sort(key=lambda path: (path.count("/"), path.lower()))
    return found[:limit]


def which_question(name: str, matches: list) -> str:
    options = "\n".join(f"  {number}. {path}" for number, path in enumerate(matches[:MAX_MATCHES], 1))
    more = f"\n  (y más; di la ruta si no está)" if len(matches) > MAX_MATCHES else ""
    return f"Hay varios {name}:\n{options}{more}\n¿Cuál? (número o no)"


def chosen(answer: str, matches: list):
    """La ruta elegida, False si dice que no, None si el mensaje es otra cosa."""
    from core.actions.models import command_text

    words = command_text(answer or "")
    number = ORDINALS.get(words)

    if number and number <= min(len(matches), MAX_MATCHES):
        return matches[number - 1]

    if words in CANCEL:
        return False

    # "core/timing.py" o "el de core": la única que lo contiene.
    plain = words.removeprefix("el de ").removeprefix("la de ").replace("\\", "/")
    named = [path for path in matches if plain and plain in path.lower()]
    return named[0] if len(named) == 1 else None
