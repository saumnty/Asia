"""Qué nunca entra a la biblioteca, aunque la ruta lo incluya.

- Los datos de Asia: data/, memory/, logs/ y config/settings.json.
- Secretos: .env, claves (*.key, *.pem, id_rsa...).
- Lo que el .gitignore de la fuente ignora (el de la raíz y los de subcarpetas).
- Binarios y archivos de más de 1 MB. Un modelo de Simulink (.slx) es binario,
  pero entra si es un zip de verdad: de él solo se lee código (core/rag/simulink.py).

El .gitignore se interpreta aquí, sin git ni paquetes: una fuente puede no ser
un repositorio.
"""
import fnmatch
import os
import re
from pathlib import Path

from core import paths
from core.rag.simulink import is_model, is_model_name

MAX_FILE_BYTES = 1024 * 1024
BINARY_SAMPLE = 8192

SECRET_NAMES = {".env", ".envrc", ".npmrc", ".pypirc", ".netrc", "credentials", "credentials.json", "secrets.json"}
SECRET_PATTERNS = (
    ".env.*", "*.env", "*.key", "*.pem", "*.p12", "*.pfx", "*.crt", "*.cer", "*.der", "*.keystore", "*.jks",
    "*.asc", "*.gpg", "*.ppk", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
)


def is_asia_data(path: Path) -> bool:
    """data/, memory/, logs/ y config/settings.json de esta instalación de Asia."""
    resolved = path.resolve()

    return (
        paths.is_private_data(resolved)
        or resolved.is_relative_to(paths.LOGS_DIR)
        or resolved == paths.SETTINGS_FILE
    )


def is_secret(path: Path) -> bool:
    name = path.name.lower()
    return name in SECRET_NAMES or any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_PATTERNS)


def is_binary(path: Path) -> bool:
    with open(path, "rb") as f:
        return b"\0" in f.read(BINARY_SAMPLE)


def too_large(path: Path) -> bool:
    return path.stat().st_size > MAX_FILE_BYTES


def glob_to_regex(pattern: str) -> str:
    """Una línea de .gitignore (sin ! ni / final) como expresión sobre la ruta relativa."""
    anchored = "/" in pattern
    pattern = pattern.lstrip("/")
    out = ""
    i = 0

    while i < len(pattern):
        if pattern[i:i + 3] == "**/":
            out += "(?:.*/)?"
            i += 3
        elif pattern[i:i + 3] == "/**":
            out += "/.*"
            i += 3
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1

    return out if anchored else f"(?:.*/)?{out}"


class GitIgnore:
    """Las reglas de un .gitignore, relativas a su carpeta. Gana la última que coincide."""

    def __init__(self, text: str):
        self.rules = []

        for line in text.splitlines():
            line = line.rstrip()

            if not line or line.startswith("#"):
                continue

            negated = line.startswith("!")
            pattern = line[1:] if negated else line
            only_dirs = pattern.endswith("/")
            regex = re.compile(glob_to_regex(pattern.rstrip("/")))
            self.rules.append((regex, negated, only_dirs))

    def state(self, relative: str, is_dir: bool):
        """True si se ignora, False si se reincluye, None si ninguna regla habla de él."""
        result = None

        for regex, negated, only_dirs in self.rules:
            if only_dirs and not is_dir:
                continue

            if regex.fullmatch(relative):
                result = not negated

        return result


class SourceFilter:
    """Decide qué archivos de una fuente se pueden indexar."""

    def __init__(self, root, extensions, ignored_dirs):
        self.root = Path(root).resolve()
        self.extensions = extensions
        self.ignored_dirs = ignored_dirs
        self.gitignores = {}

    def gitignore_of(self, folder: Path):
        if folder not in self.gitignores:
            path = folder / ".gitignore"

            try:
                self.gitignores[folder] = GitIgnore(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                self.gitignores[folder] = None

        return self.gitignores[folder]

    def ignored_by_git(self, path: Path, is_dir: bool) -> bool:
        """Mira cada .gitignore de la raíz hacia abajo: el más cercano manda."""
        result = False
        parents = [path.parent, *path.parent.parents]

        for folder in reversed(parents):
            if folder != self.root and not folder.is_relative_to(self.root):
                continue

            rules = self.gitignore_of(folder)

            if rules is None:
                continue

            state = rules.state(path.relative_to(folder).as_posix(), is_dir)

            if state is not None:
                result = state

        return result

    def skip_folder(self, folder: Path) -> bool:
        name = folder.name.lower()
        return name in self.ignored_dirs or is_asia_data(folder) or self.ignored_by_git(folder, True)

    def allows(self, path: Path) -> bool:
        if is_secret(path) or is_asia_data(path) or self.ignored_by_git(path, False):
            return False

        try:
            # El único binario que entra: de un modelo solo se lee el código de sus bloques.
            if is_model_name(path):
                return not too_large(path) and is_model(path)

            if path.suffix.lower() not in self.extensions:
                return False

            return not too_large(path) and not is_binary(path)
        except OSError:
            return False

    def files(self):
        """Los archivos indexables de la fuente, sin entrar en las carpetas excluidas."""
        for folder, folders, names in os.walk(self.root):
            current = Path(folder)
            folders[:] = [name for name in folders if not self.skip_folder(current / name)]

            for name in names:
                path = current / name

                if self.allows(path):
                    yield path
