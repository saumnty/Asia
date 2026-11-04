"""Palabras clave para buscar en un .zim (títulos y texto completo) y la consulta conjunta "en preguntas"."""
import pytest
from libzim.writer import Creator

from config.settings_manager import SettingsManager
from core import prompts
from core.rag.keywords import keywords_prompt, parse_keywords
from core.rag.library import Library, Source, questions_group, without_group
from core.rag.wikipedia import found_articles
from test_rag_questions import QUESTION_HTML, Page
from test_rag_wikipedia import Embedder, archive_of, zim  # noqa: F401
from test_confidencial import make_brain
from tools.rag_tool import RagTool


def test_las_busquedas_de_la_respuesta():
    answer = "1. Monte Everest\n- montaña más alta\n«Everest»\n\nmonte everest\n" + "x" * 80 + "\nHimalaya\nK2"

    assert parse_keywords(answer) == ["Monte Everest", "montaña más alta", "Everest", "Himalaya"]
    assert parse_keywords("") == []


def test_el_prompt_pide_el_idioma_del_sitio():
    assert "en inglés" in keywords_prompt("cómo uso un pid", "en", "Stack Exchange")
    assert "en español" in keywords_prompt("cuál es la capital", "es", "Wikipedia")


def test_por_titulo_encuentra_lo_que_el_texto_completo_no(zim):  # noqa: F811
    archive = archive_of(zim)

    assert found_articles(archive, "ciudad sede del parlamento australiano") == []
    found = found_articles(archive, "ciudad sede del parlamento australiano", keywords=["Camberra"])

    assert [path for path, _, _ in found] == ["Camberra"]


def test_la_pregunta_original_sigue_de_respaldo(zim):  # noqa: F811
    found = found_articles(archive_of(zim), "fotosíntesis", keywords=["palabra que no está"])

    assert [path for path, _, _ in found] == ["Fotosíntesis"]


class Asks:
    def __init__(self):
        self.calls = []

    def ask(self, prompt, **options):
        self.calls.append((prompt, options))
        return "kalman filter\nextended kalman"


def keywords_brain(enabled, sources):
    SettingsManager.set_overrides({"rag": {"min_coverage": 0.3, "max_distance": 392.0, "zim_keywords": enabled}})
    brain = make_brain()
    brain.settings = SettingsManager()
    brain.provider_router = Asks()

    for source in sources:
        Library().save(source.name, source.kind, source.path, 1, named_only=True, language=source.language, publica=True)

    return brain


ROBOTICS = Source("robotics", "preguntas", "C:/zim/robotics.zim", "robotics", language="en")
SPANISH = Source("stackoverflow_es", "preguntas", "C:/zim/so_es.zim", "stackoverflow_es", language="es")


def test_apagado_no_llama_al_modelo():
    brain = keywords_brain(False, [ROBOTICS])

    assert brain.zim_search_keywords("vale la pena un EKF en robotics") == {}
    assert brain.provider_router.calls == []


def test_con_qwen3_del_dominio_general_y_una_vez_por_idioma():
    brain = keywords_brain(True, [ROBOTICS, SPANISH])

    found = brain.zim_search_keywords("vale la pena un filtro de Kalman en preguntas")

    assert found == {"en": ["kalman filter", "extended kalman"], "es": ["kalman filter", "extended kalman"]}
    assert [options["domain"] for _, options in brain.provider_router.calls] == ["general", "general"]
    assert all("en preguntas" not in prompt for prompt, _ in brain.provider_router.calls)


WIKIPEDIA = Source("wikipedia", "enciclopedia", "C:/zim/wiki.zim", "wikipedia", language="es")


def test_por_defecto_solo_la_enciclopedia():
    brain = keywords_brain(["enciclopedia"], [ROBOTICS, SPANISH, WIKIPEDIA])

    assert brain.zim_search_keywords("vale la pena un EKF en preguntas") == {}
    assert brain.zim_search_keywords("qué moneda se usa en Japón en wikipedia") == {"es": ["kalman filter", "extended kalman"]}
    assert len(brain.provider_router.calls) == 1


def test_los_valores_por_defecto():
    from config.settings_manager import DEFAULTS_FILE, read_json

    assert read_json(DEFAULTS_FILE)["rag"]["zim_keywords"] == ["enciclopedia"]


def test_una_fuente_que_no_es_zim_no_pide_palabras():
    brain = keywords_brain(True, [Source("bolitabot", "proyecto", "C:/b", "bolitabot")])

    assert brain.zim_search_keywords("cómo se calcula el punto en bolitabot") == {}


# --- "en preguntas": todos los sitios a la vez ------------------------------------

def test_el_grupo():
    sources = [ROBOTICS, SPANISH, Source("asia", "proyecto", "C:/Asia", "asia")]

    assert questions_group("qué es un EKF en preguntas", sources) == [ROBOTICS, SPANISH]
    assert questions_group("qué es un EKF en preguntas y respuestas", sources) == [ROBOTICS, SPANISH]
    assert questions_group("qué es un EKF en robotics", sources) == []
    assert questions_group("tengo dos preguntas", sources) == []
    assert without_group("qué es un EKF en preguntas") == "qué es un EKF"


def site(path, name, language):
    with Creator(str(path)).config_indexing(True, "eng" if language == "en" else "spa") as creator:
        creator.set_mainpath("questions/42/como-publicar")
        creator.add_metadata("Date", "2026-10-20")
        creator.add_metadata("Name", f"{name}_all")
        creator.add_metadata("Language", "eng" if language == "en" else "eng,spa")
        creator.add_item(Page("questions/42/como-publicar", "How to publish a capital topic", QUESTION_HTML))

    return path


@pytest.fixture
def two_sites(tmp_path, monkeypatch):
    for name, domain, language in (("robotics", "robotics.stackexchange.com", "en"), ("stackoverflow_es", "es.stackoverflow.com", "es")):
        path = site(tmp_path / f"{name}.zim", domain, language)
        assert "lista" in RagTool().index_project(name, str(path), "preguntas")

    monkeypatch.setattr("core.rag.wikipedia.OllamaEmbedder", Embedder)


def test_en_preguntas_busca_en_todos_los_sitios(two_sites):
    text = str(RagTool().search_project("capital topic en preguntas", "asia"))

    assert "robotics_42.qa" in text and "stackoverflow_es_42.qa" in text
    assert "robotics.stackexchange.com/a/51" in text and "es.stackoverflow.com/a/51" in text


def test_en_preguntas_con_el_archivo_ausente():
    Library().save("robotics", "preguntas", "C:/no/existe.zim", 1, named_only=True, language="en", publica=True)

    assert RagTool().search_project("algo en preguntas", "asia") == prompts.QA_MISSING
