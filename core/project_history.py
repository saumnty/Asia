"""Historia del proyecto para su resumen: el esquema del ROADMAP y los commits recientes.

Con solo los primeros archivos de la carpeta, el resumen de asia (2026-11) no nombraba
la biblioteca, el RAG ni la estrategia B: están en el ROADMAP y en el git log.
"""
import subprocess
from pathlib import Path

ROADMAP = "ROADMAP.md"
ROADMAP_CHARS = 6000
ROW_CHARS = 160
COMMITS = 30
GIT_TIMEOUT_S = 10


def roadmap_outline(text: str, max_chars: int = ROADMAP_CHARS) -> str:
    """Los títulos y el principio de cada fila con nombre de fase ("| 3. Seguridad | …").

    Las filas "| — |" son arreglos sueltos de una fase y los párrafos, detalle: no caben.
    """
    lines = []

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("#"):
            lines.append(stripped)
        elif stripped.startswith("|") and not stripped.startswith(("|---", "| —", "| Fase")):
            lines.append(stripped[:ROW_CHARS])

    outline = "\n".join(lines)
    return outline if len(outline) <= max_chars else outline[:max_chars].rsplit("\n", 1)[0]


def read_roadmap(folder: Path) -> str:
    path = Path(folder) / ROADMAP

    if not path.is_file():
        return ""

    return roadmap_outline(path.read_text(encoding="utf-8", errors="ignore"))


def recent_commits(folder: Path, count: int = COMMITS) -> str:
    """Fecha y mensaje de los últimos commits; "" si no es un repositorio o git no está.

    Solo con .git en la carpeta: si no, git subiría hasta un repositorio que la contenga.
    """
    if not (Path(folder) / ".git").exists():
        return ""

    try:
        done = subprocess.run(
            ["git", "-C", str(folder), "log", "--no-merges", f"-n{count}", "--format=%as %s"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return ""

    return done.stdout.strip() if done.returncode == 0 else ""
