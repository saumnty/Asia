"""La regla de la entidad: una cita de Wikipedia o Stack Exchange tiene que nombrar lo que se pregunta."""
from core import prompts
from core.rag.entities import about_entities, mentions, question_entities
from core.rag.quotes import Quote
from test_rag_answer import brain_with

WIKI_CONTEXT = """
--- [Puente_de_Hierro_Soria.wiki:20-22] Puente de Hierro (Soria) > Historia ---
Fuente: Wikipedia
Contenido:
Puente de Hierro (Soria) > Historia
El puente se construyó en el año 1929.
Une las dos orillas del Duero.
"""


def test_los_nombres_propios_de_la_pregunta():
    assert question_entities("en qué año se fundó Brezalmonte de Arriba") == ["Brezalmonte de Arriba"]
    assert question_entities("quién ganó el Premio Orzaluna de novela en 1987") == ["Premio Orzaluna"]
    assert question_entities("¿Quién pintó la Mona Lisa?") == ["Mona Lisa"]


def test_las_siglas_y_las_fuentes_no_son_nombres():
    assert question_entities("qué diferencia hay entre un MOSFET y un BJT") == []
    assert question_entities("qué moneda se usa en Japón en Wikipedia", skip=["Wikipedia"]) == ["Japón"]


def test_el_nombre_se_busca_sin_tildes_ni_mayusculas():
    assert mentions("Japón", "La moneda de JAPON es el yen")
    assert mentions("Australia", "Territorio_de_la_Capital_Australiana.wiki")
    assert not mentions("Brezalmonte de Arriba", "Barrio de Arriba (Riotuerto)")


def wiki_quote(text, label, path="Puente_de_Hierro_Soria.wiki"):
    return Quote(path, 21, label, text)


def test_una_cita_de_otro_articulo_no_vale():
    quote = wiki_quote("El puente se construyó en el año 1929.", "Puente de Hierro (Soria) > Historia")

    assert about_entities([quote], "en qué año se inauguró el puente de Valdecierzo") == ([], ["Valdecierzo"])


def test_vale_si_lo_nombra_la_linea_o_el_titulo():
    by_title = wiki_quote("Se inauguró en 1929.", "Puente de Valdecierzo > Historia")
    by_line = wiki_quote("El de Valdecierzo, en 1931.", "Puentes de Soria")
    question = "en qué año se inauguró el puente de Valdecierzo"

    assert about_entities([by_title, by_line], question) == ([by_title, by_line], [])


def test_las_citas_de_los_proyectos_no_se_miran():
    quote = Quote("control/pid.py", 41, "Pid.salida", "self.kp = 2.5")

    assert about_entities([quote], "qué ganancia tiene el Pid de Bolitabot") == ([quote], [])


def test_sin_citas_queda_como_estaba():
    assert about_entities([], "dónde nace el río Tumbarrayo") == ([], [])


def test_buscar_dice_que_no_encontro_el_nombre():
    brain = brain_with("[Puente_de_Hierro_Soria.wiki:20-22] El puente se construyó en el año 1929.",
                       "El puente de Valdecierzo se inauguró en 1929 [Puente_de_Hierro_Soria.wiki:21].",
                       context=WIKI_CONTEXT)

    answer = brain.process("/buscar en qué año se inauguró el puente de Valdecierzo")

    assert answer == f"{prompts.NO_INFO_ABOUT} Valdecierzo."
    assert len(brain.provider_router.prompts) == 1
