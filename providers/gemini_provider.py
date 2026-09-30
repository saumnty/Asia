from google import genai
from config.settings_manager import SettingsManager


class GeminiProvider:
    def __init__(self):
        self.settings = SettingsManager()
        self.client = genai.Client()
        self.model = self.settings.get("gemini_model", "gemini-2.5-flash")

    def ask(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt
        )

        return response.text
    
    def ask_stream(self, prompt: str) -> str:
        stream = self.client.models.generate_content_stream(
            model=self.model,
            contents=prompt
        )

        full_response = ""

        for chunk in stream:
            if chunk.text:
                print(chunk.text, end="", flush=True)
                full_response += chunk.text

        print()

        return None