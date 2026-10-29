from providers.ollama_provider import OllamaProvider
from memory.memory_manager import MemoryManager
from memory.project_memory import ProjectMemory
from config.settings_manager import SettingsManager
from providers.gemini_provider import GeminiProvider
from core.model_selection import StickyModel, model_for, thinks
from core.provenance import (
    DESCONOCIDO,
    MEMORIA,
    PROYECTO,
    Fragment,
    current_fragments,
    labels_of,
    most_restrictive,
)


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
        # Etiqueta de procedencia de cada mensaje de history (core/provenance.py).
        self.history_labels = []
        self.last_fragments = None
        # Modelo del chat: se mantiene mientras siga la conversación.
        self.sticky_model = StickyModel()

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

    def ask(self, prompt: str, review=False, domain="code") -> str:
        """Llamada de un solo turno, sin historial de chat ni contexto personal.

        La usan las acciones internas (resúmenes, revisiones, generación de
        código), que ya incluyen en el prompt todo el contexto que necesitan.
        review=True para las revisiones de código: usan temperatura baja y
        penalización de repetición (ver ollama_provider.review_options).
        domain elige el modelo en models_by_domain: las acciones internas son
        de código.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        # Lo que leyeron las acciones (archivos, RAG, proyecto) está anotado
        # en la petición en curso; sin registro, todo cuenta como local.
        fragments = current_fragments() or [Fragment(DESCONOCIDO, prompt)]
        self.last_fragments = fragments

        try:
            return self._complete(
                messages, review=review, model=model_for(self.settings, domain),
                think=thinks(self.settings, domain), fragments=fragments
            )
        except ProviderError as e:
            return str(e)

    def chat(self, prompt: str, on_chunk=None, history_prompt=None) -> str:
        """Conversación con el usuario: incluye memoria, proyecto e historial.

        history_prompt es lo que se guarda en el historial en lugar de prompt
        (p. ej. el mensaje sin el contenido de los archivos adjuntos).

        Procedencia: la memoria y el resumen del proyecto del prompt de
        sistema, cada mensaje del historial con la etiqueta que heredó su
        turno y lo que trae este mensaje (usuario, adjuntos...).
        """
        memory_context = self.build_memory_context()
        project_context = self.build_project_context()
        system_prompt = f"""{SYSTEM_PROMPT}

Contexto personal:
{memory_context}

Contexto del proyecto:
{project_context}
"""

        user_message = {"role": "user", "content": prompt}

        messages = [
            {"role": "system", "content": system_prompt},
            *self.history,
            user_message
        ]

        ambient = []

        if self.memory.load():
            ambient.append(Fragment(MEMORIA, memory_context))

        if project_context:
            ambient.append(Fragment(PROYECTO, project_context))

        turn = current_fragments() or [Fragment(DESCONOCIDO, prompt)]
        past = [Fragment(label, m["content"]) for m, label in zip(self.history, self.history_labels)]
        fragments = ambient + past + turn
        self.last_fragments = fragments

        try:
            model = self.sticky_model.choose(prompt, self.settings)
            think = thinks(self.settings, self.sticky_model.domain)
            answer = self._complete(
                messages, on_chunk=on_chunk, model=model, think=think, fragments=fragments
            )
        except ProviderError as e:
            if on_chunk:
                on_chunk(str(e))

            return str(e)

        if history_prompt is not None:
            user_message = {"role": "user", "content": history_prompt}

        # El turno (pregunta y respuesta) hereda la etiqueta más restrictiva
        # de lo que lo originó: una respuesta sobre un adjunto queda local.
        label = most_restrictive(labels_of(turn) | labels_of(ambient))

        self.history.append(user_message)
        self.history.append({"role": "assistant", "content": answer})
        self.history_labels += [label, label]
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        self.history_labels = self.history_labels[-MAX_HISTORY_MESSAGES:]

        return answer

    def _complete(self, messages: list[dict], on_chunk=None, review=False, model=None, think=False, fragments=None) -> str:
        provider_name = self.settings.get("default_provider", "ollama")

        try:
            provider = self.get_provider(provider_name)
            return provider.complete(messages, on_chunk=on_chunk, review=review, model=model, think=think)
        except Exception as e:
            fallback_name = self.settings.get("fallback_provider", None)

            if not fallback_name or fallback_name == provider_name:
                raise ProviderError(
                    f"Error usando provider {provider_name}: {e}"
                ) from e

            try:
                fallback_provider = self.get_provider(fallback_name)
                response = fallback_provider.complete(messages, review=review, model=model, think=think)
            except Exception as fallback_error:
                raise ProviderError(
                    "Falló el provider principal y también el fallback. "
                    f"Error: {fallback_error}"
                ) from fallback_error

            response = f"[Fallback: usando {fallback_name}]\n\n{response}"

            if on_chunk:
                on_chunk(response)

            return response
