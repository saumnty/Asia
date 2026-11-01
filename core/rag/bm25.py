"""BM25: búsqueda por palabras, para nombres exactos de funciones y variables.

Sin paquetes. Las palabras se parten como en el código: "drop_client" y
"dropClient" dan "drop", "client" y el nombre entero, así que sirven tanto el
nombre exacto como una parte. Sin acentos y sin palabras vacías del español.
"""
import math
import re
import unicodedata
from collections import Counter

K1 = 1.5
B = 0.75

WORD = re.compile(r"\w+")
CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
STOPWORDS = {
    "a", "al", "algo", "como", "con", "cual", "de", "del", "donde", "el", "en", "es", "esta", "este", "la", "las",
    "lo", "los", "me", "mi", "para", "pero", "por", "que", "se", "si", "sin", "su", "un", "una", "uno", "y", "o",
    "the", "of", "to", "and", "in", "is",
}


def without_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def tokenize(text: str) -> list:
    tokens = []

    # Sin acentos antes de partir: CAMEL corta en cualquier letra que no sea a-z.
    for word in WORD.findall(without_accents(text)):
        parts = [part for piece in word.split("_") for part in CAMEL.findall(piece)]
        tokens += [token.lower() for token in dict.fromkeys([word, *parts])]

    return [token for token in tokens if len(token) > 1 and token not in STOPWORDS]


class BM25:
    def __init__(self, documents: list):
        self.counts = [Counter(tokenize(document)) for document in documents]
        self.lengths = [sum(counts.values()) for counts in self.counts]
        self.average = sum(self.lengths) / len(self.lengths) if self.lengths else 0
        self.frequency = Counter(token for counts in self.counts for token in counts)

    def idf(self, token: str) -> float:
        total, found = len(self.counts), self.frequency[token]
        return math.log(1 + (total - found + 0.5) / (found + 0.5))

    def score(self, tokens: list, index: int) -> float:
        counts, length = self.counts[index], self.lengths[index]
        total = 0.0

        for token in tokens:
            count = counts[token]

            if count:
                norm = K1 * (1 - B + B * length / self.average)
                total += self.idf(token) * count * (K1 + 1) / (count + norm)

        return total

    def coverage(self, query: str, document: str) -> float:
        """Qué parte de la pregunta está en document, de 0 a 1, pesando las palabras raras.

        No depende del tamaño de la colección, a diferencia de la puntuación de BM25.
        """
        tokens = set(tokenize(query))
        total = sum(self.idf(token) for token in tokens)

        if not total:
            return 0.0

        found = tokens & set(tokenize(document))
        return sum(self.idf(token) for token in found) / total

    def top(self, query: str, limit: int) -> list:
        """[(índice, puntuación)] de los documentos con alguna palabra de query, del mejor al peor."""
        tokens = list(set(tokenize(query)))
        scored = ((i, self.score(tokens, i)) for i in range(len(self.counts)))
        return sorted((pair for pair in scored if pair[1] > 0), key=lambda pair: -pair[1])[:limit]
