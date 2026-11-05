from memory.memory_manager import MemoryManager
from core.intent_engine import IntentEngine
from tools.tool_registry import ToolRegistry
from providers.provider_router import ProviderRouter
from memory.project_memory import ProjectMemory
from config.settings_manager import SettingsManager
from core.actions.code import CodeActions
from core.actions.explore import ExploreActions
from core.actions.library import LibraryActions
from core.actions.memory import MemoryActions, whole_memory_text
from core.actions.models import ModelActions, model_command
from core.actions.confidential import ConfidentialActions, confidential_command
from core.actions.tasks import TaskActions
from core.actions.timing import TimingActions, timing_command
from core.actions.voice import VoiceActions, voice_command
from core.actions.affect import AffectActions, affect_command
from core import timing
from core.commands import is_launcher_command, options_text, resolve as resolve_command, unknown_message as unknown_command
from core.session import Session
from core.chat_memory import asks_whole_memory, is_recall
from core.early_load import EarlyLoad
from core.fast_chat import is_clear_chat
from core.fixed_intents import fixed_intent
from core.reflection import asks_previous_session, load_summary, previous_session_text
from core.recent_facts import DEFAULT_KNOWN_UNTIL, asks_recent_fact, is_affirmative, offer_text
from tools.app_tool import AppTool
from core.provenance import USUARIO, Fragment, current_fragments, request_sources
# wants_synthesis y wants_unverified se importan desde aquí en las pruebas.
from core.actions.sandbox import RUN_CANCEL_PHRASES, RUN_CONFIRM_PHRASES, SandboxActions, normalized_command
from core.actions.review import ReviewActions, wants_synthesis, wants_unverified  # noqa: F401
from tools.sandbox import PendingRun
from pathlib import Path
import re
import threading


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

# Lo atiende el modo interactivo (launcher): usan el micrófono o preguntan uno por uno.
CALIBRATE_ONLY_INTERACTIVE = "La calibración de la voz es del modo interactivo: abre Asia y escribe /calibrar voz."
REVIEW_ONLY_INTERACTIVE = "La revisión de la memoria es del modo interactivo: abre Asia y escribe /revisar memoria."

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


