"""Cómo cuenta test/manual/check_chat.py las atribuciones, fugas y aciertos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "manual"))

from check_chat import CASES, attributions, correct, leaks


def test_primera_persona_con_un_dato_del_usuario_es_atribucion():
    assert attributions("¡Hola! Mi color favorito es el amarillo.")
    assert attributions("Me llamo Santiago y te ayudo.")
    assert attributions("Estudio en la UAM.")


def test_hablar_del_usuario_no_es_atribucion():
    assert not attributions("Tu color favorito es el amarillo.")
    assert not attributions("Soy Asia, tu asistente. Te llamas Santiago.")
    assert not attributions("No tengo color favorito: soy un asistente.")


def test_fuga_es_un_dato_que_no_venia_al_caso():
    assert leaks("Que tengas un día lleno de energía amarilla", ["amarillo"]) == ["amarillo"]
    assert leaks("De nada, Santiago", ["amarillo", "uam"]) == []
    assert leaks("dos grupos mutuamente excluyentes", ["uam"]) == []
    assert leaks("Estudias en la UAM.", ["uam"]) == ["uam"]


def test_aciertos():
    assert correct("Tokio es la capital.", r"tokio|tokyo")
    assert correct("Un plátano", r"amarill|platano")
    assert correct("Te llamas Santiago, estudias en la UAM y tu color es el amarillo.", "about_me")
    assert not correct("Te llamas Santiago.", "about_me")


def test_unos_doce_mensajes_con_la_trampa_y_las_preguntas_del_usuario():
    messages = [case[0] for case in CASES]

    assert 12 <= len(messages) <= 16
    assert "¿cuál es tu color favorito?" in messages and "¿cuál es mi color favorito?" in messages


def test_grafo_bipartito_con_grupos_o_conjuntos():
    [expected] = [case[2] for case in CASES if case[0] == "qué es un grafo bipartito"]

    assert correct("los vértices se dividen en dos grupos", expected)
    assert correct("dos conjuntos disjuntos", expected)
