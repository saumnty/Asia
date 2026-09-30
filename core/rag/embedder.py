import requests


class OllamaEmbedder:
    def __init__(self, model="nomic-embed-text"):
        self.model = model
        self.url = "http://localhost:11434/api/embeddings"

    def embed(self, text: str) -> list[float]:
        response = requests.post(
            self.url,
            json={
                "model": self.model,
                "prompt": text
            }
        )

        response.raise_for_status()
        return response.json()["embedding"]