"""check_rag.py limpia sus carpetas temporales, también con Chroma abierto en Windows."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test" / "manual"))

import check_rag  # noqa: E402
from core.rag.vector_store import VectorStore  # noqa: E402


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


def indexed_in(folder, *documents):
    store = VectorStore(persist_dir=folder, collection_name=check_rag.COLLECTION)
    ids = [str(i) for i in range(len(documents))]
    store.add_documents(ids, list(documents), [[0.1, 0.2]] * len(ids), [{"file_path": "a.py"}] * len(ids))


def test_la_copia_quita_lo_que_trae_una_trampa(tmp_path, monkeypatch):
    original = tmp_path / "chroma"
    indexed_in(original, "texto normal", f"anotado: {check_rag.TRAPS[0]}")
    monkeypatch.setattr(check_rag.vector_store, "CHROMA_DIR", original)

    check_rag.clean_copy(tmp_path / "copia")

    copy = VectorStore(persist_dir=tmp_path / "copia", collection_name=check_rag.COLLECTION)
    assert copy.all_documents()["documents"] == ["texto normal"]
    assert VectorStore(persist_dir=original, collection_name=check_rag.COLLECTION).collection.count() == 2


def test_la_copia_funciona_sin_nada_que_quitar(tmp_path, monkeypatch):
    original = tmp_path / "chroma"
    indexed_in(original, "texto normal")
    monkeypatch.setattr(check_rag.vector_store, "CHROMA_DIR", original)

    check_rag.clean_copy(tmp_path / "copia")

    assert check_rag.vector_store.CHROMA_DIR == tmp_path / "copia"


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


SUMMARY = f"{check_rag.prompts.VERIFIED_LINES}\n\na.py:1\n  x\n\n{check_rag.prompts.UNVERIFIED_SUMMARY}\n\n"


@pytest.mark.parametrize(
    "question, sentence",
    [
        ("cómo se escribe un archivo sin dejarlo a medias", 'Debes abrirlo con el modo "w" [a.py:1].'),
        ("drop_client", "La función se define en `providers/ollama_provider.py` [a.py:1]."),
        ("cómo se resume la sesión en segundo plano", "Se actualiza cada 3 segundos [a.py:1]."),
    ],
)
def test_las_tres_frases_falsas_se_detectan(question, sentence):
    assert check_rag.forbidden_said(question, SUMMARY + sentence)


def test_una_frase_prohibida_con_la_marca_no_cuenta():
    shown = SUMMARY + f"Se actualiza cada 3 segundos [a.py:1]. {check_rag.prompts.UNCITED}"

    assert not check_rag.forbidden_said("cómo se resume la sesión en segundo plano", shown)


def test_una_frase_prohibida_en_las_lineas_no_cuenta():
    shown = f"{check_rag.prompts.VERIFIED_LINES}\n\na.py:1\n  cada 3 segundos"

    assert not check_rag.forbidden_said("cómo se resume la sesión en segundo plano", shown)


@pytest.mark.parametrize(
    "shown, state",
    [
        (SUMMARY + "Una frase [a.py:1].", "respondió"),
        (f"{check_rag.prompts.VERIFIED_LINES}\n\na.py:1\n  x", "solo líneas"),
        (f"{check_rag.prompts.INVALID_DRAFT}\n\n{check_rag.prompts.VERIFIED_LINES}\n\na.py:1\n  x", "redacción inválida"),
    ],
)
def test_estado_de_una_respuesta(shown, state):
    class Brain:
        def process(self, text):
            return shown

    assert check_rag.answer_row(Brain(), "q", "a.py")[0] == state
    assert check_rag.answer_row(Brain(), "q", "a.py")[1]
