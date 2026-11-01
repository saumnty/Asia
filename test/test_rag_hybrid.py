"""Búsqueda híbrida: BM25 propio y fusión con los embeddings."""
import pytest

from core.rag.tokens import stem, tokenize
from core.rag.indexer import ProjectIndexer
from core.rag.retriever import MAX_PER_FILE, Hit, merge, search_collections
from core.rag.vector_store import VectorStore
from core.rag.word_index import WordIndex
from test_rag_index import embeddings  # noqa: F401


def test_parte_los_nombres_como_en_el_codigo():
    assert {stem(t) for t in ("drop_client", "drop", "client")} <= set(tokenize("drop_client"))
    assert {stem(t) for t in ("sessionsummarizer", "session", "summarizer")} <= set(tokenize("SessionSummarizer"))
    assert {stem(t) for t in ("margin_frames", "margin", "frames")} <= set(tokenize("MARGIN_FRAMES"))
    assert {stem(t) for t in ("http", "client")} <= set(tokenize("HTTPClient"))


def test_sin_acentos_ni_palabras_vacias():
    assert set(tokenize("la sesión de pruebas")) == {stem("sesion"), stem("pruebas")}


@pytest.mark.parametrize(
    "word",
    ["cuánto", "cuánta", "cuántos", "cuántas", "cada", "cuál", "cuáles", "cómo", "dónde", "cuándo", "qué", "quién", "quiénes"],
)
def test_interrogativos_y_cuantificadores_no_cuentan(word):
    assert tokenize(word) == []


def test_una_pregunta_no_pesa_por_sus_interrogativos(tmp_path):
    # Medido en Bolitabot: "cuánto" y "cada", ausentes, dejaban la cobertura en 0,20.
    document = "T_v tramo trebol tiempos"
    words = words_with(tmp_path, [document, "otra cosa", "una mas"])

    assert coverage_of(words, "cuánto dura cada tramo del trébol", document) == coverage_of(words, "dura tramo trébol", document)


def test_todo_sigue_siendo_buscable():
    assert tokenize("TODO") == [stem("todo")]


def test_el_mismo_verbo_cuenta_como_la_misma_palabra():
    assert tokenize("detectan") == tokenize("detectar")
    assert tokenize("usuarios") == tokenize("usuario")
    assert tokenize("guardan") == tokenize("guardar")


def words_with(folder, documents, collection="prueba"):
    words = WordIndex(folder)
    words.add(collection, [str(i) for i in range(len(documents))], documents, [{}] * len(documents))
    return words


def top_ids(words, query, limit=5, collections=("prueba",)):
    return [row[0] for row in words.top(query, list(collections), limit)]


def coverage_of(words, query, document, collections=("prueba",)):
    return words.coverage(query, [document], list(collections))[0]


def test_encuentra_otra_forma_de_la_palabra(tmp_path):
    words = words_with(tmp_path, ["def otra():\n    pass", "para detectar rutas inventadas", "cliente de correo"])

    assert top_ids(words, "cómo se detectan")[0] == "1"


def test_la_cobertura_entiende_otra_forma_de_la_palabra(tmp_path):
    words = words_with(tmp_path, ["para detectar rutas", "otra cosa"])

    assert coverage_of(words, "detectan rutas", "para detectar rutas") == 1.0


def test_un_nombre_exacto_sigue_coincidiendo_consigo_mismo(tmp_path):
    assert top_ids(words_with(tmp_path, ["def is_clear_chat():", "otra"]), "is_clear_chat")[0] == "0"


def test_encuentra_el_nombre_exacto(tmp_path):
    documents = ["def otra():\n    pass", "def drop_client(owner):\n    pass", "cliente de correo"]

    assert top_ids(words_with(tmp_path, documents), "drop_client")[0] == "1"


def test_el_guion_bajo_es_parte_de_la_palabra(tmp_path):
    words = words_with(tmp_path, ["x_front = 1", "front y x separados"])

    assert top_ids(words, "x_front")[0] == "0"


