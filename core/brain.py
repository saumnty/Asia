from memory.memory_manager import MemoryManager
from core.intent_engine import IntentEngine
from tools.tool_registry import ToolRegistry
from providers.provider_router import ProviderRouter
from memory.project_memory import ProjectMemory
from config.settings_manager import SettingsManager
from core.actions.explore import ExploreActions
from core.actions.memory import MemoryActions
# wants_synthesis y wants_unverified se importan desde aquí en las pruebas.
from core.actions.review import ReviewActions, wants_synthesis, wants_unverified  # noqa: F401
from core.paths import PROJECT_ROOT
from tools.import_check import ImportPolicy, check_imports, refusal_message, rewrite_request
from tools.sandbox import PendingRun, SandboxRunner, format_result, sandbox_import_problems
from pathlib import Path
import os
import re


# Archivos de Asia que generate_code nunca propone reescribir.
PROTECTED_FILES = [
    PROJECT_ROOT / "core" / "brain.py",
    PROJECT_ROOT / "core" / "intent_engine.py",
    PROJECT_ROOT / "tools" / "tool_registry.py",
]


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


# El IntentEngine inventa rutas cuando el mensaje no trae ninguna
# ("path/to/your/file.py", "path_to_your_file.py") y la acción intentaba
# leerlas. Una ruta solo se usa si sale del mensaje del usuario.
FILE_PARAMS = ("file_path",)
FOLDER_PARAMS = ("folder_path", "project_path")
CURRENT_FOLDER = {"", ".", "./", ".\\"}

# El mensaje habla de un archivo concreto: "este archivo", "el script", "x.py".
FILE_WORDS = re.compile(
    r"\b(archivo|fichero|file|script|m[oó]dulo)s?\b|\b[\w-]+\.[a-z][a-z0-9]{0,4}\b",
    re.IGNORECASE
)

MISSING_FILE_MESSAGE = (
    "Necesito la ruta del archivo: escríbela en el mensaje o adjúntalo con @ruta."
)


def path_in_text(value: str, text: str) -> bool:
    """True si la ruta value sale del mensaje del usuario.

    Vale la ruta tal cual, su nombre con extensión ("core/brain.py" si el
    usuario escribió "brain.py") o, si la ruta existe, su nombre sin extensión
    ("explica el archivo brain", "revisa utils" para core/utils).
    """
    def norm(s):
        return s.replace("\\", "/").lower().strip().strip("\"'")

    path, message = norm(value), norm(text)

    if not path:
        return False

    # Como palabra completa: "brain.py" no sale de "mybrain.py".
    def word(w):
        return bool(w) and re.search(rf"(?<![\w.]){re.escape(w)}(?![\w])", message)

    name = path.rstrip("/").rsplit("/", 1)[-1]

    if word(path) or ("." in name and word(name)):
        return True

    # Un nombre sin extensión ("archivo", "brain") es una palabra común: solo
    # cuenta si la ruta existe. Si no, "ruta/al/archivo" pasaría con
    # "explica este archivo".
    return Path(value).exists() and (word(name) or word(Path(name).stem))


def drop_invented_paths(text: str, params: dict):
    """Quita de params las rutas que no salen del mensaje.

    Devuelve (params, falta_archivo). Una carpeta inventada pasa a ser la
    carpeta actual; un archivo inventado se quita y falta_archivo es True.
    """
    params = dict(params)
    missing_file = False

    for key in FILE_PARAMS:
        value = params.get(key)

        if isinstance(value, str) and not path_in_text(value, text):
            del params[key]
            missing_file = True

    for key in FOLDER_PARAMS:
        value = params.get(key)

        if isinstance(value, str) and value.strip() not in CURRENT_FOLDER and not path_in_text(value, text):
            params[key] = "."

    return params, missing_file


