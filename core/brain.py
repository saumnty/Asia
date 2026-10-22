from memory.memory_manager import MemoryManager
from core.intent_engine import IntentEngine
from tools.tool_registry import ToolRegistry
from providers.provider_router import ProviderRouter
from memory.project_memory import ProjectMemory
from config.settings_manager import SettingsManager
from core.actions.code import CodeActions
from core.actions.explore import ExploreActions
from core.actions.memory import MemoryActions
# wants_synthesis y wants_unverified se importan desde aquí en las pruebas.
from core.actions.review import ReviewActions, wants_synthesis, wants_unverified  # noqa: F401
from tools.sandbox import PendingRun, SandboxRunner, format_result, sandbox_import_problems
from pathlib import Path
import re


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


DIRECT_TOOL_ACTIONS = [
    "open_app",
    "create_file",
    "read_file",
    "list_folder",
    "append_file",
    "search_files",
    "search_text",
    "read_file_preview",
]


# Confirmar o cancelar una ejecución en el sandbox se reconoce por texto
# exacto, sin el IntentEngine: nada se ejecuta por una mala interpretación.
RUN_CONFIRM_PHRASES = {"confirmar ejecución", "confirmar ejecucion", "confirmo ejecución", "confirmo ejecucion"}
RUN_CANCEL_PHRASES = {"cancelar ejecución", "cancelar ejecucion"}


def normalized_command(text) -> str:
    return " ".join((text or "").lower().split()).strip(" .!¡")


class Brain(MemoryActions, ExploreActions, ReviewActions, CodeActions):
    # Acción del IntentEngine -> método que la atiende (ver core/actions).
    HANDLERS = {
        **MemoryActions.HANDLERS,
        **ExploreActions.HANDLERS,
        **ReviewActions.HANDLERS,
        **CodeActions.HANDLERS,
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

        # Acciones que van directo a una tool con los parámetros del IntentEngine.
        if action in DIRECT_TOOL_ACTIONS:
            return self.tool_registry.execute(action, **params)

        # "chat" o acción no reconocida: conversación normal. El launcher la
        # envía a provider_router.chat (con memoria, historial y streaming).
        return None