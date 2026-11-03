"""Precarga anticipada del modelo de código mientras se escribe un mensaje que claramente va a él.

Con la estrategia B (qwen3 para el IntentEngine y la charla, el 7B para
código, /buscar y revisiones), pasar de charla a una acción recargaba el 7B
(~8,5 s). Si lo que se está escribiendo lleva @archivo, /buscar o un verbo de
acción con un archivo, carpeta o proyecto, el 7B empieza a cargarse en un
hilo, sin bloquear la entrada.

En 4 GB de VRAM qwen3 y el 7B no caben a la vez: si la intención de ese
mensaje fuera a qwen3, Ollama lo recargaría y el 7B otra vez después. Por eso
la intención de ese mensaje la hace el modelo ya precargado (take()).
"""
import re
import threading

from core.fast_chat import CODE_LIKE
from core.model_selection import model_for
from providers.ollama_models import full_name

SETTING = "ollama_early_load"

ATTACHMENT = re.compile(r"(^|\s)@\S")
SEARCH = re.compile(r"^\s*/buscar\b", re.IGNORECASE)
ACTION_VERB = re.compile(
    r"\b(revis|explic|gener|refactoriz|corrig|arregl|resum|analiz|depur|audit)\w*", re.IGNORECASE
)
# Con un verbo de acción hace falta algo sobre qué actuar: "explica qué es una closure" es charla.
TARGET = re.compile(r"\b(archivo|fichero|proyecto|carpeta|c[oó]digo|funci[oó]n|clase|m[oó]dulo|bug)\b", re.IGNORECASE)


def goes_to_code_model(text: str) -> bool:
    if ATTACHMENT.search(text) or SEARCH.match(text):
        return True

    return bool(ACTION_VERB.search(text)) and bool(TARGET.search(text) or CODE_LIKE.search(text))


class EarlyLoad:
    """typing(texto) mientras se escribe; take() al procesar el mensaje."""

    def __init__(self, settings, load):
        # load(modelo): carga el modelo en Ollama sin prompt (IntentEngine.preload).
        self.settings = settings
        self.load = load
        self.started = None
        self.thread = None
        self.lock = threading.Lock()

    def model(self):
        """El modelo de código si es otro que el del IntentEngine; si no, None (nada que adelantar)."""
        code = model_for(self.settings, "code")

        if not self.settings.get(SETTING, True) or full_name(code) == full_name(self.settings.get("intent_model")):
            return None

        return code

    def typing(self, text: str):
        with self.lock:
            if self.started or not text or not goes_to_code_model(text):
                return

            model = self.model()

            if model is None:
                return

            self.started = model
            self.thread = threading.Thread(target=self.load, args=(model,), name="asia-early-load", daemon=True)
            self.thread.start()

    def take(self):
        """El modelo precargado para este mensaje (o None), y vuelve a empezar para el siguiente."""
        with self.lock:
            model, self.started = self.started, None
            return model
