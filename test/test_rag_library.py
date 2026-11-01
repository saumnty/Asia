"""Fuentes con nombre: colecciones, citas, /indexar, /fuentes y "en <fuente>"."""
import pytest

from core.actions.library import USAGE, parse_source
from core.commands import COMMANDS, options_text
from core.prompts import NOT_FOUND
from core.provenance import RAG, TOOL_LABELS
from core.rag.chunking import chunk_text
from core.rag.indexer import ProjectIndexer
from core.rag.library import Library, Source, citation, fragment_header, named_in_question, without_source
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
        ({"relative_path": "controlador.py", "start_line": 40, "end_line": 55}, "controlador.py:40-55"),
        ({"relative_path": "a.py", "start_line": 7, "end_line": 7}, "a.py:7"),
        ({"file_path": "viejo.py", "chunk": 3}, "viejo.py"),
    ],
)
def test_cita(metadata, expected):
    assert citation(metadata) == expected


def test_encabezado_de_fragmento():
    metadata = {"relative_path": "launcher.py", "start_line": 40, "end_line": 55}

    assert fragment_header(metadata) == "--- [launcher.py:40-55] ---"
    assert fragment_header({**metadata, "label": "main"}) == "--- [launcher.py:40-55] main ---"


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
        ("Bolitabot", ("Bolitabot", None, None, "", "", {})),
        ("Bolitabot C:\\robots", ("Bolitabot", "C:\\robots", None, "", "", {})),
        ("Notas C:\\notas notas", ("Notas", "C:\\notas", "notas", "", "", {})),
        ("Tesis reporte", ("Tesis", None, "reporte", "", "", {})),
        ('Tesis "C:\\mis docs" reporte', ("Tesis", "C:\\mis docs", "reporte", "", "", {})),
        (
            'ros2 C:\\docs documentacion https://docs.ros.org/en/jazzy/{}.html "CC BY 4.0"',
            ("ros2", "C:\\docs", "documentacion", "https://docs.ros.org/en/jazzy/{}.html", "CC BY 4.0", {}),
        ),
        ("ros2 https://a.org/{}", ("ros2", None, None, "https://a.org/{}", "", {})),
        ("asia-pruebas C:\\Asia\\test solo-nombrada", ("asia-pruebas", "C:\\Asia\\test", None, "", "", {"named_only": True})),
        ("ros2 C:\\docs https://a.org/sin-marca", None),
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


def test_reindexar_sin_ruta_conserva_la_fuente(tmp_path, embeddings, monkeypatch):  # noqa: F811
    monkeypatch.setattr("tools.rag_tool.unload_chat_models", lambda: None)
    monkeypatch.setattr("tools.rag_tool.ProjectIndexer", indexer_in(tmp_path / "i"))
    project = tmp_path / "docs"
    project.mkdir()
    (project / "a.md").write_text("# Hola\n\nTexto.\n", encoding="utf-8")
    brain = make_brain()
    brain.tool_registry = Registry()
    brain.process(f'/indexar ros2 "{project}" documentacion solo-nombrada')

    brain.process("/indexar ros2")

    saved = Library().get("ros2")
    assert (saved.path, saved.kind, saved.named_only) == (project.as_posix(), "documentacion", True)


def test_una_fuente_vieja_no_es_solo_nombrada():
    library = Library()
    library.path.parent.mkdir(parents=True)
    library.path.write_text(
        '[{"name": "a", "kind": "proyecto", "path": "C:/a", "collection": "aaa", "fragments": 1, "indexed": "x"}]',
        encoding="utf-8",
    )

    assert not library.get("a").named_only


def collections_searched(monkeypatch, question):
    searched = []

    def search(query, collections, **kwargs):
        searched.extend(collections)
        return []

    monkeypatch.setattr("tools.rag_tool.search_collections", search)
    RagTool().search_project(question, "asia")
    return searched


def test_una_fuente_solo_nombrada_no_entra_en_una_busqueda_general(monkeypatch):
    Library().save("asia", "proyecto", "C:/Asia", 10)
    Library().save("asia-pruebas", "proyecto", "C:/Asia/test", 5, named_only=True)

    assert collections_searched(monkeypatch, "cómo se escribe un archivo") == ["asia"]


def test_una_fuente_solo_nombrada_se_consulta_si_se_nombra(monkeypatch):
    Library().save("asia", "proyecto", "C:/Asia", 10)
    Library().save("asia-pruebas", "proyecto", "C:/Asia/test", 5, named_only=True)

    assert collections_searched(monkeypatch, "cómo se prueba el filtro en asia-pruebas") == ["asia-pruebas"]
    assert collections_searched(monkeypatch, "cómo se prueba el filtro en asia")[-1] == "asia"


def test_fuentes_dice_cual_solo_se_consulta_si_se_nombra():
    Library().save("asia-pruebas", "proyecto", "C:/Asia/test", 5, named_only=True)

    assert "asia-pruebas (proyecto, solo si se nombra)" in make_brain().process("/fuentes")


def test_sin_fuentes_lo_dice():
    assert "Aún no hay fuentes" in make_brain().process("/fuentes")


def test_en_la_tabla_de_opciones():
    for slash in ("/indexar <nombre> [ruta] [tipo] [url] [licencia]", "/fuentes"):
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
        lambda question, collections, n_results, **options: search_collections(question, collections, n_results, folder, **options),
    )

    everywhere = RagTool().search_project("aaaa bbbb", "asia")
    only_one = RagTool().search_project("bbbb en Dos", "asia")

    assert "Fuente: Uno (proyecto)" in everywhere and "Fuente: Dos (proyecto)" in everywhere
    assert "--- [a.py:1] ---" in everywhere and "Fragmento" not in everywhere
    assert "Fuente: Dos (proyecto)" in only_one and "Fuente: Uno" not in only_one


def test_el_nombre_de_la_fuente_no_se_busca():
    assert without_source("cómo funciona el PID en Bolitabot", source("Bolitabot")) == "cómo funciona el PID"
    assert without_source("qué dice en la fuente Notas sobre PID", source("Notas")) == "qué dice sobre PID"


def test_sin_resultados_no_inventa(monkeypatch):
    monkeypatch.setattr("tools.rag_tool.search_collections", lambda *a, **k: [])

    assert RagTool().search_project("algo", "asia") == NOT_FOUND


def test_la_busqueda_lleva_la_etiqueta_rag():
    assert TOOL_LABELS["search_project_rag"] == RAG
