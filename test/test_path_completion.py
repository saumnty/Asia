import os

import pytest
from prompt_toolkit.document import Document

from core.path_completion import make_completer, partial_attachment, path_completions


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "api.py").write_text("", encoding="utf-8")
    (tmp_path / "setup.py").write_text("", encoding="utf-8")
    (tmp_path / "mis notas").mkdir()
    (tmp_path / "mis notas" / "uno.txt").write_text("", encoding="utf-8")
    (tmp_path / ".oculto").write_text("", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "text, expected",
    [
        ("explica @sr", "sr"),
        ("@", ""),
        ('compara @"mis no', '"mis no'),
        ("explica @src/app.py y @src/a", "src/a"),
        ("correo ana@co", None),
        ("sin arroba", None),
        ("explica @src/app.py ", None),
    ],
)
def test_partial_attachment(text, expected):
    assert partial_attachment(text) == expected


def test_carpetas_primero_y_con_barra(project):
    assert path_completions("s", project) == ["src/", "setup.py"]


def test_dentro_de_una_carpeta(project):
    assert path_completions("src/ap", project) == ["src/api.py", "src/app.py"]
    assert path_completions("src\\ap", project) == ["src/api.py", "src/app.py"]


def test_ruta_con_espacios_va_entre_comillas(project):
    assert path_completions("mi", project) == ['"mis notas/']
    assert path_completions('"mis notas/', project) == ['"mis notas/uno.txt"']


def test_ocultos_solo_si_se_escribe_el_punto(project):
    assert ".oculto" not in path_completions("", project)
    assert path_completions(".", project) == [".oculto"]


def test_carpeta_inexistente(project):
    assert path_completions("no_existe/x", project) == []


@pytest.mark.skipif(os.name != "nt", reason="solo Windows ignora mayúsculas")
def test_windows_ignora_mayusculas(project):
    assert path_completions("SRC/AP", project) == ["SRC/api.py", "SRC/app.py"]


def test_completer_de_prompt_toolkit(project):
    completer = make_completer(lambda: project)
    document = Document("explica @src/ap")

    completions = list(completer.get_completions(document, None))

    assert [c.text for c in completions] == ["src/api.py", "src/app.py"]
    assert all(c.start_position == -len("src/ap") for c in completions)
    assert list(completer.get_completions(Document("hola"), None)) == []
