"""Troceado por funciones y secciones, y reindexado incremental por hash."""
import pytest

from core.rag import indexer as indexer_module
from core.rag.chunking import MAX_CHARS, chunk_text
from core.rag.indexer import ProjectIndexer
from test_rag_index import embeddings  # noqa: F401

PYTHON = '''"""Módulo."""
import os

LIMITE = 3


def suma(a, b):
    return a + b


class Control:
    """Un controlador."""
    GANANCIA = 2

    def __init__(self):
        self.x = 0

    @property
    def salida(self):
        return self.x * self.GANANCIA


async def espera():
    pass
'''


def labels(chunks):
    return [chunk.label for chunk in chunks]


def by_label(chunks, label):
    return next(chunk for chunk in chunks if chunk.label == label)


def test_python_por_funciones_y_metodos():
    chunks = chunk_text(PYTHON, ".py")

    assert {"suma", "Control.__init__", "Control.salida", "espera", "Control"} <= set(labels(chunks))
    assert by_label(chunks, "suma").text == "def suma(a, b):\n    return a + b"
    assert (by_label(chunks, "suma").start_line, by_label(chunks, "suma").end_line) == (7, 8)


def test_el_decorador_va_con_su_metodo():
    assert by_label(chunk_text(PYTHON, ".py"), "Control.salida").text.startswith("    @property")


def test_la_cabecera_de_la_clase_y_lo_de_fuera_no_se_pierden():
    chunks = chunk_text(PYTHON, ".py")

    assert '"""Un controlador."""' in by_label(chunks, "Control").text
    assert "GANANCIA = 2" in by_label(chunks, "Control").text
    assert any(c.label == "" and "LIMITE = 3" in c.text and "import os" in c.text for c in chunks)


def test_todas_las_lineas_con_contenido_quedan_cubiertas():
    covered = set()

    for chunk in chunk_text(PYTHON, ".py"):
        covered |= set(range(chunk.start_line, chunk.end_line + 1))

    lines = PYTHON.splitlines()
    assert all(i in covered for i, line in enumerate(lines, 1) if line.strip())


def test_python_con_error_de_sintaxis_va_por_bloques():
    chunks = chunk_text("def roto(:\n    pass\n", ".py")

    assert len(chunks) == 1 and chunks[0].label == ""


def test_funcion_larga_se_parte_con_solape():
    body = "".join(f"    x{i} = {i}\n" for i in range(300))
    chunks = chunk_text(f"def larga():\n{body}", ".py")

    assert len(chunks) > 1 and set(labels(chunks)) == {"larga"}
    assert all(len(chunk.text) <= MAX_CHARS for chunk in chunks)
    assert chunks[1].start_line <= chunks[0].end_line
    assert chunks[-1].end_line == 301


def test_una_linea_enorme_no_cuelga_y_se_acota():
    chunks = chunk_text("x" * 50000, ".txt")

    assert len(chunks) == 1 and len(chunks[0].text) <= MAX_CHARS * 2


MARKDOWN = """Intro.

# Voz

Texto de voz.

## J2

Frase por frase.

```python
# esto no es un título: sale igual en su sección
```

# Otra

Fin.
"""


def test_markdown_por_secciones_con_su_ruta():
    chunks = chunk_text(MARKDOWN, ".md")

    assert labels(chunks)[:3] == ["", "Voz", "Voz > J2"]
    assert by_label(chunks, "Voz > J2").text.startswith("## J2")
    assert by_label(chunks, "Otra").text.endswith("Fin.")


def test_tex_por_secciones():
    text = "\\documentclass{article}\n\\section{Modelo}\nTexto.\n\\subsection*{PID}\nMás.\n\\section{Fin}\nYa.\n"

    assert labels(chunk_text(text, ".tex")) == ["", "Modelo", "Modelo > PID", "Fin"]


