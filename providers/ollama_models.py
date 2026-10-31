"""Un solo modelo de Ollama en memoria a la vez (ollama_one_model_at_a_time).

Con 4 GB de VRAM y poca RAM libre, dos modelos cargados hacen que Ollama
reparta capas en la CPU o use swap. Antes de cada llamada se descargan los
demás modelos cargados (keep_alive=0). Cambiar de modelo cuesta una recarga
(segundos con un 7B): por eso el chat mantiene su modelo mientras puede
(ver core/model_selection.py).
"""


import re
import threading


def full_name(model: str) -> str:
    """"nomic-embed-text" y "nomic-embed-text:latest" son el mismo modelo."""
    return model if ":" in model else f"{model}:latest"


def unload_others(client, model: str, settings) -> list[str]:
    """Descarga de Ollama los modelos cargados distintos de model.

    Devuelve los que descargó. Si Ollama no responde, no hace nada: la
    llamada siguiente mostrará el error.
    """
    if not settings.get("ollama_one_model_at_a_time", True):
        return []

    try:
        loaded = [m.model for m in client.ps().models]
    except Exception:
        return []

    unloaded = []

    for name in loaded:
        if full_name(name) == full_name(model):
            continue

        try:
            # Una llamada sin prompt y con keep_alive=0 descarga el modelo.
            client.generate(model=name, keep_alive=0)
            unloaded.append(name)
        except Exception:
            pass

    return unloaded


# --- Modo de razonamiento (qwen3 y otros con la capacidad "thinking") -------
#
# think solo se envía a los modelos que lo declaran en su ficha (ollama
# show): a uno sin esa capacidad Ollama le rechaza la llamada. Con think
# activo, Ollama separa el razonamiento en message.thinking; por si una
# plantilla lo deja en el contenido, también se quita <think>...</think>.

THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
THINK_OPEN, THINK_CLOSE = "<think>", "</think>"

_thinking_capable = {}


def supports_thinking(client, model: str) -> bool:
    key = full_name(model)

    if key not in _thinking_capable:
        try:
            capabilities = client.show(model).capabilities or []
        except Exception:
            capabilities = []

        _thinking_capable[key] = "thinking" in capabilities

    return _thinking_capable[key]


def think_kwargs(client, model: str, enabled: bool) -> dict:
    """{"think": enabled} si el modelo razona; {} si no tiene esa capacidad."""
    return {"think": bool(enabled)} if supports_thinking(client, model) else {}


def strip_think(text: str) -> str:
    return THINK_BLOCK.sub("", text)


class ThinkFilter:
    """Quita <think>...</think> de una respuesta en streaming.

    Las etiquetas pueden llegar partidas entre fragmentos: se retiene el
    final de cada fragmento hasta saber si es el inicio de una etiqueta.
    """

    def __init__(self):
        self.buffer = ""
        self.inside = False

    def feed(self, chunk: str) -> str:
        self.buffer += chunk
        visible = ""

        while True:
            if not self.inside:
                start = self.buffer.find(THINK_OPEN)

                if start == -1:
                    keep = len(THINK_OPEN) - 1
                    visible += self.buffer[:-keep] if len(self.buffer) > keep else ""
                    self.buffer = self.buffer[-keep:] if len(self.buffer) > keep else self.buffer
                    return visible

                visible += self.buffer[:start]
                self.buffer = self.buffer[start + len(THINK_OPEN):]
                self.inside = True
            else:
                end = self.buffer.find(THINK_CLOSE)

                if end == -1:
                    self.buffer = self.buffer[-(len(THINK_CLOSE) - 1):]
                    return visible

                self.buffer = self.buffer[end + len(THINK_CLOSE):].lstrip()
                self.inside = False

    def flush(self) -> str:
        rest = "" if self.inside else self.buffer
        self.buffer = ""
        return rest


def drop_client(owner):
    """Cierra la conexión del cliente de owner (si es uno real) para que el próximo uso abra otra.

    En un hilo aparte: cerrar la conexión nunca debe retrasar a quien canceló.
    """
    connection = getattr(owner._client, "_client", None)

    if connection is None:
        return

    owner._client = None
    threading.Thread(target=connection.close, name="asia-cierre", daemon=True).start()


def installed_models(host=None):
    """Modelos descargados en Ollama, o None si Ollama no responde."""
    try:
        import ollama

        return [m.model for m in ollama.Client(host=host).list().models]
    except Exception:
        return None


def is_installed(model: str, installed) -> bool:
    return full_name(model) in {full_name(m) for m in installed}
