"""Fuentes en inglés: la pregunta también se busca traducida, con raíces del inglés."""
import pytest

from config.settings_manager import SettingsManager
from core import prompts
from core.actions.library import USAGE, parse_source
from core.prompts import NOT_FOUND
from core.rag.indexer import ProjectIndexer
from core.rag.library import Library, Source, clean_translation, needs_translation
from core.rag.retriever import search_collections
from core.rag.tokens import tokenize
from core.rag.word_index import ENGLISH, WordIndex, table_of
from test_confidencial import make_brain
from test_rag_answer import ANSWER, CONTEXT, QUOTED, Router
from test_rag_index import embeddings  # noqa: F401
from tools.rag_tool import RagTool

DOC = "Quality of service policies are configured per publisher"


def source(name, language="es", named_only=False):
    return Source(name, "documentacion", "C:/x", name, language=language, named_only=named_only)


def words_with(folder, *documents):
    words = WordIndex(folder)
    words.add("docs", [f"d{i}" for i in range(len(documents))], list(documents), [{} for _ in documents])
    return words


def ids(found):
    return [row[0] for row in found]


def test_cada_idioma_tiene_sus_raices():
    assert tokenize("policies", ENGLISH) == tokenize("policy", ENGLISH)
    assert tokenize("policies") != tokenize("policy")


def test_la_traduccion_encuentra_otra_forma_de_la_palabra_en_ingles(tmp_path):
    words = words_with(tmp_path, DOC, "Nodes talk over topics")

    assert ids(words.top("policy", ["docs"], 5, ENGLISH)) == ["d0"]


def test_las_raices_del_ingles_no_entran_en_la_busqueda_en_espanol(tmp_path):
    words = words_with(tmp_path, "the running robots")

    assert ids(words.top("run", ["docs"], 5)) == []
    assert ids(words.top("run", ["docs"], 5, ENGLISH)) == ["d0"]


def test_la_cobertura_en_ingles_usa_sus_raices(tmp_path):
    words = words_with(tmp_path, DOC, "Nodes talk over topics", "Other things")

    assert words.coverage("policy", [DOC], ["docs"], ENGLISH) == [1.0]
    assert words.coverage("policy", [DOC], ["docs"]) == [0.0]


def test_una_tabla_vieja_se_cambia_por_una_vacia(tmp_path):
    # Vacía, sync_words no coincide con Chroma y la rehace.
    words = WordIndex(tmp_path)

    with words.connection() as connection:
        connection.execute(
            f"CREATE VIRTUAL TABLE {table_of('docs')} USING fts5(chunk_id UNINDEXED, document UNINDEXED, "
            "metadata UNINDEXED, tokens)"
        )
        connection.execute(f"INSERT INTO {table_of('docs')} VALUES ('x', 'y', '{{}}', 'z')")

    assert words.count("docs") == 0


@pytest.mark.parametrize(
    "spec, language",
    [("ros2 idioma=en", "en"), ("ros2 C:\\docs documentacion idioma=es", "es")],
)
def test_indexar_acepta_el_idioma(spec, language):
    assert parse_source(spec)[5] == {"language": language}


def test_un_idioma_desconocido_no_se_acepta():
    assert parse_source("ros2 idioma=fr") is None
    assert make_brain().process("/indexar ros2 idioma=fr") == USAGE


def test_el_idioma_de_una_fuente_vieja_es_espanol():
    library = Library()
    library.path.parent.mkdir(parents=True)
    library.path.write_text(
        '[{"name": "a", "kind": "proyecto", "path": "C:/a", "collection": "aaa", "fragments": 1, "indexed": "x"}]',
        encoding="utf-8",
    )

    assert library.get("a").language == "es"


def test_fuentes_muestra_el_idioma():
    Library().save("ros2", "documentacion", "C:/docs", 10, language="en")

    assert "ros2 (documentacion, en en)" in make_brain().process("/fuentes")


@pytest.mark.parametrize(
    "question, expected",
    [
        ("qué es QoS en ros2", True),
        ("qué es QoS en asia", False),
        ("qué es QoS", True),
        ("drop_client", False),
        ("qué es QoS en pruebas", False),
    ],
)
def test_cuando_hace_falta_traducir(question, expected):
    sources = [source("ros2", "en"), source("asia"), source("pruebas", named_only=True)]

    assert needs_translation(question, sources) is expected


