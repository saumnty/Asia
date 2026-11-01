"""Glosario por fuente: amplía la pregunta; lo mantiene el usuario."""
import json

import pytest

from core import paths, prompts
from core.commands import COMMANDS, options_text
from core.rag.glossary import expand, glossary_path, read_glossary
from core.rag.library import Library
from test_confidencial import make_brain
from test_rag_answer import CONTEXT, brain_with


@pytest.fixture
def sources():
    library = Library()
    library.save("Bolitabot", "proyecto", "C:/robots", 10)
    library.save("Notas", "notas", "C:/notas", 3)
    return library.all()


def write_glossary(name, content):
    path = glossary_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


def test_el_archivo_va_en_la_biblioteca():
    assert glossary_path("Bolitabot") == paths.GLOSSARY_DIR / "glosario_Bolitabot.json"


def test_el_nombre_de_la_fuente_no_sale_de_la_carpeta():
    assert glossary_path("../../secreto").parent == paths.GLOSSARY_DIR


def test_sin_archivo_el_glosario_esta_vacio():
    assert read_glossary("Bolitabot") == {}


def test_un_equivalente_suelto_o_una_lista():
    write_glossary("Bolitabot", {"a": "x", "b": ["y", "z"]})

    assert read_glossary("Bolitabot") == {"a": ["x"], "b": ["y", "z"]}


def test_amplia_la_pregunta(sources):
    write_glossary("Bolitabot", {"punto desplazado": ["x_front", "y_front"]})

    assert expand("cómo se calcula el punto desplazado", sources) == (
        "cómo se calcula el punto desplazado (x_front, y_front)"
    )


def test_sin_terminos_la_pregunta_no_cambia(sources):
    write_glossary("Bolitabot", {"punto desplazado": ["x_front"]})

    assert expand("cómo se calcula el error", sources) == "cómo se calcula el error"


def test_sin_acentos_ni_mayusculas(sources):
    write_glossary("Bolitabot", {"Trébol": ["T_v"]})

    assert expand("cuánto dura el TREBOL", sources) == "cuánto dura el TREBOL (T_v)"


def test_solo_palabras_enteras(sources):
    write_glossary("Bolitabot", {"pid": ["kp"]})

    assert expand("qué es rapido", sources) == "qué es rapido"


def test_no_repite_lo_que_ya_dice_la_pregunta(sources):
    write_glossary("Bolitabot", {"punto desplazado": ["x_front", "y_front"]})

    assert expand("punto desplazado y x_front", sources) == "punto desplazado y x_front (y_front)"


def test_si_nombra_una_fuente_solo_usa_su_glosario(sources):
    write_glossary("Bolitabot", {"tramo": ["T_v"]})
    write_glossary("Notas", {"tramo": ["apunte"]})

    assert expand("qué es un tramo en Notas", sources) == "qué es un tramo en Notas (apunte)"


def test_sin_fuente_nombrada_usa_todos(sources):
    write_glossary("Bolitabot", {"tramo": ["T_v"]})
    write_glossary("Notas", {"tramo": ["apunte"]})

    assert expand("qué es un tramo", sources) == "qué es un tramo (T_v, apunte)"


@pytest.mark.parametrize("broken", ["{no es json", "[1, 2]", '{"a": 3}'])
def test_un_glosario_mal_escrito_no_rompe_la_busqueda(sources, broken):
    write_glossary("Bolitabot", broken)

    assert expand("qué es un tramo", sources) == "qué es un tramo"


def test_asia_nunca_escribe_el_glosario(sources):
    expand("qué es un tramo", sources)
    brain = brain_with()

    brain.process("/buscar qué ganancia tiene")
    brain.process("/glosario Bolitabot")

    assert not glossary_path("Bolitabot").exists()


def test_buscar_amplia_la_pregunta_para_buscar_y_para_el_modelo(sources):
    write_glossary("Bolitabot", {"ganancia": ["self.kp"]})
    brain = brain_with()

    brain.process("/buscar qué ganancia tiene")

    assert brain.tool_registry.calls[0][1]["question"] == "qué ganancia tiene (self.kp)"
    assert "qué ganancia tiene (self.kp)" in brain.provider_router.prompts[0]
    assert "qué ganancia tiene (self.kp)" in brain.provider_router.prompts[1]


def test_glosario_muestra_las_equivalencias(sources):
    path = write_glossary("Bolitabot", {"punto desplazado": ["x_front", "y_front"]})

    shown = make_brain().process("/glosario bolitabot")

    assert shown == f"Glosario de Bolitabot ({path}):\n- punto desplazado = x_front, y_front"


def test_glosario_sin_archivo_explica_como_crearlo(sources):
    shown = make_brain().process("/glosario Bolitabot")

    assert "no tiene glosario" in shown and str(glossary_path("Bolitabot")) in shown and "x_front" in shown


def test_glosario_de_una_fuente_desconocida(sources):
    assert "No conozco la fuente 'Otra'" in make_brain().process("/glosario Otra")


def test_glosario_mal_escrito_lo_dice(sources):
    write_glossary("Bolitabot", "{no es json")

    assert "No puedo leer" in make_brain().process("/glosario Bolitabot")


def test_en_la_tabla_de_opciones():
    assert any(c.slash == "/glosario <fuente>" and c.group == "biblioteca" for c in COMMANDS)
    assert "/glosario <fuente>" in options_text()


def test_el_contexto_de_prueba_sigue_valiendo():
    assert prompts.extract_quotes("x", CONTEXT)
