"""Reflexión (fase R): resumen al abrir, resumen al salir y sesión. Con modelo simulado."""
import threading
import time
from datetime import datetime

import pytest

import launcher
from config.settings_manager import read_json
from core import paths
from core.paths import DEFAULTS_FILE
from core.reflection import (
    SessionLog,
    SessionSummarizer,
    clean_summary,
    external_sends,
    first_sentences,
    load_summary,
    local_model,
    opening_text,
    save_summary,
    session_description,
    simple_summary,
)
from core.tasks import TaskList
from test_confidencial import make_brain
from test_launcher import FakeBrain, reader


def opened(capsys, lines=("salir",)):
    launcher.interactive_mode(FakeBrain("hecho"), read=reader(list(lines)))
    return capsys.readouterr().out


# --- Al abrir ----------------------------------------------------------------------

def test_sin_nada_no_muestra_nada(capsys):
    assert opening_text() == ""
    assert "Sesión anterior" not in opened(capsys) and "Pendientes" not in opened(capsys)


def test_muestra_una_o_dos_frases_y_los_pendientes(capsys):
    save_summary("Revisamos el PID. Ajustamos la ganancia a 3.5 por ciento. Quedó probar en el robot.", "modelo", 6)
    TaskList().add("Probar en el robot")
    TaskList().add("Actualizar el reporte")

    out = opened(capsys)

    assert "Revisamos el PID. Ajustamos la ganancia a 3.5 por ciento." in out
    assert "Quedó probar" not in out
    assert "Pendientes:\n1. Probar en el robot\n2. Actualizar el reporte" in out


def test_solo_pendientes_o_solo_resumen():
    TaskList().add("Uno")
    assert opening_text() == "Pendientes:\n1. Uno"

    TaskList().close(1)
    save_summary("Hablamos de grafos.", "modelo", 2)
    assert "Hablamos de grafos." in opening_text() and "Pendientes" not in opening_text()


def test_abrir_no_llama_al_modelo(capsys):
    save_summary("Hablamos de grafos.", "modelo", 2)

    class NoModel:
        def get_provider(self, name):
            raise AssertionError("abrir Asia no debe usar el modelo")

    brain = FakeBrain("hecho")
    brain.provider_router = NoModel()

    launcher.interactive_mode(brain, read=reader(["salir"]))

    assert "Hablamos de grafos." in capsys.readouterr().out


def test_archivos_danados_no_impiden_abrir(capsys):
    paths.SESSION_SUMMARY_FILE.parent.mkdir(parents=True)
    paths.SESSION_SUMMARY_FILE.write_text("{ roto", encoding="utf-8")
    paths.TASKS_FILE.write_text("{ roto", encoding="utf-8")

    assert load_summary() is None and opening_text() == ""
    assert "Asia apagada." in opened(capsys)


def test_primeras_frases():
    assert first_sentences("Una. Dos! ¿Tres? Cuatro.", 2) == "Una. Dos!"
    assert first_sentences("Pesa 3.5 GB y ya. Otra.", 1) == "Pesa 3.5 GB y ya."
    assert first_sentences("Sin punto", 2) == "Sin punto"


# --- Al salir ----------------------------------------------------------------------

class Model:
    """Ollama simulado: model(messages), como el modelo local; responde answer, o falla, o tarda."""

    def __init__(self, answer="Hablamos de grafos. Revisamos brain.py.", error=None, delay=0):
        self.answer = answer
        self.error = error
        self.delay = delay
        self.calls = []

    def complete(self, messages, max_tokens=None, **options):
        self.calls.append((messages, max_tokens))

        if self.delay:
            threading.Event().wait(self.delay)

        if self.error:
            raise self.error

        return self.answer

    def __call__(self, messages):
        return self.complete(messages, max_tokens=None)


class Router:
    def __init__(self, model):
        self.model = model
        self.providers_asked = []

    def get_provider(self, name):
        self.providers_asked.append(name)
        return self.model

    def chat(self, prompt, on_chunk=None, history_prompt=None):
        return "respuesta del chat"


def brain_with(model, **settings):
    brain = FakeBrain("hecho", **settings)
    brain.provider_router = Router(model)
    return brain


def filled_log(*actions):
    log = SessionLog()

    for action in actions or ("chat",):
        log.add("qué es un grafo", "Un grafo es un conjunto de nodos.", action)

    return log


def test_al_salir_resume_con_el_modelo_lo_guarda_y_lo_muestra(capsys):
    brain = brain_with(Model())

    launcher.interactive_mode(brain, read=reader(["hola", "salir"]))

    out = capsys.readouterr()
    assert "Resumen de la sesión: Hablamos de grafos. Revisamos brain.py." in out.out
    assert out.out.rstrip().endswith("Asia apagada.")
    summary = load_summary()
    assert summary["resumen"] == "Hablamos de grafos. Revisamos brain.py."
    assert summary["origen"] == "modelo" and summary["mensajes"] == 1


def test_el_resumen_guardado_aparece_al_abrir_la_siguiente_sesion(capsys):
    launcher.interactive_mode(brain_with(Model()), read=reader(["hola", "salir"]))
    capsys.readouterr()

    launcher.interactive_mode(FakeBrain("hecho"), read=reader(["salir"]))

    assert "Sesión anterior" in capsys.readouterr().out


