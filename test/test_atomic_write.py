import json

import pytest

import core.atomic_write as atomic_write
from config.settings_manager import SettingsManager
from core.atomic_write import write_json_atomic, write_text_atomic
from core.paths import APPS_FILE, PROJECT_ROOT
from memory.memory_manager import MemoryManager
from memory.project_memory import ProjectMemory
from tools.app_tool import AppTool
from tools.apply_changes_tool import ApplyChangesTool
from tools.write_safety import find_truncating_rewrites

DATA = {"nombre": "Santiago", "ciudad": "Querétaro", "lista": [1, 2], "anidado": {"a": None}}
TEXT = "# Resumen\n\nlínea con acentos: ñandú\nfin\n"


def old_write_json(path, data, **options):
    """Cómo escribían MemoryManager.save, SettingsManager.set y save_apps antes."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, **options)


def old_write_text(path, text):
    """Cómo escribía save_project_summary antes."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def files_in(folder):
    return sorted(p.name for p in folder.iterdir())


def break_writes(monkeypatch, error):
    """El temporal recibe la mitad del texto y luego falla con error."""
    real_fdopen = atomic_write.os.fdopen

    class HalfWriter:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()

        def write(self, text):
            self.f.write(text[: len(text) // 2])
            raise error

    monkeypatch.setattr(
        atomic_write.os, "fdopen",
        lambda fd, *args, **kwargs: HalfWriter(real_fdopen(fd, *args, **kwargs))
    )


def test_texto_mismos_bytes_que_open_w(tmp_path):
    expected = tmp_path / "esperado.md"
    actual = tmp_path / "actual.md"
    old_write_text(expected, TEXT)

    write_text_atomic(actual, TEXT)

    assert actual.read_bytes() == expected.read_bytes()
    assert files_in(tmp_path) == ["actual.md", "esperado.md"]


def test_texto_mismos_bytes_que_path_write_text(tmp_path):
    expected = tmp_path / "esperado.json"
    actual = tmp_path / "actual.json"
    expected.write_text(TEXT, encoding="utf-8")

    write_text_atomic(actual, TEXT)

    assert actual.read_bytes() == expected.read_bytes()


def test_json_mismos_bytes_que_json_dump(tmp_path):
    expected = tmp_path / "esperado.json"
    actual = tmp_path / "actual.json"
    old_write_json(expected, DATA, ensure_ascii=False, indent=4)

    write_json_atomic(actual, DATA, ensure_ascii=False, indent=4)

    assert actual.read_bytes() == expected.read_bytes()


def test_reemplaza_un_archivo_existente(tmp_path):
    path = tmp_path / "datos.json"
    path.write_text('{"viejo": true}', encoding="utf-8")

    write_json_atomic(path, {"nuevo": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"nuevo": True}
    assert files_in(tmp_path) == ["datos.json"]


@pytest.mark.parametrize("error", [OSError("disco lleno"), KeyboardInterrupt()])
def test_fallo_a_mitad_deja_el_original_intacto(tmp_path, monkeypatch, error):
    path = tmp_path / "datos.txt"
    path.write_text("original", encoding="utf-8")
    break_writes(monkeypatch, error)

    with pytest.raises(type(error)):
        write_text_atomic(path, TEXT)

    assert path.read_text(encoding="utf-8") == "original"
    assert files_in(tmp_path) == ["datos.txt"]


def test_fallo_sin_archivo_previo_no_crea_nada(tmp_path, monkeypatch):
    break_writes(monkeypatch, OSError("disco lleno"))

    with pytest.raises(OSError):
        write_text_atomic(tmp_path / "nuevo.txt", TEXT)

    assert files_in(tmp_path) == []


def test_json_no_serializable_falla_sin_tocar_nada(tmp_path):
    path = tmp_path / "datos.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(TypeError):
        write_json_atomic(path, {"x": object()})

    assert path.read_text(encoding="utf-8") == "{}"
    assert files_in(tmp_path) == ["datos.json"]


def check_atomic(folder, path, write, monkeypatch):
    """Tras escribir con write(), un fallo a mitad deja path intacto."""
    saved = path.read_bytes()
    before = files_in(folder)
    break_writes(monkeypatch, OSError("disco lleno"))

    with pytest.raises(OSError):
        write()

    assert path.read_bytes() == saved
    assert files_in(folder) == before


def test_memory_manager_save(tmp_path, monkeypatch):
    memory = MemoryManager(tmp_path / "memory.json")
    expected = tmp_path / "esperado.json"
    old_write_json(expected, DATA, ensure_ascii=False, indent=4)

    memory.save(DATA)

    assert memory.memory_file.read_bytes() == expected.read_bytes()
    check_atomic(tmp_path, memory.memory_file, lambda: memory.remember("otra", "cosa"), monkeypatch)


def test_settings_manager_set(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"active_project": "asia"}), encoding="utf-8")
    settings = SettingsManager(tmp_path / "defaults.json", settings_path)
    expected = tmp_path / "esperado.json"
    old_write_json(expected, {"active_project": "práctica"}, indent=4, ensure_ascii=False)

    settings.set("active_project", "práctica")

    assert settings_path.read_bytes() == expected.read_bytes()
    check_atomic(tmp_path, settings_path, lambda: settings.set("x", 1), monkeypatch)


def test_save_apps_conserva_entradas_y_es_atomico(tmp_path, monkeypatch):
    # Copia del apps.json real en una carpeta temporal: el real no se toca.
    apps_file = tmp_path / "apps.json"
    apps_file.write_bytes(APPS_FILE.read_bytes())
    tool = AppTool(apps_file)
    apps = tool.load_apps()
    expected = tmp_path / "esperado.json"
    old_write_json(expected, apps, ensure_ascii=False, indent=4)

    tool.save_apps(apps)

    assert apps_file.read_bytes() == expected.read_bytes()
    assert tool.load_apps() == apps
    check_atomic(tmp_path, apps_file, lambda: tool.save_apps({**apps, "nueva": "x.exe"}), monkeypatch)
    assert tool.load_apps() == apps


def test_save_project_summary(tmp_path, monkeypatch):
    projects = ProjectMemory(tmp_path / "projects")
    expected = tmp_path / "esperado.md"
    old_write_text(expected, TEXT)

    path = projects.save_project_summary("asia", TEXT)

    assert path.read_bytes() == expected.read_bytes()
    check_atomic(path.parent, path, lambda: projects.save_project_summary("asia", "otro"), monkeypatch)


def test_pending_change_json(tmp_path, monkeypatch):
    target = tmp_path / "objetivo.py"
    target.write_text("x = 1\n", encoding="utf-8")
    pending_file = tmp_path / "estado" / "pending_change.json"
    tool = ApplyChangesTool(pending_file, tmp_path / "backups")

    tool.propose_change(str(target), "x = 2\n")

    pending = json.loads(pending_file.read_text(encoding="utf-8"))
    expected = tmp_path / "esperado.json"
    expected.write_text(json.dumps(pending, indent=2, ensure_ascii=False), encoding="utf-8")
    assert pending_file.read_bytes() == expected.read_bytes()
    assert pending["new_content"] == "x = 2\n"

    check_atomic(
        pending_file.parent, pending_file,
        lambda: tool.propose_change(str(target), "x = 3\n"), monkeypatch
    )
    assert tool.load_pending_change()["new_content"] == "x = 2\n"


@pytest.mark.parametrize(
    "relative",
    [
        "memory/memory_manager.py",
        "config/settings_manager.py",
        "core/atomic_write.py",
        "tools/app_tool.py",
        "memory/project_memory.py",
        "tools/apply_changes_tool.py",
    ],
)
def test_write_safety_no_avisa(relative):
    content = (PROJECT_ROOT / relative).read_text(encoding="utf-8")

    assert find_truncating_rewrites(content) == []