def test_una_palabra_rara_pesa_mas_que_una_comun(tmp_path):
    documents = ["modelo modelo", "modelo", "modelo piper", "modelo"]

    assert top_ids(words_with(tmp_path, documents), "modelo piper")[0] == "2"


def test_sin_coincidencias_no_devuelve_nada(tmp_path):
    words = words_with(tmp_path, ["uno dos"])

    assert words.top("tres", ["prueba"], 5) == []
    assert words.top("de la", ["prueba"], 5) == []
    assert WordIndex(tmp_path / "vacio").top("tres", ["prueba"], 5) == []


def test_devuelve_el_documento_y_sus_metadatos(tmp_path):
    words = WordIndex(tmp_path)
    words.add("prueba", ["a"], ["kp ganancia"], [{"file_path": "pid.py", "start_line": 3}])

    [(chunk_id, document, metadata, score)] = words.top("ganancia", ["prueba"], 5)

    assert (chunk_id, document) == ("a", "kp ganancia") and metadata["start_line"] == 3 and score > 0


def test_la_cobertura_no_depende_del_tamano_de_la_coleccion(tmp_path):
    small = words_with(tmp_path / "s", ["kp ganancia", "otra cosa"])
    large = words_with(tmp_path / "l", ["kp ganancia"] + [f"relleno{i} cosa" for i in range(500)])

    assert coverage_of(small, "ganancia", "kp ganancia") == 1.0 == coverage_of(large, "ganancia", "kp ganancia")
    # "mole" no sale en ningún lado y pesa más que "ganancia".
    assert 0 < coverage_of(small, "ganancia mole", "kp ganancia") < 0.5
    assert coverage_of(large, "receta de mole", "kp ganancia") == 0.0
    assert coverage_of(WordIndex(tmp_path / "v"), "de la", "algo") == 0.0


def test_cada_coleccion_tiene_sus_frecuencias(tmp_path):
    words = words_with(tmp_path, ["tramo uno", "tramo dos"], "pequena")
    words.add("grande", [str(i) for i in range(50)], [f"relleno{i}" for i in range(50)], [{}] * 50)

    assert words.frequencies(["tram"], ["pequena"]) == (2, {"tram": 2})
    assert words.frequencies(["tram"], ["pequena", "grande"]) == (52, {"tram": 2})


def test_busca_en_varias_colecciones(tmp_path):
    words = words_with(tmp_path, ["alfa unica"], "uno")
    words.add("dos", ["b"], ["beta unica"], [{}])

    assert top_ids(words, "beta", collections=("uno", "dos")) == ["b"]
    assert top_ids(words, "beta", collections=("uno",)) == []


def test_reemplaza_un_fragmento_con_el_mismo_id(tmp_path):
    words = words_with(tmp_path, ["texto viejo"])

    words.add("prueba", ["0"], ["texto nuevo"], [{}])

    assert words.count("prueba") == 1
    assert top_ids(words, "viejo") == [] and top_ids(words, "nuevo") == ["0"]


def test_borra_fragmentos(tmp_path):
    words = words_with(tmp_path, ["uno", "dos", "tres"])

    words.delete("prueba", ["1"])

    assert words.count("prueba") == 2 and top_ids(words, "dos") == []


def test_un_nombre_de_coleccion_con_punto_y_guion(tmp_path):
    words = words_with(tmp_path, ["kp ganancia"], "mi-fuente.v2")

    assert top_ids(words, "ganancia", collections=("mi-fuente.v2",)) == ["0"]


def indexed_store(folder, *documents):
    store = VectorStore(persist_dir=folder, collection_name="prueba")
    ids = [str(i) for i in range(len(documents))]
    store.add_documents(ids, list(documents), [[0.1, 0.2]] * len(ids), [{"file_path": f"{i}.py"} for i in ids])
    return store


