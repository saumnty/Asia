from config.settings_manager import SettingsManager
from core.confidential import is_open_mode, ollama_is_external


# Por lotes: en CPU, 0,67 s por fragmento frente a 2,8 s de uno en uno.
BATCH_SIZE = 16

# nomic-embed-text espera estos prefijos: con ellos, 9 de 18 preguntas sacan el
# archivo correcto en primer lugar, contra 7 sin ellos.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


class ExternalEmbeddingBlocked(RuntimeError):
    pass


class OllamaEmbedder:
    def __init__(self, model=None, host=None, timeout=None):
        settings = SettingsManager()

        self.model = model or settings.get("embedding_model")
        host = host or settings.get("ollama_host")
        self.url = f"{host.rstrip('/')}/api/embeddings"
        self.batch_url = f"{host.rstrip('/')}/api/embed"
        self.timeout = timeout or settings.get("embedding_timeout")
        # Indexar manda el contenido de los archivos: con Ollama en otra
        # máquina (no en trusted_local_hosts) no se hace (fase G).
        self.external = ollama_is_external(_HostSettings(host, settings.get("trusted_local_hosts")))

    def check_allowed(self):
        # En modo abierto el contenido puede salir (fase G).
        if self.external and not is_open_mode(SettingsManager()):
            raise ExternalEmbeddingBlocked(
                "ollama_host apunta fuera de esta máquina: no envío contenido de archivos "
                "para indexar ni buscar con RAG. Agrega el host a trusted_local_hosts en "
                "config/settings.json si es tuyo."
            )

    def prefixed(self, prefix: str, text: str) -> str:
        return f"{prefix}{text}" if self.model.startswith("nomic") else text

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_many([self.prefixed(DOCUMENT_PREFIX, text) for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self.embed(self.prefixed(QUERY_PREFIX, text))

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Los embeddings de texts, en el mismo orden."""
        self.check_allowed()

        import requests

        embeddings = []

        for start in range(0, len(texts), BATCH_SIZE):
            response = requests.post(
                self.batch_url,
                json={"model": self.model, "input": texts[start:start + BATCH_SIZE]},
                timeout=self.timeout
            )
            response.raise_for_status()
            embeddings += response.json()["embeddings"]

        return embeddings

    def embed(self, text: str) -> list[float]:
        self.check_allowed()

        # Aquí y no arriba: requests tarda ~1 s en cargar y solo hace falta con RAG.
        import requests

        response = requests.post(
            self.url,
            json={
                "model": self.model,
                "prompt": text
            },
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()["embedding"]


class _HostSettings:
    def __init__(self, host, trusted):
        self.values = {"ollama_host": host, "trusted_local_hosts": trusted or []}

    def get(self, key, default=None):
        return self.values.get(key, default)
