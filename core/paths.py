"""Rutas absolutas de los datos internos de Asia.

Todo se calcula desde la raíz del proyecto, así que funciona igual sin
importar desde qué carpeta se ejecute Asia. Las rutas que da el usuario
("core/brain.py", ".") se siguen resolviendo contra su carpeta actual.
"""
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULTS_FILE = CONFIG_DIR / "defaults.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
APPS_FILE = CONFIG_DIR / "apps.json"

MEMORY_DIR = PROJECT_ROOT / "memory"
MEMORY_FILE = MEMORY_DIR / "memory.json"
PROJECTS_DIR = MEMORY_DIR / "projects"
PENDING_CHANGE_FILE = MEMORY_DIR / "pending_change.json"
BACKUPS_DIR = MEMORY_DIR / "backups"

DATA_DIR = PROJECT_ROOT / "data"
CHROMA_DIR = DATA_DIR / "chroma"


def has_ignored_part(path: Path, root: Path, ignored: set[str]) -> bool:
    """True si alguna parte de path, relativa a root, está en ignored.

    Se compara contra la ruta relativa para que analizar, por ejemplo, la
    carpeta "pruebas" no la descarte entera por llamarse como una ignorada.
    """
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts

    return any(part.lower() in ignored for part in parts)


def iter_files(root: Path, ignored: set[str]):
    """Recorre los archivos de root sin ENTRAR en las carpetas ignoradas.

    A diferencia de filtrar el resultado de rglob, no se listan node_modules,
    target, .git, etc., que en proyectos grandes tienen miles de archivos.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name.lower() not in ignored]

        for name in filenames:
            yield Path(dirpath) / name


def is_private_data(path: Path) -> bool:
    """True si path está dentro de la memoria o los datos internos de Asia."""
    resolved = path.resolve()
    return resolved.is_relative_to(MEMORY_DIR) or resolved.is_relative_to(DATA_DIR)
