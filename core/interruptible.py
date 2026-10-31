"""Llamadas al modelo que Ctrl+C corta al momento.

En Windows, Ctrl+C no interrumpe una espera de red: Python solo atiende la
señal cuando llega el siguiente dato, y mientras el modelo carga o procesa el
prompt no llega ninguno (65 s medidos en CPU). Por eso la llamada va en otro hilo
y el hilo principal espera en intervalos cortos: ahí Ctrl+C actúa enseguida.

Los trozos del streaming vuelven al hilo principal, que los imprime y los lee.
cancel() cierra la conexión: Ollama deja de generar y no retrasa el mensaje
siguiente. Fuera del hilo principal no hay Ctrl+C que atender y se llama directo.
"""
import contextvars
import queue
import threading

POLL_SECONDS = 0.05
CHUNK, DONE, FAILED = "trozo", "fin", "error"


def call(work, on_chunk=None, cancel=None):
    """Devuelve work(emit), o propaga su error. emit(trozo) llega a on_chunk; sin on_chunk, emit es None."""
    if threading.current_thread() is not threading.main_thread():
        return work(on_chunk)

    events = queue.SimpleQueue()
    # La medición (--timing) y la procedencia viven en ContextVars.
    context = contextvars.copy_context()

    def emit(chunk):
        events.put((CHUNK, chunk))

    def run():
        try:
            events.put((DONE, context.run(work, emit if on_chunk else None)))
        except BaseException as e:
            events.put((FAILED, e))

    threading.Thread(target=run, name="asia-modelo", daemon=True).start()

    # El bucle va en su propia función: en Python 3.11 una señal puede caer en el
    # salto del "continue", fuera del try de esta misma función.
    try:
        return wait_for(events, on_chunk)
    except KeyboardInterrupt:
        if cancel is not None:
            cancel()

        raise


def wait_for(events, on_chunk):
    while True:
        try:
            kind, value = events.get(timeout=POLL_SECONDS)
        except queue.Empty:
            continue

        if kind == DONE:
            return value

        if kind == FAILED:
            raise value

        on_chunk(value)
