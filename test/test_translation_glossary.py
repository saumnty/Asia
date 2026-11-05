"""Glosario de traducción técnica (config/glosario_traduccion.json): "nombre del equipo" es hostname."""
import json

from core import prompts
from core.rag.translation_glossary import GLOSSARY_FILE, load_glossary, terms_in


def test_el_termino_mas_largo_gana_sin_tildes_ni_mayusculas():
    glossary = {"equipo": ["computer"], "nombre del equipo": ["hostname"], "contraseña": ["password"]}

    assert terms_in("¿Cómo cambio el NOMBRE DEL EQUIPO y la contrasena?", glossary) == [
        ("nombre del equipo", ["hostname"]), ("contraseña", ["password"])]
    assert terms_in("mi equipo de fútbol", glossary) == [("equipo", ["computer"])]
    assert terms_in("los equipos", glossary) == []


def test_las_notas_no_son_terminos(tmp_path):
    path = tmp_path / "glosario.json"
    path.write_text(json.dumps({"_nota": "x", "carpeta": ["folder"], "vacio": []}), encoding="utf-8")

    assert load_glossary(path) == {"carpeta": ["folder"]}
    assert load_glossary(tmp_path / "no_existe.json") == {}


def test_el_glosario_del_repositorio():
    glossary = load_glossary(GLOSSARY_FILE)

    assert glossary["nombre del equipo"][0] == "hostname" and glossary["carpeta"][0] == "folder"
    assert glossary["archivo"] == ["file"]


def test_la_traduccion_lleva_los_terminos_y_sin_ellos_queda_igual():
    with_terms = prompts.translate_question("cómo cambio el nombre del equipo", [("nombre del equipo", ["hostname", "computer name"])])

    assert "- nombre del equipo: hostname / computer name" in with_terms
    assert "computing terms" not in prompts.translate_question("cómo cambio el nombre del equipo")


def test_buscar_traduce_con_el_glosario(monkeypatch):
    from types import SimpleNamespace

    from core.actions.explore import ExploreActions
    from core.rag import library

    asked = []
    explorer = SimpleNamespace(
        settings={"rag": {"translate_question": True}},
        provider_router=SimpleNamespace(ask=lambda prompt, max_tokens=None: asked.append(prompt) or "How do I change the hostname?"),
    )
    source = SimpleNamespace(name="askubuntu", language="en", kind="preguntas")
    monkeypatch.setattr("core.actions.explore.Library", lambda: SimpleNamespace(all=lambda: [source]))
    monkeypatch.setattr("core.actions.explore.needs_translation", lambda question, sources: True)
    monkeypatch.setattr("core.actions.explore.named_in_question", lambda question, sources: source)
    monkeypatch.setattr("core.actions.explore.without_source", lambda question, named: "cómo cambio el nombre del equipo")

    translated = ExploreActions.translated_question(explorer, "cómo cambio el nombre del equipo en askubuntu")

    assert translated == "How do I change the hostname?" and "- nombre del equipo: hostname" in asked[0]
