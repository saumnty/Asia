"""Reflexión dentro de la sesión (fase R).

El resumen de la sesión se genera al cerrarla y se guarda en
data/reflexion/ultima_sesion.json: abrir Asia solo lee ese archivo y los
pendientes, sin esperar al modelo.
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


def summarize(log: SessionLog, complete, timeout: float):
    """(resumen, origen). complete(messages) es el modelo local; None o un fallo: resumen simple."""
    if complete is not None:
        messages = [{"role": "user", "content": prompts.session_summary(session_description(log))}]
        text = clean_summary(within_timeout(lambda: complete(messages), timeout))

        if text:
            return text, "modelo"

    return simple_summary(log), "simple"


def local_model(brain):
    """complete(messages) con el Ollama de esta máquina; None si no lo hay.

    La sesión incluye lo leído de archivos: el resumen nunca va a un proveedor
    externo, ni a un Ollama fuera de esta máquina.
    """
    router = getattr(brain, "provider_router", None)
    settings = getattr(brain, "settings", None)

    if not hasattr(router, "get_provider") or ollama_is_external(settings):
        return None

    limits = (settings.get("answer_limits") or {}).get("session_summary") or {}
    tokens = limits.get("tokens", DEFAULT_SUMMARY_TOKENS)

    return lambda messages: router.get_provider("ollama").complete(messages, max_tokens=tokens)


def close_session(brain, log: SessionLog):
    """Al salir: genera el resumen, lo guarda para la próxima vez y lo muestra. Nunca impide salir."""
    if not log:
        return None

    timeout = (brain.settings.get("reflection") or {}).get("summary_timeout_s", DEFAULT_SUMMARY_TIMEOUT)

    try:
        text, source = summarize(log, local_model(brain), timeout)
        save_summary(text, source, len(log))
    except Exception as e:
        print(f"No pude guardar el resumen de la sesión: {e}", file=sys.stderr)
        return None

    return text
