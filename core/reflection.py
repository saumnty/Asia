"""Reflexión dentro de la sesión (fase R).

El resumen de la sesión se actualiza en segundo plano tras cada respuesta y se
guarda en data/reflexion/ultima_sesion.json: abrir Asia solo lee ese archivo y
los pendientes, y salir no espera si ya está al día.
"""
import json
import re
import sys
import threading
import time
from collections import Counter
from datetime import datetime

from core import paths, prompts
from core.atomic_write import write_json_atomic
from core.audit import recent_entries
from core.confidential import ollama_is_external
from core.tasks import TaskList, numbered

SENTENCE_END = re.compile(r"(?<=[^\d\s][.!?…])\s+")
CUT_NOTICE = re.compile(r"\s*\[Respuesta recortada[^\]]*\]\s*$")
OPENING_SENTENCES = 2
SUMMARY_SENTENCES = 3
CHAT = "chat"

# De cada sesión van al modelo los últimos turnos, y de cada turno, el principio.
MAX_TURNS = 30
MAX_TURN_CHARS = 200
AUDIT_ENTRIES = 200

# Los mismos que reflection y answer_limits en config/defaults.json, por si falta la clave.
DEFAULT_SUMMARY_TIMEOUT = 30
DEFAULT_SUMMARY_TOKENS = 120
DEFAULT_SUMMARY_IDLE = 3

WAIT_STEP = 0.1
SAVING_NOTICE = "Guardando resumen… (Ctrl+C para saltar)"


def first_sentences(text: str, count: int) -> str:
    return " ".join(SENTENCE_END.split(text.strip())[:count])


def save_summary(text: str, source: str, messages: int):
    """source: "modelo" o "simple" (sin modelo, ver simple_summary)."""
    paths.SESSION_SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(paths.SESSION_SUMMARY_FILE, {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "resumen": text,
        "origen": source,
        "mensajes": messages,
    })


