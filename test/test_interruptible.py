"""Ctrl+C corta la llamada al modelo al momento, también sin datos en la conexión."""
import signal
import threading
import time

import pytest

import launcher
from core import interruptible, timing
from core.intent_engine import IntentEngine
from core.provenance import USUARIO, Fragment, current_fragments, request_sources
from providers.ollama_models import drop_client
from providers.ollama_provider import OllamaProvider
from test_confidencial import make_brain
from test_launcher import FakeBrain, reader


def press_ctrl_c_after(seconds):
    """Como la consola: Ctrl+C llega al proceso aunque el hilo principal esté esperando."""
    def press():
        time.sleep(seconds)
        signal.raise_signal(signal.SIGINT)

    thread = threading.Thread(target=press, daemon=True)
    thread.start()
    return thread


class Hanging:
    """Un proveedor que no devuelve nada hasta release: el modelo cargándose."""

    def __init__(self):
        self.release = threading.Event()
        self.cancelled = 0

    def complete(self, messages, **options):
        self.release.wait(10)
        return "tarde"

    def cancel(self):
        self.cancelled += 1
        self.release.set()


def test_devuelve_el_resultado_y_los_trozos_llegan_en_el_hilo_principal():
    threads, chunks = [], []

    def on_chunk(chunk):
        threads.append(threading.current_thread())
        chunks.append(chunk)

    def work(emit):
        for chunk in ("a", "b", "c"):
            emit(chunk)

        return "abc"

    assert interruptible.call(work, on_chunk) == "abc"
    assert chunks == ["a", "b", "c"] and threads == [threading.main_thread()] * 3


def test_sin_on_chunk_emit_es_none():
    assert interruptible.call(lambda emit: emit) is None


def test_el_error_de_la_llamada_llega_igual():
    def work(emit):
        raise ConnectionError("sin Ollama")

    with pytest.raises(ConnectionError, match="sin Ollama"):
        interruptible.call(work)


def test_ctrl_c_corta_sin_esperar_a_la_llamada_y_cancela():
    hanging = Hanging()
    press_ctrl_c_after(0.1)
    start = time.perf_counter()

    with pytest.raises(KeyboardInterrupt):
        interruptible.call(lambda emit: hanging.complete([]), cancel=hanging.cancel)

    assert time.perf_counter() - start < 2 and hanging.cancelled == 1


def test_un_ctrl_c_al_imprimir_un_trozo_tambien_cancela():
    cancelled = []

    def work(emit):
        emit("a")
        threading.Event().wait(5)

    def on_chunk(chunk):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        interruptible.call(work, on_chunk, lambda: cancelled.append(True))

    assert cancelled == [True]


def test_la_llamada_ve_la_medicion_y_la_procedencia():
    seen = {}

    def work(emit):
        seen["timings"] = timing.current()
        seen["labels"] = [f.label for f in current_fragments()]

    with timing.measure_request() as timings, request_sources(Fragment(USUARIO, "hola")):
        interruptible.call(work)

    assert seen == {"timings": timings, "labels": [USUARIO]}


def test_fuera_del_hilo_principal_llama_directo():
    threads = []

    def work(emit):
        threads.append(threading.current_thread())
        emit("a")

    def background():
        interruptible.call(work, lambda chunk: None)

    thread = threading.Thread(target=background)
    thread.start()
    thread.join()

    assert threads == [thread]


# --- En Asia -----------------------------------------------------------------------

def test_router_corta_al_proveedor_y_el_turno_no_queda_en_el_historial():
    brain = make_brain()
    hanging = Hanging()
    brain.provider_router.providers["ollama"] = hanging
    press_ctrl_c_after(0.1)
    start = time.perf_counter()

    with pytest.raises(KeyboardInterrupt), request_sources(Fragment(USUARIO, "hola")):
        brain.provider_router.chat("hola")

    assert time.perf_counter() - start < 2
    assert hanging.cancelled == 1 and brain.provider_router.history == []


def test_la_intencion_se_corta_al_momento():
    class HangingClient:
        def __init__(self):
            self.release = threading.Event()

        def ps(self):
            raise ConnectionError

        def show(self, model):
            raise ConnectionError

        def chat(self, **kwargs):
            self.release.wait(10)
            return {"message": {"content": "{}"}}

    engine = IntentEngine()
    engine.client = client = HangingClient()
    press_ctrl_c_after(0.1)
    start = time.perf_counter()

    with pytest.raises(KeyboardInterrupt):
        engine.detect("revisa todo")

    client.release.set()
    assert time.perf_counter() - start < 2


def test_el_modo_interactivo_vuelve_al_prompt(capsys):
    brain = FakeBrain(None, stream_output=True)
    hanging = Hanging()
    real = make_brain()
    real.provider_router.providers["ollama"] = hanging
    brain.provider_router = real.provider_router
    presses = iter([0.1])

    def read(prompt):
        delay = next(presses, None)

        if delay is None:
            return "salir"

        press_ctrl_c_after(delay)
        return "hola"

    launcher.interactive_mode(brain, read=read)

    out = capsys.readouterr()
    assert "(Respuesta cortada.)" in out.err and out.out.rstrip().endswith("Asia apagada.")


class RealClient:
    """Como ollama.Client: su conexión httpx está en _client."""

    def __init__(self):
        self.closed = threading.Event()
        self._client = self

    def close(self):
        self.closed.set()


@pytest.mark.parametrize("cls", [IntentEngine, OllamaProvider])
def test_cancelar_cierra_la_conexion_y_abre_otra_al_siguiente_uso(cls):
    owner = cls()
    owner.client = client = RealClient()

    owner.cancel()

    assert client.closed.wait(2) and owner._client is None


def test_cancelar_con_un_cliente_simulado_no_lo_pierde():
    owner = OllamaProvider()
    owner.client = fake = object()

    drop_client(owner)

    assert owner.client is fake