def test_el_almacen_mantiene_las_palabras_al_dia(tmp_path):
    store = indexed_store(tmp_path, "kp ganancia", "otra cosa")

    assert store.words.count("prueba") == 2

    store.delete_where_file_path(lambda path: path == "0.py")

    assert store.words.count("prueba") == 1 and store.collection.count() == 1


def test_un_indice_sin_palabras_se_rehace_desde_chroma(tmp_path):
    store = indexed_store(tmp_path, "kp ganancia", "otra cosa")
    store.words.path.unlink()

    store.sync_words()

    assert store.words.count("prueba") == 2
    assert [row[0] for row in store.words.top("ganancia", ["prueba"], 5)] == ["0"]


def test_las_palabras_incompletas_se_rehacen(tmp_path):
    store = indexed_store(tmp_path, "kp ganancia", "otra cosa")
    store.words.delete("prueba", ["0"])

    store.sync_words()

    assert store.words.count("prueba") == 2


def test_sin_diferencias_no_rehace_nada(tmp_path, monkeypatch):
    store = indexed_store(tmp_path, "kp ganancia")

    def forbidden(*args):
        raise AssertionError("no debe rehacerse")

    monkeypatch.setattr(store.words, "rebuild", forbidden)

    store.sync_words()


def test_sin_colecciones_no_hay_resultados(embeddings):  # noqa: F811
    assert search_collections("algo", [], n_results=5) == []


def pair(key, file_path="a.py", **values):
    return key, Hit(f"doc {key}", {"file_path": file_path}, **values)


def test_lo_que_sale_en_las_dos_listas_gana():
    vector = [pair("solo_vector", distance=0.1), pair("ambas", distance=0.2, file_path="b.py")]
    keyword = [pair("solo_palabras", file_path="c.py", keyword_score=5.0), pair("ambas", file_path="b.py", keyword_score=4.0)]

    hits = merge(vector, keyword, 3)

    assert hits[0].document == "doc ambas"
    assert hits[0].distance == 0.2 and hits[0].keyword_score == 4.0
    assert {h.document for h in hits} == {"doc ambas", "doc solo_vector", "doc solo_palabras"}


def test_un_archivo_no_acapara_los_resultados():
    vector = [pair(i, "ROADMAP.md", distance=i / 10) for i in range(6)] + [pair("otro", "b.py", distance=0.9)]

    hits = merge(vector, [], 5)

    assert sum(h.metadata["file_path"] == "ROADMAP.md" for h in hits) == MAX_PER_FILE
    assert hits[-1].document == "doc otro"


def test_de_punta_a_punta_encuentra_un_nombre_que_los_embeddings_no(tmp_path, embeddings):  # noqa: F811
    project = tmp_path / "proyecto"
    project.mkdir()
    names = ["uno", "dos", "tres", "cuatro"]

    for name in names:
        (project / f"{name}.py").write_text(f"def funcion_{name}():\n    return 1\n", encoding="utf-8")

    (project / "objetivo.py").write_text("def calibrar_ganancia():\n    return 1\n", encoding="utf-8")
    ProjectIndexer(str(project), "prueba", persist_dir=tmp_path / "i").index_project()

    hits = search_collections("calibrar_ganancia", ["prueba"], n_results=1, persist_dir=tmp_path / "i")

    assert hits[0].metadata["relative_path"] == "objetivo.py" and hits[0].keyword_score > 0


def test_varias_colecciones(tmp_path, embeddings):  # noqa: F811
    for name, text in (("uno", "def alfa_unica():\n    pass\n"), ("dos", "def beta_unica():\n    pass\n")):
        project = tmp_path / name
        project.mkdir()
        (project / "a.py").write_text(text, encoding="utf-8")
        ProjectIndexer(str(project), name, persist_dir=tmp_path / "i").index_project()

    hits = search_collections("beta_unica", ["uno", "dos"], n_results=1, persist_dir=tmp_path / "i")

    assert hits[0].metadata["source"] == "dos"