def load_summary():
    """El resumen guardado, o None si no hay o no se puede leer."""
    try:
        return json.loads(paths.SESSION_SUMMARY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def opening_text() -> str:
    """Lo que se muestra al abrir Asia; "" si no hay nada."""
    parts = []
    summary = load_summary()

    if summary and summary.get("resumen"):
        date = summary.get("fecha", "").replace("T", " ")[:16]
        parts.append(f"Sesión anterior ({date}): {first_sentences(summary['resumen'], OPENING_SENTENCES)}")

    try:
        tasks = TaskList().open_tasks()
    except (OSError, ValueError):
        tasks = []

    if tasks:
        parts.append(f"Pendientes:\n{numbered(tasks)}")

    return "\n".join(parts)


# --- Lo que se hizo en la sesión -----------------------------------------------

class SessionLog:
    """Los mensajes de esta sesión, en memoria hasta cerrarla."""

    def __init__(self):
        self.started = datetime.now()
        self.turns = []

    def __len__(self):
        return len(self.turns)

    def add(self, text: str, answer: str, action: str):
        self.turns.append({
            "texto": shorten(text),
            "respuesta": shorten(answer) if answer else "(sin respuesta o cortada)",
            "accion": action,
        })


def shorten(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_TURN_CHARS else f"{text[:MAX_TURN_CHARS]}…"


def external_sends(log: SessionLog) -> int:
    """Envíos a proveedores externos de esta sesión, según la bitácora."""
    started = log.started.isoformat(timespec="seconds")
    return sum(entry["fecha"] >= started for entry in recent_entries(AUDIT_ENTRIES))


def session_description(log: SessionLog) -> str:
    """La sesión como texto para el modelo: de cada turno, lo pedido y el principio de la respuesta."""
    lines = []

    for turn in log.turns[-MAX_TURNS:]:
        action = "" if turn["accion"] == CHAT else f" (acción {turn['accion']})"
        lines.append(f"- Usuario: {turn['texto']}\n  Asia{action}: {turn['respuesta']}")

    sends = external_sends(log)

    if sends:
        lines.append(f"- Envíos a proveedores externos en la sesión: {sends}.")

    return "\n".join(lines)


def simple_summary(log: SessionLog) -> str:
    """Resumen sin modelo: la lista de acciones."""
    counts = Counter(turn["accion"] for turn in log.turns)
    actions = ", ".join(f"{'conversación' if a == CHAT else a} ({n})" for a, n in counts.most_common())
    sends = external_sends(log)
    extra = f" Envíos externos: {sends}." if sends else ""
    return f"Sesión de {len(log)} mensajes: {actions}.{extra}"


def clean_summary(text: str) -> str:
    """Sin el aviso de recorte ni la frase a medias que deja; como mucho SUMMARY_SENTENCES frases."""
    sentences = SENTENCE_END.split(CUT_NOTICE.sub("", text or "").strip())

    if CUT_NOTICE.search(text or "") and len(sentences) > 1:
        sentences = sentences[:-1]

    return " ".join(sentences[:SUMMARY_SENTENCES]).strip()


def within_timeout(call, timeout: float):
    """El resultado de call() o None si falla, no llega a tiempo o se pulsa Ctrl+C.

    Se espera en intervalos cortos porque en Windows Ctrl+C no interrumpe una
    espera larga. El hilo es daemon: si el modelo no responde, Asia sale igual.
    """
    results = []

    def run():
        try:
            results.append(call())
        except Exception:
            pass

    thread = threading.Thread(target=run, name="asia-resumen", daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout

    try:
        while thread.is_alive() and time.monotonic() < deadline:
            thread.join(0.1)
    except KeyboardInterrupt:
        return None

    return results[0] if results else None


class LocalModel:
    """El Ollama de esta máquina para el resumen: model(messages) y cancel()."""

    def __init__(self, router, tokens):
        self.router = router
        self.tokens = tokens

    def __call__(self, messages):
        return self.router.get_provider("ollama").complete(messages, max_tokens=self.tokens)

    def cancel(self):
        cancel = getattr(self.router.get_provider("ollama"), "cancel", None)

        if cancel is not None:
            cancel()


def local_model(brain):
    """El modelo local; None si no lo hay.

    La sesión incluye lo leído de archivos: el resumen nunca va a un proveedor
    externo, ni a un Ollama fuera de esta máquina.
    """
    router = getattr(brain, "provider_router", None)
    settings = getattr(brain, "settings", None)

    if not hasattr(router, "get_provider") or ollama_is_external(settings):
        return None

    limits = (settings.get("answer_limits") or {}).get("session_summary") or {}
    return LocalModel(router, limits.get("tokens", DEFAULT_SUMMARY_TOKENS))


class SessionSummarizer:
    """Mantiene el resumen al día en segundo plano, mientras el usuario lee.

    schedule() lanza un hilo que espera idle segundos y a que busy() sea falso,
    y resume la sesión con lo que había entonces. interrupt() lo cancela: el
    siguiente mensaje nunca compite con él. Cada resumen se guarda: al salir, si
    está al día, no hay nada que esperar.
    """

    def __init__(self, log: SessionLog, model=None, idle=DEFAULT_SUMMARY_IDLE, busy=lambda: False):
        self.log = log
        self.model = model
        self.idle = idle
        self.busy = busy
        self.text = None
        self.summarized = 0
        self.failed = None
        self.thread = None
        self.stopped = None
        self.calling = False
        self.hurry = threading.Event()
        self.lock = threading.Lock()

    @property
    def up_to_date(self) -> bool:
        return self.summarized == len(self.log)

    def schedule(self):
        """Si falta resumir algo y no hay un hilo en marcha, lo lanza."""
        pending = self.model is not None and not self.up_to_date and self.failed != len(self.log)

        if not pending or self.thread is not None and self.thread.is_alive():
            return

        messages = [{"role": "user", "content": prompts.session_summary(session_description(self.log))}]
        self.stopped = threading.Event()
        self.thread = threading.Thread(
            target=self.update, args=(self.stopped, len(self.log), messages), name="asia-resumen", daemon=True,
        )
        self.thread.start()

    def interrupt(self):
        """El usuario mandó algo: se cancela lo que esté en marcha (se retomará después)."""
        if self.thread is None:
            return

        self.stopped.set()

        if self.calling and hasattr(self.model, "cancel"):
            self.model.cancel()

        self.thread = None

    def wait_for_quiet(self, stopped) -> bool:
        """False si lo cancelaron mientras esperaba."""
        deadline = time.monotonic() + self.idle

        while not self.hurry.is_set():
            if stopped.is_set():
                return False

            if time.monotonic() >= deadline and not self.busy():
                break

            self.hurry.wait(WAIT_STEP)

        return not stopped.is_set()

    def update(self, stopped, turns, messages):
        if not self.wait_for_quiet(stopped):
            return

        self.calling = True

        try:
            text = clean_summary(self.model(messages))
        except Exception:
            text = ""
        finally:
            self.calling = False

        with self.lock:
            if stopped.is_set():
                return

            if not text:
                self.failed = turns
                return

            try:
                save_summary(text, "modelo", turns)
            except OSError:
                self.failed = turns
                return

            self.text = text
            self.summarized = turns

    def finish(self, timeout: float, notice=lambda: None):
        """Al salir: el resumen al día, esperándolo hasta timeout. None si no se consiguió."""
        if self.up_to_date:
            return self.text

        if self.model is None or self.failed == len(self.log):
            return None

        notice()
        self.hurry.set()
        self.schedule()
        deadline = time.monotonic() + timeout

        # Con sleep y no con join: Ctrl+C durante un join deja el hilo marcado
        # como terminado aunque siga vivo, y no se podría cancelar.
        try:
            while self.thread.is_alive() and time.monotonic() < deadline:
                time.sleep(WAIT_STEP)
        except KeyboardInterrupt:
            self.interrupt()
            return None

        if not self.up_to_date:
            self.interrupt()
            return None

        return self.text


def close_session(brain, log: SessionLog, summarizer: SessionSummarizer):
    """Al salir: el resumen de la sesión, guardado para la próxima vez. Nunca impide salir."""
    if not log:
        return None

    timeout = (brain.settings.get("reflection") or {}).get("summary_timeout_s", DEFAULT_SUMMARY_TIMEOUT)
    text = summarizer.finish(timeout, lambda: print(SAVING_NOTICE, file=sys.stderr, flush=True))

    if text:
        return text

    try:
        text = simple_summary(log)
        save_summary(text, "simple", len(log))
    except Exception as e:
        print(f"No pude guardar el resumen de la sesión: {e}", file=sys.stderr)
        return None

    return text
