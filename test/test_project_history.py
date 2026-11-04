"""El resumen del proyecto con el ROADMAP y los commits recientes, además de los archivos."""
import subprocess
from types import SimpleNamespace

from core import prompts
from core.actions.memory import MemoryActions
from core.project_history import read_roadmap, recent_commits, roadmap_outline

ROADMAP_TEXT = """# Roadmap

Texto de introducción que no entra.

## Completado

| Fase | Contenido | Commits |
|---|---|---|
| 3. Seguridad | open_app sin shell | `abc` |
| — | un arreglo suelto | `def` |

## Próximas fases

### Biblioteca offline
- detalle que no entra
"""


def test_el_esquema_del_roadmap():
    outline = roadmap_outline(ROADMAP_TEXT)

    assert outline.splitlines() == [
        "# Roadmap", "## Completado", "| 3. Seguridad | open_app sin shell | `abc` |",
        "## Próximas fases", "### Biblioteca offline",
    ]


def test_el_esquema_con_tope_corta_en_una_linea_entera():
    assert roadmap_outline(ROADMAP_TEXT, max_chars=30) == "# Roadmap\n## Completado"


def test_sin_roadmap_ni_repositorio(tmp_path):
    assert read_roadmap(tmp_path) == "" and recent_commits(tmp_path) == ""


def git(folder, *args):
    subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True)


def repository(folder):
    git(folder, "init", "-q")
    git(folder, "config", "user.email", "prueba@example.com")
    git(folder, "config", "user.name", "Prueba")
    (folder / "ROADMAP.md").write_text(ROADMAP_TEXT, encoding="utf-8")
    git(folder, "add", "ROADMAP.md")
    git(folder, "commit", "-q", "-m", "Biblioteca: fuentes .zim")
    return folder


def test_los_commits_recientes(tmp_path):
    commits = recent_commits(repository(tmp_path))

    assert commits.endswith(" Biblioteca: fuentes .zim") and commits[:4].isdigit()


def test_el_prompt_sin_historia_queda_como_antes():
    assert prompts.summarize_and_save_project("asia", "<archivos>").endswith("Contenido:\n<archivos>\n")


def summarizer(asked):
    return SimpleNamespace(
        active_project=lambda: "asia",
        limit=lambda name: {"max_files": 15, "max_chars_per_file": 1500},
        tool_registry=SimpleNamespace(execute=lambda *a, **k: "<archivos>"),
        provider_router=SimpleNamespace(ask=lambda prompt: asked.append(prompt) or "resumen"),
        project_memory=SimpleNamespace(save_project_summary=lambda name, summary: None),
    )


def test_el_resumen_recibe_roadmap_y_commits(tmp_path, monkeypatch):
    monkeypatch.chdir(repository(tmp_path))
    asked = []

    MemoryActions.handle_summarize_and_save_project(summarizer(asked), "resume el proyecto", {})

    assert "Esquema del ROADMAP" in asked[0] and "| 3. Seguridad |" in asked[0]
    assert "Commits recientes" in asked[0] and "Biblioteca: fuentes .zim" in asked[0]
    assert "<archivos>" in asked[0]
