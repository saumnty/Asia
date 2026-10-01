import ollama

from config.settings_manager import SettingsManager


class OllamaProvider:
    def __init__(self):
        self.settings = SettingsManager()
        self.client = ollama.Client(host=self.settings.get("ollama_host"))

    def complete(self, messages: list[dict], on_chunk=None) -> str:
        """Envía los mensajes y devuelve la respuesta completa.

        Si se pasa on_chunk, la respuesta se transmite en streaming y cada
        fragmento se entrega a on_chunk a medida que llega.
        """
        # Se lee en cada llamada para que un cambio en settings.json se
        # aplique sin reiniciar Asia.
        model = self.settings.get("ollama_model")

        if on_chunk is None:
            response = self.client.chat(
                model=model,
                messages=messages
            )

            return response["message"]["content"]

        stream = self.client.chat(
            model=model,
            messages=messages,
            stream=True
        )

        full_response = ""

        for chunk in stream:
            content = chunk["message"]["content"]
            on_chunk(content)
            full_response += content

        return full_response