def test_sin_fuentes_en_ingles_no_se_traduce():
    assert not needs_translation("qué es QoS", [source("asia")])


def test_una_fuente_solo_nombrada_en_ingles_no_traduce_una_busqueda_general():
    assert not needs_translation("qué es QoS", [source("asia"), source("ros2", "en", named_only=True)])


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("What is QoS?", "What is QoS?"),
        ('"What is QoS?"\n\nNote: this is the translation.', "What is QoS?"),
        ("**What is QoS?**", "What is QoS?"),
        ("", ""),
        ("x" * 301, ""),
    ],
)
def test_la_traduccion_se_limpia(answer, expected):
    assert clean_translation(answer) == expected


def test_el_prompt_de_traduccion_conserva_los_nombres():
    prompt = prompts.translate_question("qué hace parameter_bridge")

    assert "parameter_bridge" in prompt and "Keep code names" in prompt


def test_la_extraccion_recibe_las_dos_versiones():
    prompt = prompts.extract_quotes("qué es QoS", CONTEXT, "What is QoS?")

    assert "qué es QoS" in prompt and "What is QoS?" in prompt


def test_sin_traduccion_la_extraccion_no_cambia():
    assert "en inglés" not in prompts.extract_quotes("qué es QoS", CONTEXT)


class Registry:
    def __init__(self):
        self.calls = []

    def execute(self, action, **kwargs):
        self.calls.append(kwargs)
        return CONTEXT


def brain_with(*answers):
    brain = make_brain()
    brain.tool_registry = Registry()
    brain.provider_router = Router(*answers)
    return brain


def test_por_defecto_no_traduce():
    Library().save("ros2", "documentacion", "C:/docs", 10, language="en")
    brain = brain_with(QUOTED, ANSWER)

    brain.process("/buscar qué ganancia tiene en ros2")

    assert brain.tool_registry.calls[0]["translated"] == ""
    assert len(brain.provider_router.prompts) == 2


def test_buscar_traduce_con_la_opcion_para_una_fuente_en_ingles():
    SettingsManager.set_overrides({"rag": {"translate_question": True}})
    Library().save("ros2", "documentacion", "C:/docs", 10, language="en")
    brain = brain_with("What is the gain?", QUOTED, ANSWER)

    brain.process("/buscar qué ganancia tiene en ros2")

    assert brain.tool_registry.calls[0]["translated"] == "What is the gain?"
    assert "qué ganancia tiene\n" in brain.provider_router.prompts[0]
    assert "What is the gain?" in brain.provider_router.prompts[1]


def test_buscar_no_traduce_para_una_fuente_en_espanol():
    Library().save("asia", "proyecto", "C:/Asia", 10)
    brain = brain_with(QUOTED, ANSWER)

    brain.process("/buscar qué ganancia tiene en asia")

    assert brain.tool_registry.calls[0]["translated"] == ""
    assert len(brain.provider_router.prompts) == 2


def test_la_traduccion_solo_se_busca_en_las_colecciones_en_ingles(tmp_path, embeddings):  # noqa: F811
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "qos.md").write_text(f"# QoS\n\n{DOC}\n", encoding="utf-8")
    (docs / "otro.md").write_text("# Otro\n\nNodes talk over topics\n", encoding="utf-8")
    ProjectIndexer(str(docs), "docs", persist_dir=tmp_path / "i").index_project()

    hits = search_collections("zzz", ["docs"], persist_dir=tmp_path / "i", translated="policy", english=["docs"])
    ignored = search_collections("zzz", ["docs"], persist_dir=tmp_path / "i", translated="policy", english=[])

    assert max(hit.coverage for hit in hits) == 1.0
    assert max(hit.coverage for hit in ignored) == 0.0


def test_la_herramienta_pasa_la_traduccion_a_las_fuentes_en_ingles(monkeypatch):
    Library().save("ros2", "documentacion", "C:/docs", 10, language="en")
    Library().save("asia", "proyecto", "C:/Asia", 10)
    seen = {}

    def search(query, collections, **kwargs):
        seen.update(kwargs, collections=collections)
        return []

    monkeypatch.setattr("tools.rag_tool.search_collections", search)

    assert RagTool().search_project("qué es QoS", "asia", translated="What is QoS?") == NOT_FOUND
    assert seen["translated"] == "What is QoS?"
    assert seen["english"] == ["ros2"] and set(seen["collections"]) == {"ros2", "asia"}
