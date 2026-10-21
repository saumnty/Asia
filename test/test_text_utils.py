from core.utils.text_utils import clean_text


def test_none_devuelve_vacio():
    assert clean_text(None) == ""


def test_colapsa_espacios_y_saltos():
    assert clean_text("  hola \n\n  mundo  ") == "hola mundo"


def test_quita_puntuacion_solo_en_los_extremos():
    assert clean_text("¡hola, mundo!") == "hola, mundo"
