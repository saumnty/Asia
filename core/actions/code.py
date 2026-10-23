"""Generación y refactor de código, y el cambio pendiente (confirmar/cancelar)."""
import os
import re
from pathlib import Path

from core import prompts
from core.paths import PROJECT_ROOT
from tools.import_check import ImportPolicy, check_imports, refusal_message, rewrite_note, rewrite_request


# Archivos de Asia que generate_code nunca propone reescribir.
PROTECTED_FILES = [
    PROJECT_ROOT / "core" / "brain.py",
    PROJECT_ROOT / "core" / "intent_engine.py",
    PROJECT_ROOT / "tools" / "tool_registry.py",
]

# Cambios que alteran el comportamiento observable: se rechazan.
FORBIDDEN_CHANGES = [
    ("return None", "raise "),
    ("print(", "raise "),
]

FORBIDDEN_CHANGE_MESSAGE = (
    "Refactor rechazado automáticamente.\n\n"
    "El cambio modifica el comportamiento observable "
    "del programa (prints/returns/excepciones)."
)


def normalized_path(path) -> str:
    # normcase: en Windows "CORE\Brain.py" y "core/brain.py" son el mismo archivo.
    return os.path.normcase(str(Path(path).resolve()))


def is_protected_file(file_path: str) -> bool:
    """Compara rutas resueltas, no texto: "./core/brain.py", "core\\brain.py"
    o la ruta absoluta apuntan al mismo archivo protegido. Un core/brain.py de
    otro proyecto (otra carpeta actual) no está protegido.
    """
    target = normalized_path(file_path)
    return any(target == normalized_path(protected) for protected in PROTECTED_FILES)


def parse_code_response(response):
    """Extrae FILE_PATH, CODE y EXPLANATION de una respuesta del LLM.

    Devuelve (file_path, code, explanation), o None si no hay sección CODE.
    file_path es None si el LLM no lo incluyó.
    """
    file_match = re.search(
        r"FILE_PATH:\s*(.*?)\s*CODE:",
        response,
        re.DOTALL
    )

    file_path = file_match.group(1).strip() if file_match else None

    code_start = response.find("CODE:")

    if code_start == -1:
        return None

    explanation_pos = response.find("EXPLANATION:")
    explanation_label = "EXPLANATION:"

    if explanation_pos == -1:
        explanation_pos = response.find("EXPLANACIÓN:")
        explanation_label = "EXPLANACIÓN:"

    if explanation_pos == -1:
        code_text = response[code_start + len("CODE:"):]
        explanation = ""
    else:
        code_text = response[code_start + len("CODE:"):explanation_pos]
        explanation = response[
            explanation_pos + len(explanation_label):
        ].strip()

    code = code_text.strip()
    code = code.replace("```python", "")
    code = code.replace("```", "")
    code = code.strip()

    return file_path, code, explanation


def normalize_code(value):
    return "\n".join(
        line.rstrip()
        for line in value.strip().splitlines()
    )


