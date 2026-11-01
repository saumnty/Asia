"""Búsqueda por palabras con SQLite FTS5 (fase H, capa 2).

Sustituye a reconstruir BM25 con todos los documentos en cada búsqueda. Vive junto a
Chroma, en palabras.sqlite3, con una tabla por colección: la frecuencia de una palabra
es la de sus fuentes, no la de toda la biblioteca. Guarda los tokens ya normalizados
(core/rag/tokens.py), con raíces del español y aparte con las del inglés, y el texto de
cada fragmento; se puede rehacer entero desde Chroma.
"""
import contextlib
import json
import math
import sqlite3
from pathlib import Path

from core.rag.tokens import tokenize

FILE_NAME = "palabras.sqlite3"
# "_" es parte del token: x_front es una palabra.
TOKENIZER = "unicode61 remove_diacritics 0 tokenchars ''_''"
SPANISH, ENGLISH = "spanish", "english"
SPANISH_COLUMN, ENGLISH_COLUMN = "tokens", "english_tokens"
COLUMNS = {SPANISH: SPANISH_COLUMN, ENGLISH: ENGLISH_COLUMN}
DELETE_BATCH = 500
WAIT_S = 30


def table_of(collection: str) -> str:
    return f'"w_{collection}"'


def vocabulary_of(collection: str) -> str:
    return f'"v_{collection}"'


def inverse_frequency(total: int, found: int) -> float:
    return math.log(1 + (total - found + 0.5) / (found + 0.5))


class WordIndex:
    def __init__(self, folder):
        self.path = Path(folder) / FILE_NAME

    @contextlib.contextmanager
    def connection(self):
        """Una conexión por operación, en una transacción: también para los hilos."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=WAIT_S)

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def ensure_table(self, connection, collection: str):
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table_of(collection)})")]

        # Una tabla de antes de la columna en inglés: sync_words la rehace desde Chroma.
        if columns and ENGLISH_COLUMN not in columns:
            connection.execute(f"DROP TABLE IF EXISTS {vocabulary_of(collection)}")
            connection.execute(f"DROP TABLE {table_of(collection)}")

        connection.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table_of(collection)} USING fts5("
            f"chunk_id UNINDEXED, document UNINDEXED, metadata UNINDEXED, {SPANISH_COLUMN}, {ENGLISH_COLUMN}, "
            f"tokenize = '{TOKENIZER}')"
        )
        connection.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {vocabulary_of(collection)} "
            f"USING fts5vocab({table_of(collection)}, 'col')"
        )

    def count(self, collection: str) -> int:
        with self.connection() as connection:
            self.ensure_table(connection, collection)
            return connection.execute(f"SELECT count(*) FROM {table_of(collection)}").fetchone()[0]

    def delete_rows(self, connection, collection: str, ids: list):
        for start in range(0, len(ids), DELETE_BATCH):
            batch = ids[start:start + DELETE_BATCH]
            marks = ",".join("?" for _ in batch)
            connection.execute(f"DELETE FROM {table_of(collection)} WHERE chunk_id IN ({marks})", batch)

    def add(self, collection: str, ids: list, documents: list, metadatas: list):
        """Añade o reemplaza fragmentos."""
        with self.connection() as connection:
            self.ensure_table(connection, collection)
            self.delete_rows(connection, collection, ids)
            connection.executemany(
                f"INSERT INTO {table_of(collection)} (chunk_id, document, metadata, {SPANISH_COLUMN}, {ENGLISH_COLUMN}) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        chunk_id, document, json.dumps(metadata or {}),
                        " ".join(tokenize(document)), " ".join(tokenize(document, ENGLISH)),
                    )
                    for chunk_id, document, metadata in zip(ids, documents, metadatas)
                ],
            )

    def delete(self, collection: str, ids: list):
        with self.connection() as connection:
            self.ensure_table(connection, collection)
            self.delete_rows(connection, collection, ids)

    def rebuild(self, collection: str, ids: list, documents: list, metadatas: list):
        """Rehace la tabla de una colección: lo que falte se saca de Chroma, sin embeddings."""
        with self.connection() as connection:
            self.ensure_table(connection, collection)
            connection.execute(f"DELETE FROM {table_of(collection)}")

        self.add(collection, ids, documents, metadatas)

    def top(self, query: str, collections: list, limit: int, language: str = SPANISH) -> list:
        """[(id, documento, metadatos, puntuación)] con alguna palabra de query, del mejor al peor."""
        tokens = list(dict.fromkeys(tokenize(query, language)))

        if not tokens:
            return []

        column = COLUMNS[language]
        match = f"{column} : (" + " OR ".join(f'"{token}"' for token in tokens) + ")"
        found = []

        with self.connection() as connection:
            for collection in collections:
                self.ensure_table(connection, collection)
                table = table_of(collection)
                found += connection.execute(
                    f"SELECT chunk_id, document, metadata, -bm25({table}) FROM {table} "
                    f"WHERE {table} MATCH ? ORDER BY rank LIMIT ?",
                    (match, limit),
                ).fetchall()

        ranked = sorted(found, key=lambda row: -row[3])[:limit]
        return [(chunk_id, document, json.loads(metadata), score) for chunk_id, document, metadata, score in ranked]

    def frequencies(self, tokens: list, collections: list, language: str = SPANISH) -> tuple:
        """(fragmentos en total, {token: fragmentos que lo tienen}) de esas colecciones."""
        total, found = 0, dict.fromkeys(tokens, 0)
        column = COLUMNS[language]

        with self.connection() as connection:
            for collection in collections:
                self.ensure_table(connection, collection)
                total += connection.execute(f"SELECT count(*) FROM {table_of(collection)}").fetchone()[0]

                for token in tokens:
                    row = connection.execute(
                        f"SELECT doc FROM {vocabulary_of(collection)} WHERE term = ? AND col = ?", (token, column)
                    ).fetchone()
                    found[token] += row[0] if row else 0

        return total, found

    def coverage(self, query: str, documents: list, collections: list, language: str = SPANISH) -> list:
        """Qué parte de la pregunta está en cada documento, de 0 a 1, pesando las palabras raras.

        No depende del tamaño de la colección, a diferencia de la puntuación de BM25.
        """
        tokens = list(set(tokenize(query, language)))
        total, found = self.frequencies(tokens, collections, language)
        weights = {token: inverse_frequency(total, found[token]) for token in tokens}
        whole = sum(weights.values())

        if not whole:
            return [0.0 for _ in documents]

        return [
            sum(weights[t] for t in set(tokenize(document, language)) if t in weights) / whole
            for document in documents
        ]
