"""Fuentes con nombre: colecciones, citas, /indexar, /fuentes y "en <fuente>"."""
import pytest

from core.actions.library import USAGE, parse_source
from core.commands import COMMANDS, options_text
from core.provenance import RAG, TOOL_LABELS
from core.rag.chunking import chunk_text
from core.rag.indexer import ProjectIndexer
from core.rag.library import Library, Source, citation, named_in_question
from core.rag.retriever import search_collections
from test_confidencial import make_brain
from test_rag_index import embeddings  # noqa: F401
from tools.rag_tool import RagTool


def source(name, kind="proyecto"):
    return Source(name, kind, "C:/x", name.lower())


def test_cada_fragmento_guarda_fuente_archivo_y_lineas(tmp_path, embeddings):  # noqa: F811
    project = tmp_path / "bolita"
    (project / "control").mkdir(parents=True)
    (project / "control" / "pid.py").write_text("\n" * 3 + "a = 1\nb = 2\n", encoding="utf-8")

    indexer = ProjectIndexer(str(project), "Bolitabot", persist_dir=tmp_path / "i", kind="reporte")
    indexer.index_project()

    [metadata] = indexer.store.collection.get(include=["metadatas"])["metadatas"]
    assert metadata["source"] == "Bolitabot" and metadata["kind"] == "reporte"
    assert metadata["relative_path"] == "control/pid.py"
    assert (metadata["start_line"], metadata["end_line"]) == (4, 5)


def test_lineas_de_cada_fragmento():
    text = "".join(f"linea{i}\n" for i in range(1, 400))

    chunks = chunk_text(text, ".txt")

    assert len(chunks) > 1
    lines = text.split("\n")

    for chunk in chunks:
        # Cada fragmento está dentro de las líneas que dice ocupar.
        assert chunk.text == "\n".join(lines[chunk.start_line - 1:chunk.end_line])


@pytest.mark.parametrize(
    "metadata, expected",
    [
        ({"relative_path": "controlador.py", "start_line": 40, "end_line": 55}, "controlador.py, líneas 40–55"),
        ({"relative_path": "a.py", "start_line": 7, "end_line": 7}, "a.py, línea 7"),
        ({"file_path": "viejo.py", "chunk": 3}, "viejo.py"),
    ],
)
def test_cita(metadata, expected):
    assert citation(metadata) == expected


def test_registro_guarda_y_actualiza(tmp_path):
    library = Library()

    library.save("Bolitabot", "proyecto", "C:/robots", 10)
    library.save("Notas", "notas", "C:/notas", 3)
    library.save("bolitabot", "reporte", "C:/otra", 20)

    names = {(s.name, s.kind, s.fragments) for s in library.all()}
    assert names == {("Notas", "notas", 3), ("bolitabot", "reporte", 20)}
    assert library.get("BOLITABOT").path == "C:/otra"


@pytest.mark.parametrize(
    "question, expected",
    [
        ("cómo funciona el PID en Bolitabot", "Bolitabot"),
        ("qué dice el reporte en la fuente Notas", "Notas"),
        ("cómo funciona el PID en el proyecto bolitabot", "Bolitabot"),
        ("cómo funciona el PID", None),
        ("en Bolitabots hay algo", None),
    ],
)
def test_en_fuente(question, expected):
    found = named_in_question(question, [source("Bolitabot"), source("Notas", "notas")])

    assert (found.name if found else None) == expected


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("Bolitabot", ("Bolitabot", ".", "proyecto")),
        ("Bolitabot C:\\robots", ("Bolitabot", "C:\\robots", "proyecto")),
        ("Notas C:\\notas notas", ("Notas", "C:\\notas", "notas")),
        ("Tesis reporte", ("Tesis", ".", "reporte")),
        ('Tesis "C:\\mis docs" reporte', ("Tesis", "C:\\mis docs", "reporte")),
        ("", None),
        ("a b c d", None),
        ("a b c", None),
    ],
)
def test_parse_source(spec, expected):
    assert parse_source(spec) == expected


def test_indexar_y_fuentes(tmp_path, embeddings, monkeypatch):  # noqa: F811
    monkeypatch.setattr("tools.rag_tool.unload_chat_models", lambda: None)
    monkeypatch.setattr("tools.rag_tool.ProjectIndexer", indexer_in(tmp_path / "i"))
    project = tmp_path / "bolita"
    project.mkdir()
    (project / "pid.py").write_text("kp = 1\n", encoding="utf-8")
    brain = make_brain()
    brain.tool_registry = Registry()

    answer = brain.process(f'/indexar Bolitabot "{project}" proyecto')

    assert "Fuente 'Bolitabot' al día: 1 fragmentos" in answer
    listed = brain.process("/fuentes")
    assert "Bolitabot (proyecto): 1 fragmentos" in listed


class Registry:
    def execute(self, action, **kwargs):
        assert action == "index_project_rag"
        return RagTool().index_project(**kwargs)


def indexer_in(folder):
    def build(**kwargs):
        return ProjectIndexer(persist_dir=folder, **kwargs)

    return build


def test_indexar_mal_escrito_explica():
    assert make_brain().process("/indexar") == USAGE


def test_sin_fuentes_lo_dice():
    assert "Aún no hay fuentes" in make_brain().process("/fuentes")


def test_en_la_tabla_de_opciones():
    for slash in ("/indexar <nombre> [ruta] [tipo]", "/fuentes"):
        assert any(c.slash == slash and c.group == "biblioteca" for c in COMMANDS)
        assert slash in options_text()


def test_busca_en_todas_las_fuentes_y_dice_de_donde_viene(tmp_path, embeddings, monkeypatch):  # noqa: F811
    folder = tmp_path / "i"

    for name, text in (("Uno", "aaaa = 1\n"), ("Dos", "bbbb = 2\n")):
        project = tmp_path / name
        project.mkdir()
        (project / "a.py").write_text(text, encoding="utf-8")
        ProjectIndexer(str(project), name, persist_dir=folder).index_project()
        Library().save(name, "proyecto", str(project), 1)

    monkeypatch.setattr(
        "tools.rag_tool.search_collections",
        lambda question, collections, n_results: search_collections(question, collections, n_results, folder),
    )

    everywhere = RagTool().search_project("qué hay", "asia")
    only_one = RagTool().search_project("qué hay en Dos", "asia")

    assert "Fuente: Uno (proyecto)" in everywhere and "Fuente: Dos (proyecto)" in everywhere
    assert "Cita: a.py, línea 1" in everywhere
    assert "Fuente: Dos (proyecto)" in only_one and "Fuente: Uno" not in only_one


def test_sin_resultados_no_inventa(monkeypatch):
    monkeypatch.setattr("tools.rag_tool.search_collections", lambda *a, **k: [])

    assert "No encontré" in RagTool().search_project("algo", "asia")


def test_la_busqueda_lleva_la_etiqueta_rag():
    assert TOOL_LABELS["search_project_rag"] == RAG