def test_sesion_vacia_no_llama_al_modelo_ni_borra_el_anterior(capsys):
    save_summary("Lo de ayer.", "modelo", 3)
    model = Model()

    launcher.interactive_mode(brain_with(model), read=reader(["salir"]))

    assert model.calls == [] and load_summary()["resumen"] == "Lo de ayer."
    assert "Resumen de la sesión" not in capsys.readouterr().out


def test_prompt_con_lo_pedido_y_la_accion():
    model = Model()

    SessionSummarizer(filled_log("chat", "explain_file"), model, idle=0).finish(5)

    [(messages, _)] = model.calls
    prompt = messages[0]["content"]
    assert "Usuario: qué es un grafo" in prompt and "(acción explain_file)" in prompt
    assert "2 a 3 frases" in prompt and "No inventes" in prompt


def test_el_resumen_no_trae_textos_enteros():
    log = SessionLog()
    log.add("x" * 5000, "y" * 5000, "chat")

    assert len(session_description(log)) < 500


def test_cuenta_los_envios_externos_de_la_sesion(monkeypatch):
    log = filled_log()
    old = {"fecha": "2020-01-01T00:00:00"}
    new = {"fecha": datetime.now().isoformat(timespec="seconds")}
    monkeypatch.setattr("core.reflection.recent_entries", lambda limit: [old, new])

    assert external_sends(log) == 1
    assert "Envíos externos: 1." in simple_summary(log)
    assert "proveedores externos en la sesión: 1" in session_description(log)


@pytest.mark.parametrize(
    "model",
    [Model(error=ConnectionError("sin Ollama")), Model(answer=""), Model(answer="   "), Model(delay=2)],
)
def test_si_el_modelo_falla_o_tarda_resumen_simple(model):
    log = filled_log("chat", "chat", "explain_file")

    assert SessionSummarizer(log, model, idle=0).finish(0.2) is None
    assert simple_summary(log) == "Sesión de 3 mensajes: conversación (2), explain_file (1)."


def test_si_el_modelo_no_responde_sale_igual_y_a_tiempo(capsys):
    brain = brain_with(Model(delay=10), reflection={"summary_timeout_s": 0.2})
    start = time.perf_counter()

    launcher.interactive_mode(brain, read=reader(["hola", "salir"]))

    assert time.perf_counter() - start < 5
    assert load_summary()["origen"] == "simple"
    assert capsys.readouterr().out.rstrip().endswith("Asia apagada.")


def test_sin_router_real_resumen_simple(capsys):
    launcher.interactive_mode(FakeBrain("hecho"), read=reader(["hola", "salir"]))

    assert load_summary()["origen"] == "simple"


def test_ctrl_c_en_el_prompt_tambien_guarda_el_resumen(capsys):
    brain = brain_with(Model())
    lines = iter(["hola"])

    def read(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise KeyboardInterrupt

    launcher.interactive_mode(brain, read=read)

    assert load_summary()["origen"] == "modelo"
    assert capsys.readouterr().out.rstrip().endswith("Asia apagada.")


def test_ollama_en_otra_maquina_no_recibe_la_sesion(capsys):
    model = Model()
    brain = brain_with(model, ollama_host="http://10.0.0.9:11434")

    launcher.interactive_mode(brain, read=reader(["hola", "salir"]))

    assert model.calls == [] and load_summary()["origen"] == "simple"


def test_solo_usa_el_proveedor_local_y_el_tope_de_config():
    model = Model()
    brain = brain_with(model, answer_limits={"session_summary": {"tokens": 77}})

    local_model(brain)([{"role": "user", "content": "x"}])

    assert brain.provider_router.providers_asked == ["ollama"]
    assert model.calls[0][1] == 77


def test_quita_el_aviso_de_recorte_y_la_frase_a_medias():
    text = ("Hablamos de grafos. Revisamos brain.py. Y luego fuimos a\n\n"
            "[Respuesta recortada en 120 tokens (answer_limits en config).]")

    assert clean_summary(text) == "Hablamos de grafos. Revisamos brain.py."


def test_como_mucho_tres_frases():
    assert clean_summary("Una. Dos. Tres. Cuatro.") == "Una. Dos. Tres."


def test_si_no_se_puede_guardar_sale_igual(capsys, monkeypatch):
    def broken(*args):
        raise OSError("disco lleno")

    monkeypatch.setattr("core.reflection.save_summary", broken)

    launcher.interactive_mode(FakeBrain("hecho"), read=reader(["hola", "salir"]))

    out = capsys.readouterr()
    assert "No pude guardar el resumen" in out.err and out.out.rstrip().endswith("Asia apagada.")


def test_los_comandos_de_sesion_no_cuentan():
    brain = make_brain()
    brain.process("/modelo")
    assert brain.last_action is None

    brain.process("hola")
    assert brain.last_action == "chat"


def test_valores_en_defaults():
    defaults = read_json(DEFAULTS_FILE)

    assert defaults["reflection"]["summary_timeout_s"] > 0
    assert defaults["answer_limits"]["session_summary"]["tokens"] > 0
