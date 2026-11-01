"""Indexar y buscar con RAG: en carpetas temporales y con embeddings simulados."""
import pytest

from core.rag import embedder as embedder_module
from core.rag.embedder import OllamaEmbedder
from core.rag.indexer import ProjectIndexer
from core.rag.retriever import search_collections


class FakeResponse:
    def __init__(self, vectors):
        self.vectors = vectors

    def raise_for_status(self):
        pass

    def json(self):
        return {"embeddings": self.vectors, "embedding": self.vectors[0]}


class FakeRequests:
    """Sustituye a requests.post: el embedding de un texto es su número de letras y de "a"."""

    def __init__(self):
        self.batches = []

    def post(self, url, json, timeout):
        texts = json.get("input") or [json["prompt"]]
        self.batches.append(len(texts))
        return FakeResponse([[float(len(t)), float(t.count("a")), 1.0] for t in texts])


@pytest.fixture
def embeddings(monkeypatch):
    import requests

    fake = FakeRequests()
    monkeypatch.setattr(requests, "post", fake.post)
    return fake


def test_embeddings_por_lotes_en_orden(embeddings):
    vectors = OllamaEmbedder().embed_many(["a" * n for n in range(1, 21)])

    assert [v[0] for v in vectors] == [float(n) for n in range(1, 21)]
    assert embeddings.batches == [16, 4]


def test_lotes_con_ollama_externo_bloqueados(monkeypatch, embeddings):
    embedder = OllamaEmbedder()
    embedder.external = True

    with pytest.raises(embedder_module.ExternalEmbeddingBlocked):
        embedder.embed_many(["contenido"])

    assert embeddings.batches == []


def test_indexa_y_busca_en_una_carpeta_propia(tmp_path, embeddings):
    project = tmp_path / "proyecto"
    project.mkdir()
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")

    count = ProjectIndexer(str(project), "prueba", persist_dir=tmp_path / "indice").index_project()

    hits = search_collections("x", ["prueba"], n_results=1, persist_dir=tmp_path / "indice")
    assert count == 1 and hits[0].document == "a.py\nx = 1"


def test_prefijos_de_nomic_solo_con_nomic(embeddings):
    embedder = OllamaEmbedder(model="nomic-embed-text")

    assert embedder.prefixed("search_query: ", "hola") == "search_query: hola"
    assert OllamaEmbedder(model="otro").prefixed("search_query: ", "hola") == "hola"
