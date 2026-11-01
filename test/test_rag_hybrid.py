"""Búsqueda híbrida: BM25 propio y fusión con los embeddings."""
from core.rag.bm25 import BM25, stem, tokenize
from core.rag.indexer import ProjectIndexer
from core.rag.retriever import MAX_PER_FILE, Hit, merge, search_collections
from test_rag_index import embeddings  # noqa: F401


def test_parte_los_nombres_como_en_el_codigo():
    assert {stem(t) for t in ("drop_client", "drop", "client")} <= set(tokenize("drop_client"))
    assert {stem(t) for t in ("sessionsummarizer", "session", "summarizer")} <= set(tokenize("SessionSummarizer"))
    assert {stem(t) for t in ("margin_frames", "margin", "frames")} <= set(tokenize("MARGIN_FRAMES"))
    assert {stem(t) for t in ("http", "client")} <= set(tokenize("HTTPClient"))


def test_sin_acentos_ni_palabras_vacias():
    assert set(tokenize("la sesión de pruebas")) == {stem("sesion"), stem("pruebas")}


def test_el_mismo_verbo_cuenta_como_la_misma_palabra():
    assert tokenize("detectan") == tokenize("detectar")
    assert tokenize("usuarios") == tokenize("usuario")
    assert tokenize("guardan") == tokenize("guardar")


def test_encuentra_otra_forma_de_la_palabra():
    documents = ["def otra():\n    pass", "para detectar rutas inventadas", "cliente de correo"]

    assert BM25(documents).top("cómo se detectan", 3)[0][0] == 1


def test_la_cobertura_entiende_otra_forma_de_la_palabra():
    words = BM25(["para detectar rutas", "otra cosa"])

    assert words.coverage("detectan rutas", "para detectar rutas") == 1.0


def test_un_nombre_exacto_sigue_coincidiendo_consigo_mismo():
    assert BM25(["def is_clear_chat():", "otra"]).top("is_clear_chat", 2)[0][0] == 0


def test_encuentra_el_nombre_exacto():
    documents = ["def otra():\n    pass", "def drop_client(owner):\n    pass", "cliente de correo"]

    assert BM25(documents).top("drop_client", 3)[0][0] == 1


def test_una_palabra_rara_pesa_mas_que_una_comun():
    documents = ["modelo modelo", "modelo", "modelo piper", "modelo"]

    assert BM25(documents).top("modelo piper", 4)[0][0] == 2


def test_sin_coincidencias_no_devuelve_nada():
    assert BM25(["uno dos"]).top("tres", 5) == []
    assert BM25([]).top("tres", 5) == []


def test_la_cobertura_no_depende_del_tamano_de_la_coleccion():
    small = BM25(["kp ganancia", "otra cosa"])
    large = BM25(["kp ganancia"] + [f"relleno{i} cosa" for i in range(500)])

    assert small.coverage("ganancia", "kp ganancia") == 1.0 == large.coverage("ganancia", "kp ganancia")
    # "mole" no sale en ningún lado y pesa más que "ganancia".
    assert 0 < small.coverage("ganancia mole", "kp ganancia") < 0.5
    assert large.coverage("receta de mole", "kp ganancia") == 0.0
    assert BM25([]).coverage("de la", "algo") == 0.0


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
