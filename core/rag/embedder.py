import requests

from config.settings_manager import SettingsManager
from core.confidential import ollama_is_external


class ExternalEmbeddingBlocked(RuntimeError):
    pass


class OllamaEmbedder:
    def __init__(self, model=None, host=None, timeout=None):
        settings = SettingsManager()

        self.model = model or settings.get("embedding_model")
        host = host or settings.get("ollama_host")
        self.url = f"{host.rstrip('/')}/api/embeddings"
        self.timeout = timeout or settings.get("embedding_timeout")
        # Indexar manda el contenido de los archivos: con Ollama en otra
        # máquina (no en trusted_local_hosts) no se hace (fase G).
        self.external = ollama_is_external(_HostSettings(host, settings.get("trusted_local_hosts")))

    def embed(self, text: str) -> list[float]:
        if self.external:
            raise ExternalEmbeddingBlocked(
                "ollama_host apunta fuera de esta máquina: no envío contenido de archivos "
                "para indexar ni buscar con RAG. Agrega el host a trusted_local_hosts en "
                "config/settings.json si es tuyo."
            )

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
