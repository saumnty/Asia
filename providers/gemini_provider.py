from google import genai
from google.genai import types
from config.settings_manager import SettingsManager


class GeminiProvider:
    def __init__(self):
        self.settings = SettingsManager()
        self.client = genai.Client()
        self.model = self.settings.get("gemini_model", "gemini-2.5-flash")

    def complete(self, messages: list[dict], on_chunk=None) -> str:
        """Envía los mensajes y devuelve la respuesta completa.

        Si se pasa on_chunk, la respuesta se transmite en streaming y cada
        fragmento se entrega a on_chunk a medida que llega.
        """
        system_instruction = "\n\n".join(
            message["content"]
            for message in messages
            if message["role"] == "system"
        )

        contents = [
            types.Content(
                role="model" if message["role"] == "assistant" else "user",
                parts=[types.Part(text=message["content"])]
            )
            for message in messages
            if message["role"] != "system"
        ]

        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None
        )

        if on_chunk is None:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config
            )

            return response.text or ""

        stream = self.client.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=config
        )

        full_response = ""

        for chunk in stream:
            if chunk.text:
                on_chunk(chunk.text)
                full_response += chunk.text

        return full_response
