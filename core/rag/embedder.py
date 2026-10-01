import requests

from config.settings_manager import SettingsManager


class OllamaEmbedder:
    def __init__(self, model=None, host=None, timeout=None):
        settings = SettingsManager()

        self.model = model or settings.get("embedding_model")
        host = host or settings.get("ollama_host")
        self.url = f"{host.rstrip('/')}/api/embeddings"
        self.timeout = timeout or settings.get("embedding_timeout")

    def embed(self, text: str) -> list[float]:
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
