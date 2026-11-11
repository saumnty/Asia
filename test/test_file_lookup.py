"""Nombres de archivo sueltos: se buscan en la carpeta de Asia (core/file_lookup.py)."""
import pytest

from core import file_lookup
from core.session import Session


@pytest.fixture
def project(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "timing.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "deep").mkdir()
    (tmp_path / "test" / "deep" / "Timing.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "solo.md").write_text("# solo\n", encoding="utf-8")
    (tmp_path / "core" / "unico.py").write_text("z = 3\n", encoding="utf-8")
    for skipped in (".venv", "data", "node_modules", "__pycache__"):
        (tmp_path / skipped).mkdir()
        (tmp_path / skipped / "timing.py").write_text("", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("value, bare", [("timing.py", True), ("core/timing.py", False), (r"C:\x.py", False),
                                         ("timing", False), (None, False), ("a b.md", True)])
def test_nombre_suelto(value, bare):
    assert file_lookup.is_bare_name(value) is bare


def test_busca_sin_mayusculas_y_salta_entornos_y_datos(project):
    assert file_lookup.find_named(project, "timing.py") == ["core/timing.py", "test/deep/Timing.py"]
    assert file_lookup.find_named(project, "nada.py") == []


@pytest.mark.parametrize("answer, expected", [("2", "test/deep/Timing.py"), ("el primero", "core/timing.py"),
                                              ("Dos.", "test/deep/Timing.py"), ("core/timing.py", "core/timing.py"),
                                              ("el de test", "test/deep/Timing.py"), ("no", False),
                                              ("7", None), ("qué hora es", None)])
def test_la_respuesta_elige(answer, expected):
    assert file_lookup.chosen(answer, ["core/timing.py", "test/deep/Timing.py"]) == expected


def brain_in(folder, monkeypatch, action):
    from core.brain import Brain

    brain = Brain.__new__(Brain)
    seen = []
    brain.intent_engine = type("I", (), {"detect": lambda self, t: {"action": action, "params": {"file_path": t.split()[-1]}}})()
    brain.settings = type("S", (), {"get": lambda self, k, d=None: d})()
    monkeypatch.setattr(Brain, "app_names", lambda self: [])
    monkeypatch.setattr(Brain, "handle_explain_file", lambda self, text, params: seen.append((text, params)) or "explicado")
    monkeypatch.setattr(Session, "user_cwd", folder)
    return brain, seen


def test_una_sola_coincidencia_usa_su_ruta(project, monkeypatch):
    brain, seen = brain_in(project, monkeypatch, "explain_file")

    assert brain.process("explica unico.py") == "explicado"
    assert seen == [("explica unico.py", {"file_path": "core/unico.py"})]


def test_en_la_carpeta_abierta_no_se_busca(project, monkeypatch):
    brain, seen = brain_in(project, monkeypatch, "explain_file")

    brain.process("explica solo.md")
    assert seen[0][1] == {"file_path": "solo.md"}


def test_varias_preguntan_cual_y_el_numero_elige(project, monkeypatch):
    brain, seen = brain_in(project, monkeypatch, "explain_file")

    question = brain.process("explica timing.py")
    assert "core/timing.py" in question and "test/deep/Timing.py" in question and "¿Cuál?" in question
    assert seen == []

    assert brain.process("2") == "explicado"
    assert seen == [("explica timing.py", {"file_path": "test/deep/Timing.py"})]


def test_un_no_lo_deja_y_otra_cosa_olvida_la_pregunta(project, monkeypatch):
    brain, seen = brain_in(project, monkeypatch, "explain_file")

    brain.process("explica timing.py")
    assert brain.process("no") == "Vale, lo dejo."

    brain.process("explica timing.py")
    brain.process("explica unico.py")
    assert seen == [("explica unico.py", {"file_path": "core/unico.py"})]
    assert getattr(brain, "pending_file", None) is None


def test_sin_coincidencias_sigue_como_antes(project, monkeypatch):
    brain, seen = brain_in(project, monkeypatch, "explain_file")

    brain.process("explica nada.py")
    assert seen == [("explica nada.py", {"file_path": "nada.py"})]
