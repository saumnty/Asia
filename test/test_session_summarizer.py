"""El resumen de la sesión en segundo plano: se pone al día sin estorbar al siguiente mensaje."""
import signal
import threading
import time

import launcher
from core.reflection import SAVING_NOTICE, SessionLog, SessionSummarizer, load_summary
from test_launcher import FakeBrain
from test_reflection import Model, Router, brain_with


class Blocking(Model):
    """Tarda hasta cancel(): un resumen en marcha cuando llega el siguiente mensaje."""

    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled = 0

    def complete(self, messages, max_tokens=None, **options):
        self.calls.append((messages, max_tokens))
        self.started.set()
        self.release.wait(5)
        return self.answer

    def cancel(self):
        self.cancelled += 1
        self.release.set()


def log_with(turns=1):
    log = SessionLog()

    for _ in range(turns):
        log.add("hola", "Hola.", "chat")

    return log


def wait_until(condition, seconds=5):
    deadline = time.monotonic() + seconds

    while time.monotonic() < deadline and not condition():
        time.sleep(0.01)

    return condition()


def lines_after(summary_ready, lines):
    """Como un usuario: cada línea llega cuando ya se puede leer el resumen pendiente."""
    pending = iter(lines)

    def read(prompt):
        line = next(pending)

        if line == "salir":
            assert wait_until(summary_ready)

        return line

    return read


def test_se_actualiza_tras_cada_respuesta_y_al_salir_no_hay_espera(capsys):
    model = Model()
    brain = brain_with(model, reflection={"summary_idle_s": 0})

    read = lines_after(lambda: load_summary() is not None, ["hola", "salir"])
    launcher.interactive_mode(brain, read=read)

    out = capsys.readouterr()
    assert len(model.calls) == 1 and load_summary()["mensajes"] == 1
    assert SAVING_NOTICE not in out.err
    assert "Resumen de la sesión: Hablamos de grafos." in out.out


def test_no_arranca_si_el_usuario_sigue_escribiendo():
    model = Model()
    summarizer = SessionSummarizer(log_with(), model, idle=5)

    summarizer.schedule()
    time.sleep(0.2)
    summarizer.interrupt()

    assert model.calls == [] and not summarizer.up_to_date


def test_un_mensaje_nuevo_cancela_el_resumen_en_marcha():
    model = Blocking()
    summarizer = SessionSummarizer(log_with(), model, idle=0)

    summarizer.schedule()
    assert model.started.wait(5)
    summarizer.interrupt()

    assert model.cancelled == 1
    time.sleep(0.2)
    assert not summarizer.up_to_date and load_summary() is None


def test_en_el_modo_interactivo_el_mensaje_cancela_y_se_retoma_despues(capsys):
    model = Blocking()
    brain = brain_with(model, reflection={"summary_idle_s": 0})
    process = brain.process
    cancelled_when_processing = []

    def processing(text):
        cancelled_when_processing.append(model.cancelled)
        return process(text)

    brain.process = processing
    lines = iter(["primero", "segundo", "salir"])

    def read(prompt):
        line = next(lines)

        # "segundo" llega con el resumen de "primero" en marcha.
        if line == "segundo":
            assert model.started.wait(5)

        return line

    launcher.interactive_mode(brain, read=read)

    assert cancelled_when_processing == [0, 1]
    assert load_summary()["mensajes"] == 2


def test_espera_mientras_suena_la_lectura():
    model = Model()
    speaking = threading.Event()
    speaking.set()
    summarizer = SessionSummarizer(log_with(), model, idle=0, busy=speaking.is_set)

    summarizer.schedule()
    time.sleep(0.3)
    assert model.calls == []

    speaking.clear()
    assert wait_until(lambda: summarizer.up_to_date)


def test_con_otro_modelo_en_uso_no_lo_descarga():
    class Last(Router):
        last_request = (None, {"model": "qwen3:4b"})

    brain = FakeBrain("hecho", ollama_model="qwen2.5-coder:7b")
    brain.provider_router = Last(Model())

    assert launcher.other_model_in_use(brain) is True

    brain.provider_router.last_request = (None, {"model": "qwen2.5-coder:7b"})
    assert launcher.other_model_in_use(brain) is False

    brain.provider_router.last_request = None
    assert launcher.other_model_in_use(brain) is False


def test_al_salir_sin_estar_al_dia_lo_dice_y_lo_espera(capsys):
    model = Model()
    brain = brain_with(model, reflection={"summary_idle_s": 60})
    lines = iter(["hola", "salir"])

    launcher.interactive_mode(brain, read=lambda prompt: next(lines))

    out = capsys.readouterr()
    assert SAVING_NOTICE in out.err and SAVING_NOTICE == "Guardando resumen… (Ctrl+C para saltar)"
    assert load_summary()["origen"] == "modelo"


def test_al_salir_aprovecha_el_resumen_en_marcha():
    model = Blocking()
    summarizer = SessionSummarizer(log_with(), model, idle=0)
    summarizer.schedule()
    assert model.started.wait(5)

    threading.Timer(0.1, model.release.set).start()

    assert summarizer.finish(5) == model.answer and len(model.calls) == 1


def test_ctrl_c_al_salir_guarda_el_resumen_simple(capsys):
    model = Blocking()
    brain = brain_with(model, reflection={"summary_idle_s": 60})
    lines = iter(["hola", "salir"])

    def read(prompt):
        line = next(lines)

        if line == "salir":
            threading.Timer(0.2, lambda: signal.raise_signal(signal.SIGINT)).start()

        return line

    start = time.perf_counter()
    launcher.interactive_mode(brain, read=read)

    assert time.perf_counter() - start < 3
    assert load_summary()["origen"] == "simple" and model.cancelled == 1
    assert capsys.readouterr().out.rstrip().endswith("Asia apagada.")


def test_si_el_modelo_fallo_no_vuelve_a_intentar_hasta_la_siguiente_respuesta():
    model = Model(error=ConnectionError("sin Ollama"))
    log = log_with()
    summarizer = SessionSummarizer(log, model, idle=0)

    summarizer.schedule()
    assert wait_until(lambda: summarizer.failed == 1)
    summarizer.schedule()
    assert summarizer.finish(5) is None and len(model.calls) == 1

    log.add("otra", "Otra.", "chat")
    summarizer.schedule()
    assert wait_until(lambda: len(model.calls) == 2)


def test_guarda_lo_ultimo_que_se_resumio():
    model = Model()
    log = log_with()
    summarizer = SessionSummarizer(log, model, idle=0)

    summarizer.schedule()
    assert wait_until(lambda: summarizer.up_to_date)

    log.add("otra", "Otra.", "chat")
    assert not summarizer.up_to_date
    summarizer.schedule()
    assert wait_until(lambda: summarizer.up_to_date)
    assert load_summary()["mensajes"] == 2


def test_sin_modelo_no_lanza_nada():
    summarizer = SessionSummarizer(log_with(), None)

    summarizer.schedule()

    assert summarizer.thread is None and summarizer.finish(5) is None


def test_no_bloquea_la_entrada():
    summarizer = SessionSummarizer(log_with(), Blocking(), idle=0)
    start = time.perf_counter()

    summarizer.schedule()

    assert time.perf_counter() - start < 0.5
    summarizer.interrupt()
