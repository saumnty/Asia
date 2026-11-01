"""check_rag.py limpia sus carpetas temporales, también con Chroma abierto en Windows."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test" / "manual"))

import check_rag  # noqa: E402


@pytest.fixture(autouse=True)
def chroma_stays_up(monkeypatch):
    monkeypatch.setattr(check_rag, "release_chroma", lambda: None)


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(check_rag.time, "sleep", lambda seconds: None)


def locked_for(monkeypatch, failures):
    """shutil.rmtree falla como Windows las primeras veces y cuenta los intentos."""
    real = check_rag.shutil.rmtree
    calls = []

    def rmtree(folder):
        calls.append(folder)

        if len(calls) <= failures:
            raise PermissionError(5, "bloqueado", str(folder))

        real(folder)

    monkeypatch.setattr(check_rag.shutil, "rmtree", rmtree)
    return calls


REAL_CHROMA = """
import sys
sys.path[:0] = [sys.argv[1], sys.argv[1] + "/test/manual"]
import check_rag
from core.rag.vector_store import VectorStore

store = VectorStore(persist_dir=sys.argv[2], collection_name="prueba")
store.add_documents(["1"], ["texto"], [[0.1, 0.2]], [{"file_path": "a.py"}])
sys.exit(0 if check_rag.remove_tree(sys.argv[2]) else 1)
"""


def test_borra_una_carpeta_con_chroma_abierto(tmp_path):
    # En su propio proceso: soltar Chroma para todo el proceso, como hace una corrida
    # real, rompería a las demás pruebas.
    folder = tmp_path / "indice"

    done = subprocess.run([sys.executable, "-c", REAL_CHROMA, str(ROOT), str(folder)], timeout=60)

    assert done.returncode == 0
    assert not folder.exists()


def test_reintenta_si_windows_la_bloquea(tmp_path, monkeypatch, no_wait):
    folder = tmp_path / "indice"
    folder.mkdir()
    calls = locked_for(monkeypatch, failures=2)

    assert check_rag.remove_tree(folder) is True
    assert len(calls) == 3 and not folder.exists()


def test_si_no_puede_lo_dice_y_no_truena(tmp_path, monkeypatch, no_wait, capsys):
    folder = tmp_path / "indice"
    folder.mkdir()
    calls = locked_for(monkeypatch, failures=99)

    assert check_rag.remove_tree(folder) is False
    assert len(calls) == check_rag.REMOVE_TRIES
    assert str(folder) in capsys.readouterr().err


def test_una_carpeta_que_ya_no_esta_cuenta_como_borrada(tmp_path):
    assert check_rag.remove_tree(tmp_path / "no_existe") is True


def test_barre_solo_sus_carpetas(tmp_path):
    (tmp_path / "asia_rag_viejo").mkdir()
    (tmp_path / "asia_rag_viejo" / "chroma.sqlite3").write_text("x", encoding="utf-8")
    (tmp_path / "asia_sandbox_otro").mkdir()
    (tmp_path / "otra_cosa").mkdir()

    check_rag.sweep_leftovers(tmp_path)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["asia_sandbox_otro", "otra_cosa"]


def test_al_barrer_no_espera_por_una_carpeta_bloqueada(tmp_path, monkeypatch):
    (tmp_path / "asia_rag_en_uso").mkdir()
    calls = locked_for(monkeypatch, failures=99)

    def forbidden(seconds):
        raise AssertionError("barrer no debe esperar")

    monkeypatch.setattr(check_rag.time, "sleep", forbidden)

    check_rag.sweep_leftovers(tmp_path)

    assert len(calls) == 1


def test_sus_temporales_llevan_el_prefijo_que_se_barre(tmp_path, monkeypatch):
    monkeypatch.setattr(check_rag.tempfile, "tempdir", str(tmp_path))

    folder = check_rag.temp_folder()

    assert folder.parent == tmp_path and folder.name.startswith(check_rag.TEMP_PREFIX)
