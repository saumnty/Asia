from providers.ollama_provider import OllamaProvider
from memory.memory_manager import MemoryManager
from memory.project_memory import ProjectMemory
from config.settings_manager import SettingsManager
from providers.gemini_provider import GeminiProvider


SYSTEM_PROMPT = (
    "Eres Asia, un asistente local. "
    "Responde en español, de forma clara y útil."
)

# Mensajes (usuario + asistente) que se conservan del chat con el usuario.
MAX_HISTORY_MESSAGES = 20


class ProviderError(Exception):
    pass


class ProviderRouter:
    # Los providers se crean al primer uso: así un provider mal configurado
    # (p. ej. Gemini sin API key) no impide arrancar Asia con otro.
    provider_factories = {
        "ollama": OllamaProvider,
        "gemini": GeminiProvider
    }

    def __init__(self):
        self.settings = SettingsManager()
        self.memory = MemoryManager()
        self.project_memory = ProjectMemory()
        self.providers = {}
        self.history = []

    def get_provider(self, name: str):
        if name not in self.providers:
            factory = self.provider_factories.get(name)

            if not factory:
                raise ProviderError(f"Proveedor no disponible: {name}")

            self.providers[name] = factory()

        return self.providers[name]

    def build_memory_context(self):
        data = self.memory.load()

        if not data:
            return "No hay memoria guardada."

        return "\n".join(
            f"- {key}: {value}"
            for key, value in data.items()
        )

    def build_project_context(self):
        project_name = self.settings.get("active_project")

        if not project_name:
            return ""

        summary = self.project_memory.load_project_summary(project_name)

        if not summary:
            return ""

        return summary

    def ask(self, prompt: str) -> str:
        """Llamada de un solo turno, sin historial de chat ni contexto personal.

        La usan las acciones internas (resúmenes, revisiones, generación de
        código), que ya incluyen en el prompt todo el contexto que necesitan.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]

        try:
            return self._complete(messages)
        except ProviderError as e:
            return str(e)

    def chat(self, prompt: str, on_chunk=None) -> str:
        """Conversación con el usuario: incluye memoria, proyecto e historial."""
        system_prompt = f"""{SYSTEM_PROMPT}

Contexto personal:
{self.build_memory_context()}

Contexto del proyecto:
{self.build_project_context()}
"""

        user_message = {"role": "user", "content": prompt}

        messages = [
            {"role": "system", "content": system_prompt},
            *self.history,
            user_message
        ]

        try:
            answer = self._complete(messages, on_chunk=on_chunk)
        except ProviderError as e:
            if on_chunk:
                on_chunk(str(e))

            return str(e)

        self.history.append(user_message)
        self.history.append({"role": "assistant", "content": answer})
        self.history = self.history[-MAX_HISTORY_MESSAGES:]

        return answer

    def _complete(self, messages: list[dict], on_chunk=None) -> str:
        provider_name = self.settings.get("default_provider", "ollama")

        try:
            provider = self.get_provider(provider_name)
            return provider.complete(messages, on_chunk=on_chunk)
        except Exception as e:
            fallback_name = self.settings.get("fallback_provider", None)

            if not fallback_name or fallback_name == provider_name:
                raise ProviderError(
                    f"Error usando provider {provider_name}: {e}"
                ) from e

            try:
                fallback_provider = self.get_provider(fallback_name)
                response = fallback_provider.complete(messages)
            except Exception as fallback_error:
                raise ProviderError(
                    "Falló el provider principal y también el fallback. "
                    f"Error: {fallback_error}"
                ) from fallback_error

            response = f"[Fallback: usando {fallback_name}]\n\n{response}"

            if on_chunk:
                on_chunk(response)

            return response
