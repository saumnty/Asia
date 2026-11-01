"""Fuentes públicas: sus fragmentos pueden salir; si se mezclan con una privada, no.

ToolRegistry y ProviderRouter reales, con Gemini y Ollama simulados: nada sale de verdad.
"""
import json

import pytest

from config.settings_manager import SettingsManager
from core import paths
from core.actions.library import PUBLIC_USAGE
from core.commands import COMMANDS, options_text
from core.confidential import LOCAL_MODE
from core.prompts import NOT_FOUND
from core.provenance import ADJUNTO, PUBLICA, RAG, USUARIO, Fragment, LabeledResult, most_restrictive, record
from core.rag.indexer import ProjectIndexer
from core.rag.library import Library
from core.rag.retriever import Hit
from test_confidencial import gemini_text, make_brain
from test_rag_index import embeddings  # noqa: F401
from tools.rag_tool import RagTool
from tools.tool_registry import ToolRegistry

DOC = "La lista de politicas de QoS"
PRIVATE = "SECRETO_DE_BOLITABOT"


def hit(text, source):
    metadata = {"relative_path": "a.md", "start_line": 1, "end_line": 2, "source": source, "kind": "documentacion"}
    return Hit(f"a.md\n{text}", metadata, distance=1.0, coverage=1.0)


@pytest.fixture
def library(monkeypatch):
    Library().save("ros2", "documentacion", "C:/docs", 10)
    Library().save("gazebo", "documentacion", "C:/gz", 10)
    Library().save("bolitabot", "proyecto", "C:/robot", 10)
    Library().set_public("ros2", True)
    Library().set_public("gazebo", True)

    def search(question, collections, **options):
        return [hit(PRIVATE if name == "bolitabot" else DOC, name) for name in collections]

    monkeypatch.setattr("tools.rag_tool.search_collections", search)


def brain_on_gemini():
    SettingsManager.set_overrides({"default_provider": "gemini"})
    brain = make_brain()
    brain.tool_registry = ToolRegistry(brain.provider_router)
    return brain


def audit():
    path = paths.EXTERNAL_AUDIT_FILE
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_por_defecto_una_fuente_no_es_publica():
    assert Library().save("a", "proyecto", "C:/a", 1).publica is False


def test_una_fuente_vieja_no_es_publica():
    library = Library()
    library.path.parent.mkdir(parents=True)
    library.path.write_text(
        '[{"name": "a", "kind": "proyecto", "path": "C:/a", "collection": "aaa", "fragments": 1, "indexed": "x"}]',
        encoding="utf-8",
    )

    assert library.get("a").publica is False


def test_el_registro_guarda_el_atributo_publica():
    Library().save("a", "proyecto", "C:/a", 1)
    Library().set_public("A", True)

    assert json.loads(paths.SOURCES_FILE.read_text(encoding="utf-8"))[0]["publica"] is True


def test_marcar_una_fuente_no_toca_las_demas():
    Library().save("a", "proyecto", "C:/a", 1)
    Library().save("b", "proyecto", "C:/b", 2)

    Library().set_public("b", True)

    assert [(s.name, s.publica) for s in Library().all()] == [("a", False), ("b", True)]


def test_marcar_una_fuente_que_no_existe():
    assert Library().set_public("nada", True) is None


def test_reindexar_conserva_publica(tmp_path, embeddings, monkeypatch):  # noqa: F811
    monkeypatch.setattr("tools.rag_tool.unload_chat_models", lambda: None)
    monkeypatch.setattr("tools.rag_tool.ProjectIndexer", lambda **kwargs: ProjectIndexer(persist_dir=tmp_path / "i", **kwargs))
    project = tmp_path / "docs"
    project.mkdir()
    (project / "a.md").write_text("# Hola\n\nTexto.\n", encoding="utf-8")
    RagTool().index_project("ros2", str(project))
    Library().set_public("ros2", True)

    RagTool().index_project("ros2")

    assert Library().get("ros2").publica is True


@pytest.mark.parametrize("answer, expected", [("sí", True), ("si", True), ("SÍ", True), ("no", False)])
def test_comando_publica(answer, expected):
    Library().save("ros2", "documentacion", "C:/docs", 10)
    Library().set_public("ros2", not expected)

    shown = make_brain().process(f"/publica ROS2 {answer}")

    assert Library().get("ros2").publica is expected
    assert ("pública" if expected else "privada") in shown


@pytest.mark.parametrize("spec", ["", "ros2", "ros2 quiza", "ros2 si no"])
def test_publica_mal_escrito_explica(spec):
    Library().save("ros2", "documentacion", "C:/docs", 10)

    assert make_brain().process(f"/publica {spec}".strip()) == PUBLIC_USAGE
    assert not Library().get("ros2").publica


