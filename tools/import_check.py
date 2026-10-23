"""Imports del código generado: que existan y estén permitidos (ast, sin LLM).

El modelo a veces importa librerías que no existen o que el proyecto no usa.
Ejecutarlo daría ModuleNotFoundError y, peor, instalar lo que pidió podría
traer un paquete malicioso con ese nombre (slopsquatting). Asia nunca hace
pip install: solo se aceptan los imports de la lista permitida.

Permitidos para un archivo:
- biblioteca estándar de Python;
- módulos locales (archivos .py y paquetes de la carpeta del archivo o de la
  carpeta del usuario);
- paquetes del requirements.txt del proyecto, si están instalados;
- allowed_imports de la configuración;
- los imports que el archivo ya tenía (el proyecto corre en su propio
  entorno, que Asia no conoce).
"""
import ast
import functools
import importlib.metadata
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


STDLIB = frozenset(sys.stdlib_module_names)

NOT_INSTALLED = "no está instalada"
NOT_ALLOWED = "no está en la lista permitida"


def top_level(name: str) -> str:
    return name.split(".")[0]


def extract_imports(code: str) -> list[tuple[str, int]]:
    """(módulo de primer nivel, línea) de cada import absoluto.

    Incluye importlib.import_module("x") y __import__("x") con nombre fijo.
    Los imports relativos (from . import x) son del proyecto y se omiten.
    Lanza SyntaxError si el código no es Python válido.
    """
    imports = []

    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import):
            imports += [(top_level(alias.name), node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.append((top_level(node.module), node.lineno))
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")

            if name in ("import_module", "__import__") and isinstance(node.args[0].value, str):
                imports.append((top_level(node.args[0].value), node.lineno))

    return sorted(set(imports), key=lambda item: (item[1], item[0]))


def normalize_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(path: Path) -> list[str]:
    """Nombres de distribución de un requirements.txt (sin versiones ni extras)."""
    names = []

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.split("#", 1)[0].strip()

        # -r otro.txt, -e ., --index-url... no son paquetes.
        if not line or line.startswith("-"):
            continue

        match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)

        if match:
            names.append(match.group())

    return names


@functools.lru_cache(maxsize=1)
def installed_distributions() -> dict[str, list[str]]:
    # Recorre todos los paquetes instalados (lento): una vez por proceso.
    return importlib.metadata.packages_distributions()


def import_names_for(dist: str) -> set[str]:
    """Módulos que instala una distribución (google-genai -> google).

    Si no está instalada, se supone el nombre con guiones bajos.
    """
    wanted = normalize_dist(dist)
    names = {
        module
        for module, dists in installed_distributions().items()
        if any(normalize_dist(d) == wanted for d in dists)
    }

    return names or {dist.replace("-", "_").lower()}


def find_requirements(file_path: Path, cwd: Path) -> Path | None:
    """requirements.txt más cercano al archivo, sin salir de la carpeta del usuario."""
    cwd = cwd.resolve()
    folder = file_path.resolve().parent

    while True:
        candidate = folder / "requirements.txt"

        if candidate.is_file():
            return candidate

        if folder == cwd or cwd not in folder.parents:
            break

        folder = folder.parent

    candidate = cwd / "requirements.txt"
    return candidate if candidate.is_file() else None


def local_modules(file_path: Path, cwd: Path) -> set[str]:
    names = set()

    for folder in {file_path.resolve().parent, cwd.resolve()}:
        if not folder.is_dir():
            continue

        for entry in folder.iterdir():
            if entry.suffix == ".py":
                names.add(entry.stem)
            elif entry.is_dir() and (entry / "__init__.py").exists():
                names.add(entry.name)

    return names


@dataclass
class ImportPolicy:
    """Qué imports se aceptan en un archivo concreto."""

    allowed: set[str] = field(default_factory=set)
    local: set[str] = field(default_factory=set)
    existing: set[str] = field(default_factory=set)

    @classmethod
    def for_file(cls, file_path, cwd, extra=()):
        file_path, cwd = Path(file_path), Path(cwd)
        target = file_path if file_path.is_absolute() else cwd / file_path
        allowed = {top_level(name) for name in extra}
        requirements = find_requirements(target, cwd)

        if requirements:
            for dist in parse_requirements(requirements):
                allowed |= import_names_for(dist)

        existing = set()

        if target.is_file():
            try:
                existing = {name for name, _ in extract_imports(target.read_text(encoding="utf-8"))}
            except (SyntaxError, UnicodeDecodeError):
                pass

        return cls(allowed=allowed, local=local_modules(target, cwd), existing=existing)

    def describe(self) -> str:
        """Lista para el prompt: lo que el modelo puede importar."""
        packages = sorted(self.allowed | self.existing)
        listed = ", ".join(packages) if packages else "ninguno"
        return (
            "biblioteca estándar de Python, módulos del propio proyecto y estos "
            f"paquetes: {listed}"
        )


@dataclass
class ImportIssue:
    module: str
    line: int
    reason: str


@dataclass
class ImportReport:
    issues: list[ImportIssue] = field(default_factory=list)
    syntax_error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.issues and self.syntax_error is None

    def describe(self) -> str:
        if self.syntax_error:
            return f"- el código no es Python válido: {self.syntax_error}"

        return "\n".join(
            f"- línea {issue.line}: import {issue.module} ({issue.reason})"
            for issue in self.issues
        )


def is_installed(module: str) -> bool:
    # find_spec de un módulo de primer nivel no ejecuta su código.
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def check_imports(code: str, policy: ImportPolicy) -> ImportReport:
    try:
        imports = extract_imports(code)
    except SyntaxError as e:
        return ImportReport(syntax_error=f"línea {e.lineno}: {e.msg}")

    issues = []

    for module, line in imports:
        if module in STDLIB or module in policy.local or module in policy.existing:
            continue

        if not is_installed(module):
            issues.append(ImportIssue(module, line, NOT_INSTALLED))
        elif module not in policy.allowed:
            issues.append(ImportIssue(module, line, NOT_ALLOWED))

    return ImportReport(issues=issues)


def rewrite_request(report: ImportReport) -> str:
    """Instrucción que se agrega al prompt para pedir la reescritura."""
    return f"""

Tu respuesta anterior no se puede usar:
{report.describe()}

Reescribe el código sin esas librerías, usando solo la biblioteca estándar o
las dependencias permitidas. No inventes librerías. Responde con el mismo
formato FILE_PATH / CODE / EXPLANATION.
"""


def module_names(code: str) -> set[str]:
    try:
        return {module for module, _ in extract_imports(code)}
    except SyntaxError:
        return set()


def rewrite_note(report: ImportReport, old_code: str, new_code: str) -> str:
    """Aviso de que el código se reescribió: qué librería usaba y qué usa ahora.

    Sin él, "genera un código que use superjson_mega" devolvía un código con
    json sin decir que superjson_mega no se podía usar.
    """
    if report.syntax_error:
        return (
            f"Aviso: el primer código generado no era Python válido "
            f"({report.syntax_error}); se pidió una reescritura."
        )

    used = ", ".join(sorted({f"{i.module} ({i.reason})" for i in report.issues}))
    added = sorted(module_names(new_code) - module_names(old_code))
    instead = (
        f"ahora usa {', '.join(added)} en su lugar"
        if added
        else "ahora no usa ninguna librería en su lugar"
    )

    return f"Aviso: el código generado usaba {used}. Se pidió una reescritura y {instead}."


def refusal_message(file_path: str, report: ImportReport) -> str:
    return (
        f"No propongo el cambio para {file_path}: el código generado, aun "
        f"después de pedir una reescritura, tiene imports que no se pueden usar:\n"
        f"{report.describe()}\n\n"
        "Asia no instala paquetes. Si de verdad hace falta una librería, "
        "agrégala al requirements.txt del proyecto (o a allowed_imports en la "
        "configuración) e instálala tú."
    )