# Confirmar o cancelar una ejecución en el sandbox se reconoce por texto
# exacto, sin el IntentEngine: nada se ejecuta por una mala interpretación.
RUN_CONFIRM_PHRASES = {"confirmar ejecución", "confirmar ejecucion", "confirmo ejecución", "confirmo ejecucion"}
RUN_CANCEL_PHRASES = {"cancelar ejecución", "cancelar ejecucion"}


def normalized_command(text) -> str:
    return " ".join((text or "").lower().split()).strip(" .!¡")


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


class Brain(MemoryActions, ExploreActions, ReviewActions):
    # Acción del IntentEngine -> método que la atiende (ver core/actions).
    HANDLERS = {
        **MemoryActions.HANDLERS,
        **ExploreActions.HANDLERS,
        **ReviewActions.HANDLERS,
    }

    def __init__(self):
        self.memory = MemoryManager()
        self.intent_engine = IntentEngine()
        self.provider_router = ProviderRouter()
        self.tool_registry = ToolRegistry(self.provider_router)
        self.project_memory = ProjectMemory()
        self.settings = SettingsManager()
        self.last_debug_report = None
        self.pending_run = PendingRun()

    def sandbox(self):
        return SandboxRunner(
            timeout=self.settings.get("sandbox_timeout", 20),
            max_output=self.settings.get("sandbox_max_output", 4000)
        )

    def prepare_run(self, label, script_name, code):
        """Deja lista una ejecución en el sandbox; corre con "confirmar ejecución"."""
        if not script_name.lower().endswith(".py"):
            return f"Solo ejecuto archivos .py en el sandbox ({script_name} no lo es)."

        problems = sandbox_import_problems(code)

        if problems:
            listed = "\n".join(f"- {problem}" for problem in problems)
            return (
                f"No ejecuto {label}: el sandbox solo tiene la biblioteca estándar "
                f"y este código importa:\n{listed}\n"
                "Fallaría con ModuleNotFoundError. Asia no instala paquetes en el sandbox."
            )

        self.pending_run.save(label, script_name, code)
        lines = len(code.splitlines())

        return (
            f"Ejecución preparada: {label} ({lines} líneas).\n"
            f"Correrá en un venv desechable solo con la biblioteca estándar, en una "
            f"carpeta temporal, sin stdin y con un límite de "
            f"{self.settings.get('sandbox_timeout', 20)} s.\n"
            "Ojo: el sandbox aísla paquetes, no el sistema. El código corre con tus "
            "permisos y puede leer o modificar tus archivos y usar la red.\n"
            'Escribe "confirmar ejecución" para correrlo o "cancelar ejecución".'
        )

    def confirm_run(self):
        pending = self.pending_run.load()

        if not pending:
            return "No hay ninguna ejecución pendiente."

        # Se borra antes de correr: si Asia se cae a mitad, no se repite sola.
        self.pending_run.clear()
        runner = self.sandbox()
        result = runner.run(pending["code"], pending["script_name"])

        return format_result(pending["label"], result, runner.timeout)

    def cancel_run(self):
        if not self.pending_run.load():
            return "No hay ninguna ejecución pendiente."

        self.pending_run.clear()
        return "Ejecución cancelada."

    def run_sandbox(self, params):
        file_path = params.get("file_path")

        if file_path:
            path = Path(file_path)

            if not path.is_file():
                return f"No encontré el archivo: {file_path}"

            return self.prepare_run(str(path), path.name, path.read_text(encoding="utf-8"))

        pending_change = self.tool_registry.get_apply_changes_tool().load_pending_change()

        if not pending_change:
            return (
                "No hay un cambio pendiente que probar. Indica el archivo, por "
                "ejemplo: ejecuta @script.py en el sandbox."
            )

        target = pending_change["file_path"]
        return self.prepare_run(
            f"cambio pendiente para {target}", Path(target).name, pending_change["new_content"]
        )

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
                return new_code, new_explanation or explanation, None

            report = new_report

        return code, explanation, refusal_message(file_path, report)

    def limit(self, name):
        """Límite de contexto configurado en context_limits (settings)."""
        return self.settings.get("context_limits")[name]

    def active_project(self):
        return self.settings.get("active_project").lower().strip()

    def process(self, text):
        """Ejecuta la acción detectada en el texto.

        Devuelve None si el mensaje es conversación normal (acción "chat" o
        no reconocida); en ese caso quien llama debe usar provider_router.chat.
        """
        command = normalized_command(text)

        if command in RUN_CONFIRM_PHRASES:
            return self.confirm_run()

        if command in RUN_CANCEL_PHRASES:
            return self.cancel_run()

        intent = self.intent_engine.detect(text)

        action = intent.get("action")
        params = intent.get("params")

        if not isinstance(params, dict):
            params = {}

        params, missing_file = drop_invented_paths(text, params)

        # Sin archivo, run_sandbox prueba el cambio pendiente.
        if action == "run_sandbox":
            return self.run_sandbox(params)

        # Ruta inventada: si el mensaje habla de un archivo se pide la ruta;
        # si no ("explica qué es una closure"), es conversación normal.
        if missing_file:
            return MISSING_FILE_MESSAGE if FILE_WORDS.search(text) else None

        handler = self.HANDLERS.get(action)

        if handler:
            return getattr(self, handler)(text, params)

        if action == "smart_refactor":
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

            prompt = f"""
Actúa como Senior Software Engineer.

El usuario quiere refactorizar este archivo.

Solicitud:
{request}

Archivo:
{file_path}

Contenido actual:
{content}

Hallazgos estáticos:
{static_findings}

Objetivo:
Mejorar claridad, mantenibilidad, estructura y estilo SIN cambiar el comportamiento.

Responde EXACTAMENTE con:

FILE_PATH:
{file_path}

CODE:
contenido completo del archivo refactorizado

EXPLANATION:
explicación breve de los cambios

Reglas:
- No uses markdown.
- No uses triple backticks.
- No pongas ```python.
- Conserva el comportamiento actual.
- No agregues dependencias innecesarias.
- Solo puedes importar: {self.import_policy(file_path).describe()}. No inventes ni agregues otras librerías.
- No elimines funciones públicas.
- No cambies nombres públicos salvo que el usuario lo pida.
- Si el archivo ya está bien, conserva el contenido y explica que no se requieren cambios importantes.

Reglas estrictas de refactor:
- No cambies returns por exceptions.
- No cambies exceptions por returns.
- No cambies prints por raises.
- No cambies valores de retorno.
- No cambies el comportamiento observable.
- Solo puedes cambiar formato, nombres internos, comentarios, estructura interna o simplificar lógica equivalente.
"""

            response = self.provider_router.ask(prompt)

            parsed = parse_code_response(response)

            if not parsed:
                return f"No pude extraer CODE.\n\nRespuesta recibida:\n{response}"

            # Se ignora el FILE_PATH que devuelva el LLM: el refactor siempre
            # se aplica al archivo que pidió el usuario.
            _, code, explanation = parsed

            def normalize_code(value):
                return "\n".join(
                    line.rstrip()
                    for line in value.strip().splitlines()
                )

            if normalize_code(content) == normalize_code(code):
                return f"No se requieren cambios reales en {file_path}."

            code, explanation, import_error = self.check_generated_imports(
                prompt, file_path, code, explanation
            )

            if import_error:
                return import_error

            forbidden_changes = [
                ("return None", "raise "),
                ("print(", "raise "),
            ]

            for old_pattern, new_pattern in forbidden_changes:

                if old_pattern in content and new_pattern in code:
                    return (
                        "Refactor rechazado automáticamente.\n\n"
                        "El cambio modifica el comportamiento observable "
                        "del programa (prints/returns/excepciones)."
                    )

            apply_tool = self.tool_registry.get_apply_changes_tool()

            diff_message = apply_tool.propose_change(
                file_path=file_path,
                new_content=code
            )

            return f"""
{explanation}

{diff_message}
"""
        
        if action == "generate_code":
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

            prompt = f"""
Actúa como Senior Python Developer.

El usuario quiere generar o corregir código para este proyecto.

Solicitud:
{request}

Archivo objetivo detectado:
{target_file}

Contenido actual del archivo objetivo:
{target_file_content}

Contexto del proyecto:
{project_context}

Diagnóstico previo disponible:
{debug_context}

Responde EXACTAMENTE con este formato:

FILE_PATH:
ruta/del/archivo.py

CODE:
contenido completo del archivo final

EXPLANATION:
explicación breve del cambio

IMPORTANTE:
- No traduzcas FILE_PATH.
- No traduzcas CODE.
- No traduzcas EXPLANATION.
- Usa exactamente esas tres etiquetas.
- No uses markdown.
- No uses triple backticks.
- No pongas ```python.
- CODE debe contener el archivo completo final.
- Si modificas un archivo existente, conserva sus imports, clases y funciones que no deban cambiarse.
- Si usas re, agrega import re.
- Si creas una función nueva, incluye todos los imports necesarios.
- Solo puedes importar: {self.import_policy(target_file).describe()}. No inventes ni agregues otras librerías.
- Si el usuario menciona un archivo .py específico, usa ese archivo como FILE_PATH.
- Si el usuario quiere crear una tool nueva, usa una ruta dentro de tools/.
- Si el usuario quiere modificar Brain, usa core/brain.py.
- Si el usuario quiere modificar IntentEngine, usa core/intent_engine.py.
- Si no estás seguro de la ruta, usa pruebas/generated_code.py.
- Si solo propones cambios menores de tipado, formato o comentarios, dilo explícitamente como "cambio menor".
"""

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

            forbidden_changes = [
                ("return None", "raise "),
                ("print(", "raise "),
            ]

            old_content = ""

            if Path(file_path).exists():
                old_content = Path(file_path).read_text(encoding="utf-8").strip()

            new_code = code

            for old_pattern, new_pattern in forbidden_changes:

                if old_pattern in old_content and new_pattern in new_code:
                    return (
                        "Refactor rechazado automáticamente.\n\n"
                        "El cambio modifica el comportamiento observable "
                        "del programa (prints/returns/excepciones)."
                    )

            if "re." in code and "import re" not in code:
                code = "import re\n\n" + code

            if not file_path or not code:
                return f"Faltan datos para proponer el cambio.\n\nRespuesta recibida:\n{response}"
            
            if is_protected_file(file_path):
                return f"""
            Asia generó un cambio para un archivo protegido:

            {file_path}

            Por seguridad no lo aplicaré automáticamente todavía.
            Primero revisa el cambio manualmente o pide modificar un archivo menos crítico.
            """

            if old_content == code.strip():
                return f"No se requieren cambios en {file_path}."

            apply_tool = self.tool_registry.get_apply_changes_tool()

            diff_message = apply_tool.propose_change(
                file_path=file_path,
                new_content=code
            )

            return f"""
{explanation}

{diff_message}
"""
        
        if action == "apply_change":
            apply_tool = self.tool_registry.get_apply_changes_tool()
            return apply_tool.apply_pending_change()

        if action == "cancel_change":
            apply_tool = self.tool_registry.get_apply_changes_tool()
            return apply_tool.cancel_pending_change()
        
        if action == "show_pending_change":
            apply_tool = self.tool_registry.get_apply_changes_tool()
            return apply_tool.show_pending_change()

        if action in [
            "open_app",
            "create_file",
            "read_file",
            "list_folder",
            "append_file",
            "search_files",
            "search_text",
            "read_file_preview"
        ]:
            return self.tool_registry.execute(action, **params)

        # "chat" o acción no reconocida: conversación normal. El launcher la
        # envía a provider_router.chat (con memoria, historial y streaming).
        return None