def test_publica_de_una_fuente_que_no_existe():
    assert "No conozco la fuente 'nada'" in make_brain().process("/publica nada sí")


def test_fuentes_dice_cual_es_publica():
    Library().save("ros2", "documentacion", "C:/docs", 10)
    Library().set_public("ros2", True)

    assert "ros2 (documentacion, pública)" in make_brain().process("/fuentes")


def test_en_la_tabla_de_opciones():
    assert any(c.slash == "/publica <fuente> sí|no" and c.group == "biblioteca" for c in COMMANDS)
    assert "/publica <fuente> sí|no" in options_text()


def test_publica_es_menos_restrictiva_que_cualquier_local():
    assert most_restrictive({PUBLICA, RAG}) == RAG
    assert most_restrictive({PUBLICA, USUARIO}) == PUBLICA


def test_un_resultado_con_etiqueta_sigue_siendo_texto():
    assert LabeledResult(NOT_FOUND, PUBLICA) == NOT_FOUND


def label_of(question):
    return getattr(RagTool().search_project(question, "asia"), "label", None)


def test_la_etiqueta_es_publica_solo_si_todo_lo_consultado_lo_es(library):
    assert label_of("politicas en ros2") == PUBLICA
    assert label_of("politicas en bolitabot") == RAG
    assert label_of("politicas") == RAG


def test_una_busqueda_general_con_solo_fuentes_publicas_es_publica(library):
    Library().set_public("bolitabot", True)

    assert label_of("politicas") == PUBLICA


def test_una_fuente_solo_nombrada_y_privada_no_cuenta_en_una_busqueda_general(library):
    Library().set_public("bolitabot", True)
    Library().save("notas", "notas", "C:/n", 1, named_only=True)

    assert label_of("politicas") == PUBLICA


def test_sin_fuentes_la_busqueda_es_local(monkeypatch):
    monkeypatch.setattr("tools.rag_tool.search_collections", lambda *a, **k: [hit(DOC, "asia")])

    assert label_of("politicas") == RAG


def test_una_pregunta_solo_sobre_publicas_sale_a_gemini(library):
    brain = brain_on_gemini()

    brain.process("/buscar politicas en ros2")

    assert DOC in gemini_text(brain)
    assert brain.provider_router.providers["ollama"].received == []


def test_la_bitacora_registra_el_envio(library):
    brain_on_gemini().process("/buscar politicas en ros2")

    [entry, *_] = audit()
    assert entry["proveedor"] == "gemini" and entry["autorizacion"] == "exportable"
    assert entry["tipos"] == [PUBLICA, USUARIO] and entry["respuesta"] == "ok"
    assert DOC not in json.dumps(entry)


def test_una_pregunta_sobre_una_privada_no_sale(library):
    brain = brain_on_gemini()

    brain.process("/buscar politicas en bolitabot")

    assert gemini_text(brain) == "" and audit() == []
    assert PRIVATE in str(brain.provider_router.providers["ollama"].received)


def test_una_pregunta_que_mezcla_cuenta_como_local(library):
    brain = brain_on_gemini()

    brain.process("/buscar politicas")

    assert gemini_text(brain) == "" and audit() == []
    assert brain.provider_router.providers["ollama"].received


def test_una_mezcla_con_solo_fragmentos_publicos_tambien_es_local(library, monkeypatch):
    monkeypatch.setattr("tools.rag_tool.search_collections", lambda *a, **k: [hit(DOC, "ros2")])
    brain = brain_on_gemini()

    brain.process("/buscar politicas")

    assert gemini_text(brain) == "" and audit() == []


def test_un_contenido_local_en_la_misma_peticion_no_sale(library, monkeypatch):
    brain = brain_on_gemini()
    search = brain.tool_registry.execute

    def with_attachment(action, **kwargs):
        record(Fragment(ADJUNTO, "contenido de un adjunto"))
        return search(action, **kwargs)

    monkeypatch.setattr(brain.tool_registry, "execute", with_attachment)

    brain.process("/buscar politicas en ros2")

    assert gemini_text(brain) == "" and audit() == []


def test_en_modo_local_no_sale_ni_lo_publico(library):
    brain = brain_on_gemini()
    SettingsManager.set_overrides({"default_provider": "gemini", "confidential_mode": LOCAL_MODE})

    brain.process("/buscar politicas en ros2")

    assert gemini_text(brain) == "" and audit() == []


def test_al_volver_a_privada_deja_de_salir(library):
    Library().set_public("ros2", False)
    brain = brain_on_gemini()

    brain.process("/buscar politicas en ros2")

    assert gemini_text(brain) == "" and audit() == []


def test_con_ollama_de_proveedor_no_se_registra_nada(library):
    brain = make_brain()
    brain.tool_registry = ToolRegistry(brain.provider_router)

    brain.process("/buscar politicas en ros2")

    assert gemini_text(brain) == "" and audit() == []
