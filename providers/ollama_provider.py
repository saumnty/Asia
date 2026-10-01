import ollama


class OllamaProvider:
    def __init__(self, model="qwen2.5-coder:7b"):
        self.model = model

    def complete(self, messages: list[dict], on_chunk=None) -> str:
        """Envía los mensajes y devuelve la respuesta completa.

        Si se pasa on_chunk, la respuesta se transmite en streaming y cada
        fragmento se entrega a on_chunk a medida que llega.
        """
        if on_chunk is None:
            response = ollama.chat(
                model=self.model,
                messages=messages
            )

            return response["message"]["content"]

        stream = ollama.chat(
            model=self.model,
            messages=messages,
            stream=True
        )

        full_response = ""

        for chunk in stream:
            content = chunk["message"]["content"]
            on_chunk(content)
            full_response += content

        return full_response
