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

    assert 20 <= len(messages) <= 30
    assert "¿cuál es tu color favorito?" in messages and "¿cuál es mi color favorito?" in messages


def test_grafo_bipartito_con_grupos_o_conjuntos():
    [expected] = [case[2] for case in CASES if case[0] == "qué es un grafo bipartito"]

    assert correct("los vértices se dividen en dos grupos", expected)
    assert correct("dos conjuntos disjuntos", expected)


def test_a_fondo_es_largo_y_sin_negarse():
    assert correct("Un nodo es...", "long", tokens=900)
    assert not correct("Un nodo es...", "long", tokens=200)
    assert not correct("No puedo explicarlo sin inventar.", "long", tokens=900)


def test_casos_de_la_prueba_manual_de_b():
    messages = [case[0] for case in CASES]

    for text in ("¿quién ganó el mundial de 2026?", "¿qué hicimos en la sesión anterior?", "¿de qué tema empezamos a hablar?",
                 "explícamelo a fondo", "¿y eso para qué sirve?"):
        assert text in messages
    assert messages[messages.index("¿quién ganó el mundial de 2026?") + 1] == "sí"
    assert messages[messages.index("¿y eso para qué sirve?") - 1].startswith("/buscar")


def test_empezamos_no_vale_con_el_ultimo_tema():
    [expected] = [case[2] for case in CASES if case[0] == "¿de qué tema empezamos a hablar?"]

    assert correct("Empezamos a hablar de ROS 2.", expected)
    assert not correct("Empezamos con los tópicos, la base para entender los nodos en ROS 2.", expected)
