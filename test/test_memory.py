import json

from memory.memory_manager import MemoryManager
from memory.project_memory import ProjectMemory


def test_memory_manager_crea_archivo_vacio(tmp_path):
    memory_file = tmp_path / "sub" / "memory.json"

    memory = MemoryManager(memory_file)

    assert memory_file.exists()
    assert memory.load() == {}


def test_memory_manager_remember_recall_forget(tmp_path):
    memory = MemoryManager(tmp_path / "memory.json")

    memory.remember("proyecto", "Asia")

    assert memory.recall("proyecto") == "Asia"
    assert json.loads((tmp_path / "memory.json").read_text(encoding="utf-8")) == {
        "proyecto": "Asia"
    }

    assert memory.forget("proyecto") is True
    assert memory.recall("proyecto") is None
    assert memory.forget("proyecto") is False


def test_memory_manager_save_conserva_acentos(tmp_path):
    memory = MemoryManager(tmp_path / "memory.json")

    memory.save({"nombre": "Santiago", "ciudad": "Querétaro"})

    assert memory.load() == {"nombre": "Santiago", "ciudad": "Querétaro"}
    assert "Querétaro" in (tmp_path / "memory.json").read_text(encoding="utf-8")


def test_project_memory_guarda_y_carga_resumen(tmp_path):
    projects = ProjectMemory(tmp_path / "projects")

    path = projects.save_project_summary("Mi Proyecto", "# Resumen")

    assert path == tmp_path / "projects" / "mi_proyecto.md"
    assert projects.load_project_summary("mi proyecto") == "# Resumen"


def test_project_memory_proyecto_inexistente(tmp_path):
    projects = ProjectMemory(tmp_path / "projects")

    assert projects.load_project_summary("nada") is None


def test_project_memory_append_nota(tmp_path):
    projects = ProjectMemory(tmp_path / "projects")
    projects.save_project_summary("asia", "# Resumen")

    projects.append_project_note("asia", "nota uno")

    assert projects.load_project_summary("asia") == (
        "# Resumen\n\n## Nota nueva\nnota uno"
    )
