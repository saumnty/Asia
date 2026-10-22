"""Revisión de archivos y proyectos, código muerto y depuración."""
from core import prompts


NO_SYNTHESIS_PHRASES = ("sin síntesis", "sin sintesis", "por archivo")


def wants_synthesis(text, params, default=True) -> bool:
    """Decide si review_project termina con la síntesis del LLM.

    Frases como "sin síntesis" en el mensaje mandan sobre todo lo demás, para
    no depender de que el IntentEngine llene el parámetro. Si no aparecen, se
    usa params["synthesis"] (puede llegar como texto) y luego el default.
    """
    lowered = (text or "").lower()

    if any(phrase in lowered for phrase in NO_SYNTHESIS_PHRASES):
        return False

    value = params.get("synthesis")

    if isinstance(value, bool):
        return value

    if isinstance(value, str) and value.strip():
        return value.strip().lower() not in ("false", "no", "0")

    return default


UNVERIFIED_PHRASES = ("sin verificar", "no verificad", "incluye todo", "muestra todo")


def wants_unverified(text) -> bool:
    """True si el usuario pide ver también los hallazgos cuya cita no existe."""
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in UNVERIFIED_PHRASES)


class ReviewActions:
    HANDLERS = {
        "review_file": "handle_review_file",
        "review_project": "handle_review_project",
        "detect_dead_code": "handle_detect_dead_code",
        "debug_project": "handle_debug_project",
        "review_file_deep": "handle_review_file_deep",
    }

    def handle_review_file(self, text, params):
        file_path = params.get("file_path")

        if not file_path:
            return "Necesito la ruta del archivo para revisarlo."

        content = self.tool_registry.execute(
            "read_file_preview",
            file_path=file_path,
            max_chars=self.limit("review_file")
        )

        return self.provider_router.ask(prompts.review_file(file_path, content), review=True)

    def handle_review_project(self, text, params):
        folder_path = params.get("folder_path", ".")

        priority_files = self.tool_registry.execute(
            "select_project_files",
            folder_path=folder_path,
            max_files=self.limit("review_project_files")
        )

        per_file_report = self.tool_registry.execute(
            "review_project_files",
            file_paths=priority_files,
            max_chars=self.limit("review_project_file"),
            show_unverified=wants_unverified(text)
        )

        synthesis_default = self.settings.get("review_project_synthesis", True)

        # Sin síntesis se devuelven los reportes por archivo tal cual: en
        # las pruebas fueron más precisos que el resumen final del modelo.
        if not wants_synthesis(text, params, synthesis_default):
            files_list = "\n".join(f"- {path}" for path in priority_files)

            return (
                f"Reportes por archivo de {folder_path} (sin síntesis).\n\n"
                f"Archivos revisados:\n{files_list or '- ninguno'}\n"
                f"{per_file_report}"
            )

        return self.provider_router.ask(
            prompts.review_project(priority_files, per_file_report), review=True
        )

    def handle_detect_dead_code(self, text, params):
        folder_path = params.get("folder_path", ".")

        raw_report = self.tool_registry.execute(
            "detect_dead_code",
            folder_path=folder_path
        )

        return self.provider_router.ask(prompts.detect_dead_code(raw_report))

    def handle_debug_project(self, text, params):
        issue = params.get("issue", text)
        folder_path = params.get("folder_path", ".")

        debug_report = self.tool_registry.execute(
            "debug_project",
            issue=issue,
            folder_path=folder_path
        )

        self.last_debug_report = debug_report

        # La indentación del mensaje es la que tenía en core/brain.py.
        return f"""
            Diagnóstico de depuración:

            {debug_report}

            Si quieres que proponga un cambio automático, escribe algo como:

            genera el fix para el archivo principal usando este diagnóstico
            """

    def handle_review_file_deep(self, text, params):
        file_path = params.get("file_path")

        if not file_path:
            return "Necesito la ruta del archivo para revisarlo profundamente."

        debug_report = self.tool_registry.execute(
            "review_file_deep",
            file_path=file_path,
            show_unverified=wants_unverified(text)
        )

        self.last_debug_report = debug_report

        return debug_report
