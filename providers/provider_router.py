from providers.ollama_provider import OllamaProvider
from memory.memory_manager import MemoryManager
from memory.project_memory import ProjectMemory
from config.settings_manager import SettingsManager
from providers.gemini_provider import GeminiProvider


class ProviderRouter:
    def __init__(self):
        self.settings = SettingsManager()
        self.memory = MemoryManager()
        self.project_memory = ProjectMemory()
        self.providers = {
            "ollama": OllamaProvider(),
            "gemini": GeminiProvider()
        }
        

    def build_memory_context(self):
        data = self.memory.load()

        if not data:
            return "No hay memoria guardada."

        return "\n".join(
            f"- {key}: {value}"
            for key, value in data.items()
        )

    def build_project_context(self):
        data = self.memory.load()
        project_name = data.get("proyecto")

        if not project_name:
            return ""

        summary = self.project_memory.load_project_summary(project_name)

        if not summary:
            return ""

        return summary

    def ask(self, prompt: str) -> str:
        provider_name = self.settings.get("default_provider", "ollama")
        provider = self.providers.get(provider_name)

        if not provider:
            return f"Proveedor no disponible: {provider_name}"

        memory_context = self.build_memory_context()
        project_context = self.build_project_context()

        final_prompt = f"""
Contexto personal:
{memory_context}

Contexto del proyecto:
{project_context}

Mensaje del usuario:
{prompt}
"""

        try:
            stream_output = self.settings.get("stream_output", False)

            if stream_output and hasattr(provider, "ask_stream"):
                return provider.ask_stream(final_prompt)

            return provider.ask(final_prompt)
        except Exception as e:
            fallback_name = self.settings.get("fallback_provider", None)

            if fallback_name and fallback_name != provider_name:
                fallback_provider = self.providers.get(fallback_name)

                if fallback_provider:
                    try:
                        response = fallback_provider.ask(final_prompt)

                        return (
                            f"[Fallback: usando {fallback_name}]\n\n"
                            + response
                        )
                    except Exception as fallback_error:
                        return f"Falló el provider principal y también el fallback. Error: {fallback_error}"

            return f"Error usando provider {provider_name}: {e}"