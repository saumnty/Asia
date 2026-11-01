"""Las palabras de un texto, para buscar nombres exactos de funciones y variables.

Las palabras se parten como en el código: "drop_client" y "dropClient" dan
"drop", "client" y el nombre entero, así que sirven tanto el nombre exacto como
una parte. Sin acentos, sin palabras vacías del español y reducidas a su raíz
con snowballstemmer: "detectan" encuentra "detectar".
"""
import re
import unicodedata
from functools import lru_cache

WORD = re.compile(r"\w+")
CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
STOPWORDS = {
    "a", "al", "algo", "como", "con", "cual", "de", "del", "donde", "el", "en", "es", "esta", "este", "la", "las",
    "lo", "los", "me", "mi", "para", "pero", "por", "que", "se", "si", "sin", "su", "un", "una", "uno", "y", "o",
    "the", "of", "to", "and", "in", "is",
    # Interrogativos y cuantificadores: dicen cómo se pregunta, no de qué. Ausentes de una
    # fuente pequeña pesaban más que las palabras con contenido. "todo" no: es TODO en el código.
    "cuando", "cuanto", "cuanta", "cuantos", "cuantas", "cuales", "quien", "quienes", "cada",
    "todos", "todas", "toda", "mucho", "mucha", "muchos", "muchas", "poco", "poca", "pocos", "pocas",
    "varios", "varias", "algun", "alguna", "algunos", "algunas", "ningun", "ninguna",
}


def without_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


@lru_cache(maxsize=1)
def spanish_stemmer():
    # Aquí y no arriba: solo hace falta con RAG.
    import snowballstemmer

    return snowballstemmer.stemmer("spanish")


@lru_cache(maxsize=None)
def stem(token: str) -> str:
    return spanish_stemmer().stemWord(token)


def tokenize(text: str) -> list:
    tokens = []

    # Sin acentos antes de partir: CAMEL corta en cualquier letra que no sea a-z.
    for word in WORD.findall(without_accents(text)):
        parts = [part for piece in word.split("_") for part in CAMEL.findall(piece)]
        tokens += [token.lower() for token in dict.fromkeys([word, *parts])]

    return [stem(token) for token in tokens if len(token) > 1 and token not in STOPWORDS]
