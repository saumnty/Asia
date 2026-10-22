import json

import pytest

import core.atomic_write as atomic_write
from config.settings_manager import SettingsManager
from core.atomic_write import write_json_atomic
from core.paths import PROJECT_ROOT
from memory.memory_manager import MemoryManager
from tools.write_safety import find_truncating_rewrites

DATA = {"nombre": "Santiago", "ciudad": "Querétaro", "lista": [1, 2], "anidado": {"a": None}}


def old_write(path, data, **options):
    """Cómo escribían MemoryManager.save y SettingsManager.set antes."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, **options)


def files_in(folder):
    return sorted(p.name for p in folder.iterdir())


def failing_dump(data, f, **kwargs):
    """Escribe la mitad del JSON y falla, como un corte a mitad de escritura."""
    text = json.dumps(data, **kwargs)
    f.write(text[: len(text) // 2])
    raise OSError("disco lleno")


def interrupted_dump(data, f, **kwargs):
    f.write("{")
    raise KeyboardInterrupt


def test_mismo_contenido_que_la_escritura_anterior(tmp_path):
    expected = tmp_path / "esperado.json"
    actual = tmp_path / "actual.json"
    old_write(expected, DATA, ensure_ascii=False, indent=4)

    write_json_atomic(actual, DATA, ensure_ascii=False, indent=4)

    assert actual.read_bytes() == expected.read_bytes()
    assert files_in(tmp_path) == ["actual.json", "esperado.json"]


def test_reemplaza_un_archivo_existente(tmp_path):
    path = tmp_path / "datos.json"
    path.write_text('{"viejo": true}', encoding="utf-8")

    write_json_atomic(path, {"nuevo": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"nuevo": True}
    assert files_in(tmp_path) == ["datos.json"]


@pytest.mark.parametrize("dump", [failing_dump, interrupted_dump])
def test_fallo_a_mitad_deja_el_original_intacto(tmp_path, monkeypatch, dump):
    path = tmp_path / "datos.json"
    path.write_text('{"original": 1}', encoding="utf-8")
    original = path.read_bytes()
    monkeypatch.setattr(atomic_write.json, "dump", dump)

    with pytest.raises((OSError, KeyboardInterrupt)):
        write_json_atomic(path, DATA)

    assert path.read_bytes() == original
    assert files_in(tmp_path) == ["datos.json"]


def test_fallo_sin_archivo_previo_no_crea_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(atomic_write.json, "dump", failing_dump)

    with pytest.raises(OSError):
        write_json_atomic(tmp_path / "nuevo.json", DATA)

    assert files_in(tmp_path) == []


def test_memory_manager_save_igual_que_antes_y_atomico(tmp_path, monkeypatch):
    memory = MemoryManager(tmp_path / "memory.json")
    expected = tmp_path / "esperado.json"
    old_write(expected, DATA, ensure_ascii=False, indent=4)

    memory.save(DATA)

    assert memory.memory_file.read_bytes() == expected.read_bytes()

    saved = memory.memory_file.read_bytes()
    monkeypatch.setattr(atomic_write.json, "dump", failing_dump)

    with pytest.raises(OSError):
        memory.remember("otra", "cosa")

    assert memory.memory_file.read_bytes() == saved
    assert files_in(tmp_path) == ["esperado.json", "memory.json"]


def test_settings_manager_set_igual_que_antes_y_atomico(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"active_project": "asia"}), encoding="utf-8")
    settings = SettingsManager(tmp_path / "defaults.json", settings_path)
    expected = tmp_path / "esperado.json"
    old_write(expected, {"active_project": "práctica"}, indent=4, ensure_ascii=False)

    settings.set("active_project", "práctica")

    assert settings_path.read_bytes() == expected.read_bytes()

    saved = settings_path.read_bytes()
    monkeypatch.setattr(atomic_write.json, "dump", failing_dump)

    with pytest.raises(OSError):
        settings.set("default_provider", "gemini")

    assert settings_path.read_bytes() == saved
    assert files_in(tmp_path) == ["esperado.json", "settings.json"]


@pytest.mark.parametrize(
    "relative",
    ["memory/memory_manager.py", "config/settings_manager.py", "core/atomic_write.py"],
)
def test_write_safety_ya_no_avisa(relative):
    content = (PROJECT_ROOT / relative).read_text(encoding="utf-8")

    assert find_truncating_rewrites(content) == []
