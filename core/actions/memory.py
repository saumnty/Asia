"""Memoria personal, memoria del proyecto y ajustes (provider, proyecto activo)."""
from core import prompts
from core.provenance import PROYECTO, Fragment, record


class MemoryActions:
    HANDLERS = {
        "remember": "handle_remember",
        "recall": "handle_recall",
        "forget": "handle_forget",
        "summarize_and_save_project": "handle_summarize_and_save_project",
        "ask_project_memory": "handle_ask_project_memory",
        "update_project_memory": "handle_update_project_memory",
        "show_settings": "handle_show_settings",
        "set_provider": "handle_set_provider",
        "set_active_project": "handle_set_active_project",
        "show_active_project": "handle_show_active_project",
    }

    # remember, recall y forget sin key (o sin value) no hacen nada: el
    # mensaje sigue como conversación normal.
    def handle_remember(self, text, params):
        key, value = params.get("key"), params.get("value")

        if not (key and value):
            return None

        self.memory.remember(key, value)
        return f"Entendido. Recordaré que {key} es {value}."

    def handle_recall(self, text, params):
        key = params.get("key")

        if not key:
            return None

        result = self.memory.recall(key)

        if result:
            return f"{key}: {result}"

        return f"No tengo guardado ningún dato para: {key}."

    def handle_forget(self, text, params):
        key = params.get("key")

        if not key:
            return None

        deleted = self.memory.forget(key)

        if deleted:
            return f"Listo. Olvidé el dato: {key}."

        return f"No tenía guardado ningún dato para: {key}."

    def handle_summarize_and_save_project(self, text, params):
        folder_path = params.get("folder_path", ".")
        project_name = self.active_project()

        content = self.tool_registry.execute(
            "read_folder_context",
            folder_path=folder_path,
            **self.limit("save_project_summary")
        )

        summary = self.provider_router.ask(
            prompts.summarize_and_save_project(project_name, content)
        )

        self.project_memory.save_project_summary(
            project_name,
            summary
        )

        return f"Resumen actualizado y guardado para el proyecto {project_name}."

    def handle_ask_project_memory(self, text, params):
        question = params.get("question", text)
        project_name = self.active_project()
        project_summary = self.project_memory.load_project_summary(project_name)

        if not project_summary:
            return f"No tengo resumen guardado para el proyecto {project_name}."

        record(Fragment(PROYECTO, project_summary))

        return self.provider_router.ask(
            prompts.ask_project_memory(project_name, project_summary, question)
        )

    def handle_update_project_memory(self, text, params):
        note = params.get("note")

        if not note:
            return "Necesito una nota para actualizar la memoria del proyecto."

        project_name = self.active_project()

        self.project_memory.append_project_note(
            project_name,
            note
        )

        return f"Memoria del proyecto {project_name} actualizada."

    def handle_show_settings(self, text, params):
        provider = self.settings.get("default_provider")
        fallback = self.settings.get("fallback_provider")
        stream = self.settings.get("stream_output", False)
        model = self.settings.get(f"{provider}_model")

        return (
            f"Provider actual: {provider}\n"
            f"Modelo: {model}\n"
            f"Fallback: {fallback}\n"
            f"Streaming: {stream}\n"
            f"Proyecto activo: {self.active_project()}"
        )

    def handle_set_provider(self, text, params):
        provider = params.get("provider")

        if not provider:
            return "Necesito saber qué provider quieres usar."

        provider = provider.lower().strip()

        aliases = self.settings.get("provider_aliases", {})
        provider = aliases.get(provider, provider)

        if provider not in self.provider_router.provider_factories:
            return f"Provider no disponible todavía: {provider}"

        self.settings.set("default_provider", provider)

        return f"Provider cambiado a: {provider}"

    def handle_set_active_project(self, text, params):
        project_name = params.get("project_name")

        if not project_name:
            return "Necesito saber a qué proyecto quieres cambiar."

        project_name = project_name.lower().strip()

        aliases = self.settings.get("project_aliases", {})
        project_name = aliases.get(project_name, project_name)

        self.settings.set("active_project", project_name)

        return f"Proyecto activo cambiado a: {project_name}"

    def handle_show_active_project(self, text, params):
        return f"Proyecto activo: {self.active_project()}"
