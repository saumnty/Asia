"""Hechos concretos posteriores a lo que sabe el modelo: no se contestan de memoria y se ofrece Wikipedia."""
import pytest

from core.rag.library import Library
from core.recent_facts import asks_recent_fact, is_affirmative, offer_text
from test_confidencial import make_brain


@pytest.mark.parametrize(
    "text",
    ["¿quién ganó el mundial de 2026?", "¿Quién es el presidente actual de México?", "¿cuál fue el último campeón de la Champions?",
     "¿qué pasó en las elecciones de 2025?", "¿quién ganó el Nobel de física este año?", "y quién ganó la final de 2027?"],
)
def test_hecho_reciente(text):
    assert asks_recent_fact(text, 2024)


@pytest.mark.parametrize(
    "text",
    ["¿quién ganó el mundial de 1986?", "¿qué es un grafo bipartito?", "¿cuántos días tiene 2028?",
     "explica el archivo informe_2026.py", "¿quién fue Einstein?", "hola", "¿cuál es la capital de Japón?"],
)
def test_no_es_hecho_reciente(text):
    assert not asks_recent_fact(text, 2024)


def test_el_tope_viene_del_argumento():
    assert asks_recent_fact("¿quién ganó el mundial de 2022?", 2021)
    assert not asks_recent_fact("¿quién ganó el mundial de 2022?", 2024)


@pytest.mark.parametrize("text, yes", [("sí", True), ("Sí, búscalo", True), ("sí, pero otra cosa", False), ("si", True), ("dale", True), ("no", False)])
def test_afirmativas(text, yes):
    assert is_affirmative(text) is yes


class Search:
    def __init__(self):
        self.questions = []

    def __call__(self, text, params):
        self.questions.append(params["question"])
        return "resultado"


def wikipedia(tmp_path):
    zim = tmp_path / "wikipedia_es_top_nopic_2026-10.zim"
    zim.write_bytes(b"")
    Library().save("wikipedia", "enciclopedia", str(zim), 10, named_only=True, publica=True)


class NoModel:
    def detect(self, text, model=None):
        raise AssertionError("no debía llamar al modelo")


def test_ofrece_wikipedia_y_con_si_la_busca(tmp_path, monkeypatch):
    wikipedia(tmp_path)
    brain = make_brain()
    brain.intent_engine = NoModel()
    search = Search()
    monkeypatch.setattr(brain, "handle_search_project_rag", search)

    offer = brain.process("¿quién ganó el mundial de 2026?")

    assert offer.startswith("No lo sé de memoria")
    assert "¿Lo busco en Wikipedia (copia offline de 2026-10)?" in offer
    assert brain.process("sí") == "resultado"
    assert search.questions == ["quién ganó el mundial de 2026 en wikipedia"]


def test_la_oferta_vale_solo_para_el_mensaje_siguiente(tmp_path, monkeypatch):
    wikipedia(tmp_path)
    brain = make_brain()
    search = Search()
    monkeypatch.setattr(brain, "handle_search_project_rag", search)

    brain.process("¿quién ganó el mundial de 2026?")
    brain.process("cuéntame un chiste")
    brain.process("sí")

    assert search.questions == []


def test_sin_wikipedia_solo_dice_que_no_lo_sabe():
    brain = make_brain()

    answer = brain.process("¿quién ganó el mundial de 2026?")

    assert answer == offer_text(None) and "Wikipedia para buscarlo" in answer
    assert getattr(brain, "offered_search", None) is None
