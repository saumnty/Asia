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
from core.actions.sandbox import RUN_CANCEL_PHRASES, RUN_CONFIRM_PHRASES, SandboxActions, normalized_command
from core.actions.review import ReviewActions, wants_synthesis, wants_unverified  # noqa: F401
from tools.sandbox import PendingRun
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

# Acciones que trabajan sobre un archivo y sin file_path piden la ruta.
FILE_ACTIONS = {
    "summarize_file", "explain_file", "review_file", "review_file_deep",
    "smart_refactor", "read_file", "read_file_preview", "append_file",
}


def is_multiline(text: str) -> bool:
    """Dos o más líneas con texto: casi siempre código pegado sin <<.

    En código, FILE_WORDS ve nombres de archivo en "self.x" o "df.loc", y
    pedir la ruta no tiene sentido: el contenido ya está en el mensaje.
    """
    return sum(1 for line in text.splitlines() if line.strip()) >= 2


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


# Frases exactas (en minúsculas, sin puntuación final) que no necesitan al
# IntentEngine: son comandos fijos y una mala clasificación aplicaría o
# descartaría un cambio por error. "confirmar ejecución" y "cancelar
# ejecución" están en core/actions/sandbox.py; "salir" lo atiende el launcher.
SHORTCUT_ACTIONS = {
    **dict.fromkeys(
        ["confirmar cambio", "confirmar el cambio", "confirma el cambio",
         "aplicar cambio", "aplicar el cambio", "aplica el cambio"],
        "apply_change"
    ),
    **dict.fromkeys(
        ["cancelar cambio", "cancelar el cambio", "cancela el cambio"],
        "cancel_change"
    ),
    **dict.fromkeys(
        ["muestra el cambio pendiente", "mostrar el cambio pendiente", "mostrar cambio pendiente",
         "ver el cambio pendiente", "ver cambio pendiente", "cambio pendiente"],
        "show_pending_change"
    ),
}


class Brain(MemoryActions, ExploreActions, ReviewActions, CodeActions, SandboxActions):
    # Acción del IntentEngine -> método que la atiende (ver core/actions).
    HANDLERS = {
        **MemoryActions.HANDLERS,
        **ExploreActions.HANDLERS,
        **ReviewActions.HANDLERS,
        **CodeActions.HANDLERS,
        **SandboxActions.HANDLERS,
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

        # Comandos fijos: texto exacto, sin pasar por el IntentEngine.
        shortcut = SHORTCUT_ACTIONS.get(command)

        if shortcut:
            return getattr(self, self.HANDLERS[shortcut])(text, {})

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
            return self.handle_run_sandbox(text, params)

        # Varias líneas sin ruta válida: es texto pegado para el chat, no un
        # archivo que falte.
        if is_multiline(text) and (missing_file or action in FILE_ACTIONS and not params.get("file_path")):
            return None

        # Ruta inventada: si el mensaje (corto) habla de un archivo se pide la
        # ruta; si no ("explica qué es una closure"), es conversación normal.
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