class CodeActions:
    HANDLERS = {
        "smart_refactor": "handle_smart_refactor",
        "generate_code": "handle_generate_code",
        "apply_change": "handle_apply_change",
        "cancel_change": "handle_cancel_change",
        "show_pending_change": "handle_show_pending_change",
    }

    def import_policy(self, file_path):
        """Imports permitidos para file_path (ver tools/import_check.py)."""
        return ImportPolicy.for_file(
            file_path or "nuevo.py",
            Path.cwd(),
            self.settings.get("allowed_imports", [])
        )

    def check_generated_imports(self, prompt, file_path, code, explanation):
        """Comprueba los imports de un .py generado antes de proponerlo.

        Si hay imports no instalados o no permitidos, se pide una reescritura
        (una sola vez). Devuelve (code, explanation, error); error no es None
        si ni la reescritura sirve, y entonces no se propone el cambio.
        """
        if not str(file_path).lower().endswith(".py"):
            return code, explanation, None

        policy = self.import_policy(file_path)
        report = check_imports(code, policy)

        if report.ok:
            return code, explanation, None

        parsed = parse_code_response(
            self.provider_router.ask(prompt + rewrite_request(report))
        )

        if parsed:
            _, new_code, new_explanation = parsed
            new_report = check_imports(new_code, policy)

            if new_report.ok:
                note = rewrite_note(report, code, new_code)
                return new_code, f"{note}\n\n{new_explanation or explanation}".rstrip(), None

            report = new_report

        return code, explanation, refusal_message(file_path, report)

    def propose(self, file_path, code, explanation):
        diff_message = self.tool_registry.get_apply_changes_tool().propose_change(
            file_path=file_path,
            new_content=code
        )

        return f"""
{explanation}

{diff_message}
"""

    def handle_smart_refactor(self, text, params):
        file_path = params.get("file_path")
        request = params.get("request", text)

        if not file_path:
            return "Necesito la ruta del archivo para refactorizarlo."

        if not Path(file_path).is_file():
            return f"No encontré el archivo: {file_path}"

        # Se revisa antes de llamar al LLM: el refactor siempre va al
        # archivo pedido, así que no tiene sentido generarlo.
        if is_protected_file(file_path):
            return (
                f"{file_path} es un archivo protegido de Asia.\n"
                "No propondré un refactor automático. Edítalo a mano o "
                "pide refactorizar un archivo menos crítico."
            )

        content = self.tool_registry.execute(
            "read_file",
            file_path=file_path
        )

        static_findings = self.tool_registry.execute(
            "analyze_static",
            file_path=file_path
        )

        prompt = prompts.smart_refactor(
            request, file_path, content, static_findings,
            self.import_policy(file_path).describe()
        )

        response = self.provider_router.ask(prompt)

        parsed = parse_code_response(response)

        if not parsed:
            return f"No pude extraer CODE.\n\nRespuesta recibida:\n{response}"

        # Se ignora el FILE_PATH que devuelva el LLM: el refactor siempre
        # se aplica al archivo que pidió el usuario.
        _, code, explanation = parsed

        if normalize_code(content) == normalize_code(code):
            return f"No se requieren cambios reales en {file_path}."

        code, explanation, import_error = self.check_generated_imports(
            prompt, file_path, code, explanation
        )

        if import_error:
            return import_error

        for old_pattern, new_pattern in FORBIDDEN_CHANGES:
            if old_pattern in content and new_pattern in code:
                return FORBIDDEN_CHANGE_MESSAGE

        return self.propose(file_path, code, explanation)

    def handle_generate_code(self, text, params):
        request = params.get("request", text)

        debug_context = ""

        if self.last_debug_report and (
            "bug" in request.lower()
            or "bugs" in request.lower()
            or "diagnóstico" in request.lower()
            or "diagnostico" in request.lower()
            or "detectados" in request.lower()
        ):
            debug_context = self.last_debug_report

        target_file = None
        target_match = re.search(r"([\w./\\-]+\.[a-zA-Z0-9]+)", request)

        if target_match:
            target_file = target_match.group(1).replace("\\", "/")

        project_context = self.tool_registry.execute(
            "read_folder_context",
            folder_path=".",
            **self.limit("generate_code_project")
        )

        target_file_content = ""

        if target_file and Path(target_file).exists():
            target_file_content = self.tool_registry.execute(
                "read_file_preview",
                file_path=target_file,
                max_chars=self.limit("generate_code_file")
            )

        prompt = prompts.generate_code(
            request, target_file, target_file_content, project_context, debug_context,
            self.import_policy(target_file).describe()
        )

        response = self.provider_router.ask(prompt)

        parsed = parse_code_response(response)

        if not parsed:
            return f"No pude extraer CODE.\n\nRespuesta recibida:\n{response}"

        file_path, code, explanation = parsed

        # Si el usuario nombró un archivo existente, el cambio va a ese
        # archivo aunque el LLM devuelva otra ruta.
        if target_file and Path(target_file).is_file():
            file_path = target_file

        if not file_path:
            return f"No pude extraer FILE_PATH.\n\nRespuesta recibida:\n{response}"

        code, explanation, import_error = self.check_generated_imports(
            prompt, file_path, code, explanation
        )

        if import_error:
            return import_error

        old_content = ""

        if Path(file_path).exists():
            old_content = Path(file_path).read_text(encoding="utf-8").strip()

        for old_pattern, new_pattern in FORBIDDEN_CHANGES:
            if old_pattern in old_content and new_pattern in code:
                return FORBIDDEN_CHANGE_MESSAGE

        if "re." in code and "import re" not in code:
            code = "import re\n\n" + code

        if not file_path or not code:
            return f"Faltan datos para proponer el cambio.\n\nRespuesta recibida:\n{response}"

        # La indentación del mensaje es la que tenía en core/brain.py.
        if is_protected_file(file_path):
            return f"""
            Asia generó un cambio para un archivo protegido:

            {file_path}

            Por seguridad no lo aplicaré automáticamente todavía.
            Primero revisa el cambio manualmente o pide modificar un archivo menos crítico.
            """

        if old_content == code.strip():
            return f"No se requieren cambios en {file_path}."

        return self.propose(file_path, code, explanation)

    def handle_apply_change(self, text, params):
        return self.tool_registry.get_apply_changes_tool().apply_pending_change()

    def handle_cancel_change(self, text, params):
        return self.tool_registry.get_apply_changes_tool().cancel_pending_change()

    def handle_show_pending_change(self, text, params):
        return self.tool_registry.get_apply_changes_tool().show_pending_change()
