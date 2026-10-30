"""'¿Quisiste decir @X?' y un 'sí' reenvía el mensaje con la ruta corregida."""
import pytest

import launcher
from core.attachments import corrected_message, missing_warning
from core.session import Session
from test_launcher import FakeBrain, reader


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(Session, "user_cwd", tmp_path)
    (tmp_path / "moda.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def run(lines, brain=None):
    brain = brain or FakeBrain("hecho")
    launcher.interactive_mode(brain, read=reader([*lines, "salir"]))
    return brain


@pytest.mark.parametrize("yes", ["sí", "si", "Sí.", "s", "dale"])
def test_si_reenvia_con_la_ruta_corregida(cwd, capsys, yes):
    brain = run(["explica @mod", yes])

    assert brain.processed == [f"explica {(cwd / 'moda.py').resolve()}"]
    err = capsys.readouterr().err
    assert "¿Quisiste decir @moda.py?" in err
    assert 'Escribe "sí" para enviarlo con @moda.py' in err
    assert "Reenvío: explica @moda.py" in err


def test_sin_si_no_reenvia(cwd):
    brain = run(["explica @mod", "hola", "sí"])

    # "hola" descarta la corrección; el "sí" de después es un mensaje normal.
    assert brain.processed == ["hola", "sí"]


def test_varias_sugerencias_no_adivina(cwd, capsys):
    (cwd / "modelo.py").write_text("y = 2\n", encoding="utf-8")

    brain = run(["explica @mod", "sí"])

    assert brain.processed == ["sí"]
    assert "Escribe \"sí\"" not in capsys.readouterr().err


def test_sin_sugerencias_no_hay_correccion(cwd):
    brain = run(["explica @zzz_nada", "sí"])

    assert brain.processed == ["sí"]


def test_ruta_con_espacios(tmp_path, monkeypatch):
    monkeypatch.setattr(Session, "user_cwd", tmp_path)
    (tmp_path / "mis notas.md").write_text("hola\n", encoding="utf-8")
    warning = missing_warning("mis nota.md", tmp_path)

    assert corrected_message('resume @"mis nota.md" ya', [warning]) == 'resume @"mis notas.md" ya'


def test_corrected_message_varios_adjuntos(cwd):
    (cwd / "datos.csv").write_text("a\n", encoding="utf-8")
    warnings = [missing_warning("mod", cwd), missing_warning("dato.csv", cwd)]

    assert corrected_message("compara @mod con @dato.csv", warnings) == "compara @moda.py con @datos.csv"
