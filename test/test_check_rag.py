"""check_rag.py limpia sus carpetas temporales, también con Chroma abierto en Windows."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test" / "manual"))

import check_rag  # noqa: E402
from core import prompts  # noqa: E402
from core.rag.vector_store import VectorStore  # noqa: E402
from test_rag_wikipedia import zim  # noqa: E402, F401


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


class FakeEmbedder:
    def __init__(self):
        self.documents = []

    def embed_documents(self, documents):
        self.documents.extend(documents)
        return [[0.3, 0.4]] * len(documents)


def indexed_roadmap(folder, *documents, path=check_rag.ROADMAP):
    store = VectorStore(persist_dir=folder, collection_name=check_rag.COLLECTION)
    ids = [str(i) for i in range(len(documents))]
    store.add_documents(ids, list(documents), [[0.1, 0.2]] * len(ids), [{"relative_path": path}] * len(ids))
    return store


def test_quita_del_roadmap_las_lineas_que_citan_una_pregunta(tmp_path):
    question = check_rag.QUESTIONS[7][0]
    store = indexed_roadmap(tmp_path, f"ROADMAP.md · Velocidad\nantes\n\"{question}\" pasa a 2.º\ndespués", "otro\ntexto")
    embedder = FakeEmbedder()

    assert check_rag.without_benchmark_lines(store, embedder) == 1

    stored = store.collection.get(include=["documents", "embeddings"])
    assert stored["documents"] == ["ROADMAP.md · Velocidad\nantes\ndespués", "otro\ntexto"]
    assert list(stored["embeddings"][0]) == pytest.approx([0.3, 0.4])
    assert embedder.documents == ["ROADMAP.md · Velocidad\nantes\ndespués"]


def test_tambien_trampas_ajenas_y_wikipedia_sin_la_fuente(tmp_path):
    cited = [
        f"- {check_rag.TRAPS[3].capitalize()}, con Bolitabot",
        f"menciona \"{check_rag.UNANSWERABLE[0]}\"",
        f"- \"{check_rag.WIKIPEDIA_QUESTIONS[1][0]}\": 47 s",
        "\"cómo se lee un archivo JSON\" sin respuesta directa",
    ]
    store = indexed_roadmap(tmp_path, "\n".join(["ROADMAP.md", *cited, "queda"]))

    assert check_rag.without_benchmark_lines(store, FakeEmbedder()) == 4
    assert store.all_documents()["documents"] == ["ROADMAP.md\nqueda"]


def test_un_nombre_exacto_en_el_roadmap_no_es_una_cita(tmp_path):
    store = indexed_roadmap(tmp_path, "ROADMAP.md\n- `drop_client` llama a `cancel`")
    embedder = FakeEmbedder()

    assert check_rag.without_benchmark_lines(store, embedder) == 0
    assert embedder.documents == []


def test_solo_quita_lineas_del_roadmap(tmp_path):
    store = indexed_roadmap(tmp_path, f"README.md\n{check_rag.QUESTIONS[0][0]}", path="README.md")

    assert check_rag.without_benchmark_lines(store, FakeEmbedder()) == 0
    assert store.all_documents()["documents"] == [f"README.md\n{check_rag.QUESTIONS[0][0]}"]


def test_la_copia_quita_las_lineas_del_roadmap(tmp_path, monkeypatch):
    original = tmp_path / "chroma"
    indexed_roadmap(original, f"ROADMAP.md\n\"{check_rag.QUESTIONS[0][0]}\"\nqueda")
    monkeypatch.setattr(check_rag.vector_store, "CHROMA_DIR", original)
    monkeypatch.setattr(check_rag, "OllamaEmbedder", FakeEmbedder)

    check_rag.clean_copy(tmp_path / "copia")

    copy = VectorStore(persist_dir=tmp_path / "copia", collection_name=check_rag.COLLECTION)
    assert copy.all_documents()["documents"] == ["ROADMAP.md\nqueda"]
    assert VectorStore(persist_dir=original, collection_name=check_rag.COLLECTION).collection.count() == 1


def test_el_indice_del_ranking_quita_las_lineas_del_roadmap(tmp_path, monkeypatch):
    class Indexer:
        def __init__(self, root, collection, persist_dir):
            self.store = indexed_roadmap(persist_dir, f"ROADMAP.md\n\"{check_rag.QUESTIONS[0][0]}\"\nqueda")

        def index_project(self):
            return self.store.collection.count()

    monkeypatch.setattr(check_rag, "ProjectIndexer", Indexer)
    monkeypatch.setattr(check_rag, "unload_chat_models", lambda: None)
    monkeypatch.setattr(check_rag, "OllamaEmbedder", FakeEmbedder)

    count, _ = check_rag.build_index(tmp_path / "indice")

    store = VectorStore(persist_dir=tmp_path / "indice", collection_name=check_rag.COLLECTION)
    assert count == 1
    assert store.all_documents()["documents"] == ["ROADMAP.md\nqueda"]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """Un repo con dos commits: el primero es el congelado."""
    repo = tmp_path / "repo"
    (repo / "core").mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "prueba@example.com")
    git(repo, "config", "user.name", "Prueba")
    (repo / "core" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "ROADMAP.md").write_text("# Antes\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "primero")
    first = git(repo, "rev-parse", "HEAD")
    (repo / "ROADMAP.md").write_text("# Después\n", encoding="utf-8")
    (repo / "nuevo.py").write_text("y = 2\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "segundo")
    (repo / "sin_commit.py").write_text("z = 3\n", encoding="utf-8")
    return repo, first


def test_la_copia_congelada_tiene_el_repo_de_ese_commit(tmp_path, repo):
    repo, first = repo

    corpus = check_rag.frozen_copy(first, tmp_path / "indice", repo=repo)

    assert (corpus / "ROADMAP.md").read_text(encoding="utf-8") == "# Antes\n"
    assert (corpus / "core" / "a.py").exists()
    assert not (corpus / "nuevo.py").exists() and not (corpus / "sin_commit.py").exists()


def test_la_copia_congelada_se_reutiliza(tmp_path, repo):
    repo, first = repo
    corpus = check_rag.frozen_copy(first, tmp_path / "indice", repo=repo)
    (corpus / "marca.txt").write_text("sigue", encoding="utf-8")

    assert check_rag.frozen_copy(first, tmp_path / "indice", repo=repo) == corpus
    assert (corpus / "marca.txt").exists()


def test_el_ranking_indexa_la_copia_del_commit_de_la_base(tmp_path, monkeypatch, repo):
    repo, first = repo
    indexed = []

    class Indexer:
        def __init__(self, root, collection, persist_dir):
            indexed.append(Path(root))
            self.store = indexed_roadmap(persist_dir, "ROADMAP.md\nqueda")

        def index_project(self):
            return self.store.collection.count()

    real_copy = check_rag.frozen_copy
    monkeypatch.setattr(check_rag, "frozen_copy", lambda commit, folder: real_copy(commit, folder, repo=repo))
    monkeypatch.setattr(check_rag, "ProjectIndexer", Indexer)
    monkeypatch.setattr(check_rag, "unload_chat_models", lambda: None)

    check_rag.build_index(tmp_path / "indice", first)

    assert indexed == [tmp_path / "indice" / f"repo-{first[:12]}"]


def test_la_base_congela_el_ranking_en_un_commit_que_existe():
    commit = check_rag.load_base()["ranking_commit"]

    assert len(commit) == 40
    assert git(check_rag.ROOT, "cat-file", "-t", commit) == "commit"


def test_el_ranking_usa_la_ruta_relativa_de_lo_indexado(tmp_path, monkeypatch):
    hit = type("Hit", (), {"metadata": {"file_path": "C:/otra/core/a.py", "relative_path": "core/a.py"}, "distance": 1.0, "coverage": 1.0})()
    monkeypatch.setattr(check_rag, "QUESTIONS", [("pregunta", "core/a.py", "concepto")])
    monkeypatch.setattr(check_rag, "search_collections", lambda *args, **kwargs: [hit])

    rows, _ = check_rag.measure(tmp_path)

    assert rows[0][1] == 1


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


@pytest.mark.parametrize("shown", check_rag.prompts.NOTHING_TO_ANSWER)
def test_cualquier_negativa_del_codigo_cuenta_como_negada(shown):
    class Brain:
        def process(self, text):
            return shown

    assert check_rag.answer_row(Brain(), "q en wikipedia")[0] == "el código negó"


BASE = {"limite_conocido": 2, "ranking": {"concepto": [1, 2, 2], "documento": [0, 0, 0], "nombre": [1, 1, 1]}}


def ranked(*concepts):
    return [("concepto", rank) for rank in concepts] + [("nombre", 1)]


def test_el_limite_conocido_hasta_la_base_no_falla():
    assert check_rag.end_to_end_failures([0, 2], 0, 0, BASE) == []


def test_el_limite_conocido_se_compara_por_corrida():
    assert check_rag.end_to_end_failures([2, 2, 2], 0, 0, BASE) == []


def test_superar_el_limite_conocido_falla():
    assert "límite conocido" in check_rag.end_to_end_failures([1, 3], 0, 0, BASE)[0]


@pytest.mark.parametrize("traps, strangers, name", [(1, 0, "trampas"), (0, 1, "ajenas")])
def test_una_trampa_o_una_ajena_respondida_falla_aunque_el_limite_este_bien(traps, strangers, name):
    assert name in check_rag.end_to_end_failures([0], traps, strangers, BASE)[0]


def test_el_ranking_igual_o_mejor_que_la_base_no_falla():
    assert check_rag.ranking_failures(ranked(1, 3), BASE) == []
    assert check_rag.ranking_failures(ranked(1, 1), BASE) == []


def test_el_ranking_por_debajo_de_la_base_falla():
    assert check_rag.ranking_failures(ranked(1, 4), BASE) == ["ranking, concepto, top 3: 1, base 2"]


def test_mejorar_un_tipo_no_tapa_que_baje_otro():
    rows = [("concepto", 1), ("concepto", 1), ("nombre", 3)]

    assert check_rag.ranking_failures(rows, BASE) == ["ranking, nombre, top 1: 0, base 1"]


def test_una_pregunta_sin_puesto_cuenta_como_fallo():
    assert check_rag.ranking_failures(ranked(1, None), BASE)


def test_el_codigo_de_salida_y_lo_que_fallo(capsys):
    assert check_rag.finished([]) == 0
    assert check_rag.finished(["trampas respondidas: 1"]) == 1
    assert "FALLA: trampas respondidas: 1" in capsys.readouterr().out


def test_la_base_se_lee_de_su_archivo(tmp_path):
    path = tmp_path / "base.json"
    path.write_text(check_rag.json.dumps(BASE), encoding="utf-8")

    assert check_rag.load_base(path) == BASE


def test_la_base_guardada_cubre_cada_tipo_y_cada_top():
    base = check_rag.load_base()

    assert set(base["ranking"]) == set(check_rag.KINDS)
    assert all(len(found) == len(check_rag.TOPS) for found in base["ranking"].values())
    assert base["limite_conocido"] >= 0
    assert 0 <= base["wikipedia"]["encontrados"] <= len(check_rag.WIKIPEDIA_QUESTIONS)
    assert base["wikipedia"]["trampas"] >= 0


WIKI_BASE = {"wikipedia": {"encontrados": 1, "trampas": 0}}
WIKI_LINES = f"{check_rag.prompts.FROM_WIKIPEDIA}\n{check_rag.prompts.VERIFIED_LINES}\n\nCamberra\n  Camberra es la capital."


def test_wikipedia_correcta_si_esta_en_las_lineas():
    assert check_rag.wikipedia_correct(WIKI_LINES, r"Camberra")


def test_wikipedia_no_cuenta_lo_que_solo_dice_el_resumen():
    shown = f"{WIKI_LINES}\n\n{check_rag.prompts.UNVERIFIED_SUMMARY}\n\nFue fundada en 1913 [Camberra.wiki:3]."

    assert not check_rag.wikipedia_correct(shown, r"1913")


def test_wikipedia_no_cuenta_los_fragmentos_de_respaldo():
    shown = f"{check_rag.prompts.NO_DIRECT_ANSWER}\n\nCamberra es la capital."

    assert not check_rag.wikipedia_correct(shown, r"Camberra")


def test_wikipedia_igual_que_la_base_no_falla():
    assert check_rag.wikipedia_failures(1, 0, WIKI_BASE) == []


@pytest.mark.parametrize("found, traps, name", [(0, 0, "encontrado"), (1, 1, "trampas")])
def test_wikipedia_por_debajo_de_la_base_o_con_trampas_falla(found, traps, name):
    assert name in check_rag.wikipedia_failures(found, traps, WIKI_BASE)[0]


def shown_with(summary):
    lines = f"{prompts.VERIFIED_LINES}\n\nWikipedia · x (Armenia)\n  Armenia cuenta con 325 056 habitantes."
    return f"{lines}\n\n{prompts.UNVERIFIED_SUMMARY}\n\n{summary}"


@pytest.mark.parametrize("summary", [
    # Los dos de la corrida del 2026-11-03.
    "La información sobre la población de Salento no está disponible en las líneas proporcionadas [Armenia_Quindío.wiki:48].",
    f"El río Ulúa no nace en las fuentes consultadas. {prompts.UNCITED}\nLa información proporcionada se refiere a la cuenca.",
    "Ese dato no se menciona en los fragmentos.",
])
def test_un_resumen_que_dice_que_no_esta_es_una_negativa(summary):
    assert check_rag.wikipedia_state("respondió", shown_with(summary)) == "el modelo negó"


@pytest.mark.parametrize("summary", [
    "Villarrubia de los Ojos tiene 9,667 habitantes [Provincia_de_Ciudad_Real.wiki:60].",
    "El Muro de Berlín cayó en 1989; no hubo enfrentamientos.",
])
def test_una_respuesta_no_es_una_negativa(summary):
    assert check_rag.wikipedia_state("respondió", shown_with(summary)) == "respondió"


def test_la_negativa_solo_mira_el_resumen():
    shown = f"{prompts.VERIFIED_LINES}\n\nWikipedia · x\n  Esto no está disponible en las líneas.\n\n{prompts.UNVERIFIED_SUMMARY}\n\nSon 5."

    assert check_rag.wikipedia_state("respondió", shown) == "respondió"
    assert check_rag.wikipedia_state("sin respuesta directa", shown_with("no está en las fuentes")) == "sin respuesta directa"


def test_las_trampas_de_wikipedia_no_tienen_el_dato_en_otro_articulo():
    removed = ("Villarrubia", "Salento", "Vilcabamba", "Salto del Laja", "Real del Monte")

    assert len(check_rag.WIKIPEDIA_TRAPS) == 6
    assert not [trap for trap in check_rag.WIKIPEDIA_TRAPS if any(name in trap for name in removed)]


def test_las_preguntas_de_wikipedia_la_nombran():
    questions = [q for q, _, _ in check_rag.WIKIPEDIA_QUESTIONS] + check_rag.WIKIPEDIA_TRAPS

    assert all(question.endswith(" en wikipedia") for question in questions)


def test_sin_la_fuente_de_wikipedia_lo_dice_y_sale_con_1(capsys):
    assert check_rag.wikipedia(0, WIKI_BASE) == 1
    assert "/indexar wikipedia" in capsys.readouterr().out


def test_sin_corridas_solo_mira_los_articulos(zim, monkeypatch, capsys):
    from tools.rag_tool import RagTool

    RagTool().index_project("wikipedia", str(zim), "enciclopedia")
    monkeypatch.setattr(check_rag, "WIKIPEDIA_QUESTIONS", [("capital de Australia en wikipedia", ("Camberra",), "x")])
    monkeypatch.setattr(check_rag, "WIKIPEDIA_TRAPS", ["zzzyyyxxx en wikipedia"])

    assert check_rag.wikipedia(0, WIKI_BASE) == 0
    assert "1/1" in capsys.readouterr().out
    assert check_rag.wikipedia(0, {"wikipedia": {"encontrados": 2, "trampas": 0}}) == 1


def test_preguntas_fallan_por_sitio_si_bajan_o_responden_trampas():
    base = {"preguntas": {"robotics": {"encontrados": 3, "trampas": 0}, "es_stackoverflow": {"encontrados": 4, "trampas": 0}}}

    assert check_rag.questions_failures({"robotics": 3}, {"robotics": 0}, base) == []
    assert check_rag.questions_failures({"robotics": 2}, {}, base) == ["robotics, página encontrada: 2, base 3"]
    assert check_rag.questions_failures({"robotics": 3}, {"robotics": 1}, base) == ["robotics, trampas respondidas: 1, base 0"]
    # Un sitio sin descargar no se mide ni falla.
    assert check_rag.questions_failures({}, {}, base) == []


def test_el_banco_de_preguntas_nombra_su_fuente():
    for name, bench in check_rag.QA_BENCH.items():
        assert all(question.endswith(f" en {name}") for question, *_ in bench["preguntas"] + bench["trampas"])


def test_sin_palabras_clave_no_llama_al_modelo():
    assert check_rag.keywords_for("qué moneda se usa en Japón", None, False) == []
