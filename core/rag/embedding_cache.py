"""Embeddings de textos ya vistos, por hash: un artículo solo se embebe la primera vez.

Vale aunque cambie el .zim: lo que no cambió de texto conserva su hash. Se limita por
entradas: cada una ocupa unos 3 KB, así que MAX_ENTRIES son unos 200 MB. Sale lo
que lleva más tiempo sin usarse.
"""
import hashlib
import sqlite3
import time
from array import array
from contextlib import closing

from core import paths

MAX_ENTRIES = 60000
WAIT_S = 10


def key_of(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\0{text}".encode("utf-8")).hexdigest()


class EmbeddingCache:
    def __init__(self, path=None, limit=MAX_ENTRIES):
        self.path = path or paths.WIKIPEDIA_CACHE_FILE
        self.limit = limit

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=WAIT_S)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector BLOB NOT NULL, used REAL NOT NULL)"
        )
        return connection

    def embed(self, texts: list, embedder) -> list:
        """Los embeddings de texts, en el mismo orden. Solo llama a embedder con lo que falta."""
        keys = [key_of(embedder.model, text) for text in texts]

        with closing(self.connect()) as connection, connection:
            marks = ",".join("?" * len(keys))
            known = dict(connection.execute(f"SELECT key, vector FROM embeddings WHERE key IN ({marks})", keys))
            missing = {key: text for key, text in zip(keys, texts) if key not in known}
            vectors = embedder.embed_documents(list(missing.values())) if missing else []
            found = {key: array("f", vector).tobytes() for key, vector in zip(missing, vectors)}
            known.update(found)
            now = time.time()
            connection.executemany(
                "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?)", [(key, known[key], now) for key in set(keys)]
            )
            connection.execute(
                "DELETE FROM embeddings WHERE key NOT IN (SELECT key FROM embeddings ORDER BY used DESC LIMIT ?)",
                (self.limit,),
            )

        return [array("f", known[key]).tolist() for key in keys]

    def count(self) -> int:
        with closing(self.connect()) as connection:
            return connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