def test_otros_lenguajes_por_bloques():
    block = "\n".join(f"int x{i} = {i};" for i in range(20))
    text = f"{block}\n\n{block}\n\n{block}\n"

    chunks = chunk_text(text, ".c")

    assert len(chunks) == 3 and chunks[1].start_line == 22


def test_vacio():
    assert chunk_text("", ".py") == [] and chunk_text("\n\n", ".md") == []


# --- Reindexado incremental --------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    (root / "a.py").write_text("def uno():\n    return 1\n", encoding="utf-8")
    (root / "b.py").write_text("def dos():\n    return 2\n", encoding="utf-8")
    return root


def indexer_of(project, tmp_path):
    return ProjectIndexer(str(project), "prueba", persist_dir=tmp_path / "indice")


def documents_of(indexer):
    return indexer.store.collection.get(include=["documents"])["documents"]


def embedded(fake):
    return sum(fake.batches)


def test_sin_cambios_no_embebe_nada(tmp_path, project, embeddings):  # noqa: F811
    indexer_of(project, tmp_path).index_project()
    first = embedded(embeddings)

    again = indexer_of(project, tmp_path)
    count = again.index_project()

    assert embedded(embeddings) == first and count == 2
    assert (again.changed, again.unchanged) == (0, 2)


def test_solo_lo_que_cambio(tmp_path, project, embeddings):  # noqa: F811
    indexer_of(project, tmp_path).index_project()
    first = embedded(embeddings)
    (project / "a.py").write_text("def uno_nuevo():\n    return 11\n", encoding="utf-8")

    indexer = indexer_of(project, tmp_path)
    indexer.index_project()

    assert embedded(embeddings) == first + 1 and indexer.changed == 1
    documents = " ".join(documents_of(indexer))
    assert "uno_nuevo" in documents and "def uno()" not in documents and "def dos" in documents


def test_archivo_borrado_sale_del_indice(tmp_path, project, embeddings):  # noqa: F811
    indexer_of(project, tmp_path).index_project()
    (project / "a.py").unlink()

    indexer = indexer_of(project, tmp_path)

    assert indexer.index_project() == 1 and "def uno" not in " ".join(documents_of(indexer))


def test_si_ollama_falla_el_indice_queda_como_estaba(tmp_path, project, embeddings, monkeypatch):  # noqa: F811
    indexer_of(project, tmp_path).index_project()
    (project / "a.py").write_text("def otra():\n    pass\n", encoding="utf-8")
    indexer = indexer_of(project, tmp_path)

    def broken(texts):
        raise ConnectionError("sin Ollama")

    monkeypatch.setattr(indexer.embedder, "embed_documents", broken)

    with pytest.raises(ConnectionError):
        indexer.index_project()

    assert "def uno" in " ".join(documents_of(indexer))


def test_cambiar_el_troceado_reindexa_todo(tmp_path, project, embeddings, monkeypatch):  # noqa: F811
    indexer_of(project, tmp_path).index_project()
    monkeypatch.setattr(indexer_module, "CHUNKER_VERSION", "2")

    indexer = indexer_of(project, tmp_path)
    indexer.index_project()

    assert indexer.changed == 2


def test_un_indice_viejo_sin_hash_se_reemplaza(tmp_path, project, embeddings):  # noqa: F811
    indexer = indexer_of(project, tmp_path)
    indexer.store.add_documents(["viejo"], ["texto viejo"], [[1.0, 1.0, 1.0]], [{"file_path": "launcher.py", "chunk": 0}])

    indexer.index_project()

    assert "texto viejo" not in documents_of(indexer)


def test_no_toca_lo_de_otras_carpetas_de_la_coleccion(tmp_path, project, embeddings):  # noqa: F811
    indexer = indexer_of(project, tmp_path)
    other = (tmp_path / "otra" / "a.py").as_posix()
    indexer.store.add_documents(["otra"], ["de otra carpeta"], [[1.0, 1.0, 1.0]], [{"file_path": other}])

    indexer.index_project()

    assert "de otra carpeta" in documents_of(indexer)