class Brain(MemoryActions, ExploreActions, ReviewActions, CodeActions, SandboxActions, ModelActions, ConfidentialActions,
            TimingActions, VoiceActions, TaskActions, LibraryActions, AffectActions):
    # Acción del IntentEngine -> método que la atiende (ver core/actions).
    HANDLERS = {
        **MemoryActions.HANDLERS,
        **ExploreActions.HANDLERS,
        **ReviewActions.HANDLERS,
        **CodeActions.HANDLERS,
        **SandboxActions.HANDLERS,
        **TaskActions.HANDLERS,
        **LibraryActions.HANDLERS,
    }

    def __init__(self):
        self.memory = MemoryManager()
        self.intent_engine = IntentEngine()
        self.provider_router = ProviderRouter()
        self.tool_registry = ToolRegistry(self.provider_router)
        self.project_memory = ProjectMemory()
        self.settings = SettingsManager()
        # El launcher le pasa lo que se va escribiendo (core/early_load.py).
        self.early_load = EarlyLoad(self.settings, self.intent_engine.preload)
        # El de la sesión anterior: durante esta, el archivo se va reescribiendo con la actual.
        self.previous_session = load_summary()
        self.last_debug_report = None
        self.pending_run = PendingRun()
        # Qué hizo el último mensaje (resumen de la sesión): una acción, "chat" o
        # None si fue un comando de sesión.
        self.last_action = None

    def offer_wikipedia(self, text):
        """No lo sé; ¿lo busco en Wikipedia? El "sí" del mensaje siguiente lo busca."""
        from core.rag.library import ENCYCLOPEDIA, Library

        source = next((s for s in Library().all() if s.kind == ENCYCLOPEDIA and s.name.lower() == "wikipedia"), None)
        self.last_action = "chat"
        self.offered_search = text.strip().rstrip("?¿ ").lstrip("¿") if source else None
        return offer_text(source)

    def limit(self, name):
        """Límite de contexto configurado en context_limits (settings)."""
        return self.settings.get("context_limits")[name]

    def preload_in_background(self):
        """Carga el modelo del IntentEngine en un hilo, sin bloquear la entrada."""
        preload = getattr(self.intent_engine, "preload", None)

        if preload is None:
            return None

        thread = threading.Thread(target=preload, name="asia-preload", daemon=True)
        thread.start()
        return thread

    def app_names(self):
        """Nombres de apps conocidas: con uno en el mensaje decide el IntentEngine."""
        try:
            return list(AppTool().known_apps())
        except Exception:
            return []

    def active_project(self):
        return self.settings.get("active_project").lower().strip()

    def process(self, text):
        """Ejecuta la acción detectada en el texto.

        Devuelve None si el mensaje es conversación normal (acción "chat" o
        no reconocida); en ese caso quien llama debe usar provider_router.chat.

        Lo que lean las acciones queda anotado con su procedencia
        (core/provenance.py); si el launcher ya abrió el registro, se suma.
        """
        with request_sources(Fragment(USUARIO, text)):
            answer = self.process_labeled(text)

            # El resultado de una acción queda en el historial de la charla: tras
            # /buscar, "¿y eso para qué sirve?" no sabía de qué se hablaba.
            remember = getattr(getattr(self, "provider_router", None), "remember_action", None)

            if remember and isinstance(answer, str) and answer.strip() and self.last_action not in (None, "chat"):
                remember(text, answer, current_fragments())

            return answer

    def process_labeled(self, text):
        self.last_action = None
        # Si mientras se escribía empezó a cargarse el modelo de código, la
        # intención de este mensaje va con él (core/early_load.py).
        early = getattr(self, "early_load", None)
        preloaded = early.take() if early else None

        # Comandos "/" (core/commands.py): se traducen a su frase, que se
        # atiende abajo como siempre.
        slash = resolve_command(text)

        if slash:
            if slash.unknown:
                return unknown_command(slash.unknown)

            if slash.command.special == "opciones":
                return options_text()

            if slash.command.special == "calibrar":
                return CALIBRATE_ONLY_INTERACTIVE

            if slash.command.special in ("revisar_memoria", "revisar_memoria_a_fondo"):
                return REVIEW_ONLY_INTERACTIVE

            if slash.command.action:
                action, param = slash.command.action
                return getattr(self, self.HANDLERS[action])(text, {param: slash.arg})

            text = slash.phrase or text

        if is_launcher_command(text, "calibrar"):
            return CALIBRATE_ONLY_INTERACTIVE

        if is_launcher_command(text, "revisar_memoria") or is_launcher_command(text, "revisar_memoria_a_fondo"):
            return REVIEW_ONLY_INTERACTIVE

        if is_launcher_command(text, "carpeta"):
            return f"Carpeta desde donde llamaste a Asia: {Session.get_user_cwd()}"

        command = normalized_command(text)

        # "¿Lo busco en Wikipedia?" y la respuesta es "sí" (core/recent_facts.py).
        offered, self.offered_search = getattr(self, "offered_search", None), None

        if offered and is_affirmative(text):
            return self.handle_search_project_rag(text, {"question": f"{offered} en wikipedia"})

        # Comandos fijos: texto exacto, sin pasar por el IntentEngine.
        shortcut = SHORTCUT_ACTIONS.get(command)

        if shortcut:
            return getattr(self, self.HANDLERS[shortcut])(text, {})

        if command in RUN_CONFIRM_PHRASES:
            return self.confirm_run()

        if command in RUN_CANCEL_PHRASES:
            return self.cancel_run()

        # Ver o cambiar el modelo (core/actions/models.py): texto fijo, sin LLM.
        model_cmd = model_command(text)

        if model_cmd:
            return self.handle_model_command(*model_cmd)

        # Modo confidencial (core/actions/confidential.py): texto fijo, sin LLM.
        confidential_cmd = confidential_command(text)

        if confidential_cmd:
            return self.handle_confidential_command(confidential_cmd)

        voice_cmd = voice_command(text)

        if voice_cmd:
            return self.handle_voice_command(voice_cmd)

        # Núcleo afectivo (core/actions/affect.py): /estado, /afecto y la corrección del usuario.
        affect_cmd = affect_command(text, getattr(self, "settings", None))

        if affect_cmd:
            return self.handle_affect_command(affect_cmd, text)

        timing_cmd = timing_command(text)

        if timing_cmd:
            return self.handle_timing_command(timing_cmd)

        # Charla clara (saludo, gracias, "qué es X"): directo al chat, sin
        # los ~20 s del IntentEngine (core/fast_chat.py).
        # Un hecho concreto posterior a lo que sabe el modelo: no se contesta de memoria.
        settings = getattr(self, "settings", None)
        known_until = (settings.get("knowledge_until_year") if settings else None) or DEFAULT_KNOWN_UNTIL

        if asks_recent_fact(text, known_until):
            return self.offer_wikipedia(text)

        # "¿Qué hicimos en la sesión anterior?": el resumen de sesión (fase R), no
        # el del proyecto, que iba por ask_project_memory y podía ser de hace meses.
        if asks_whole_memory(text) and hasattr(getattr(self, "memory", None), "load"):
            self.last_action = "recall"
            return whole_memory_text(self.memory.load())

        if asks_previous_session(text):
            self.last_action = "chat"
            return previous_session_text(getattr(self, "previous_session", None) or load_summary())

        if is_clear_chat(text, self.app_names()):
            self.last_action = "chat"
            return None

        # Órdenes inequívocas ("abre X", "muestra el proyecto activo"): sin
        # IntentEngine (core/fixed_intents.py).
        intent = fixed_intent(text)

        if intent is None:
            with timing.intent_stage():
                intent = self.intent_engine.detect(text, model=preloaded) if preloaded else self.intent_engine.detect(text)

        action = intent.get("action")
        params = intent.get("params")

        # qwen3 mandaba "¿cuál es tu color favorito?" a recall (y contestaba
        # "color_favorito: amarillo") y "¿qué sabes de mí?" a recall del nombre.
        if action == "recall" and not is_recall(text):
            action = "chat"

        self.last_action = action if action in self.HANDLERS or action in DIRECT_TOOL_ACTIONS else "chat"

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