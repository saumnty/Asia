"""--timing y "/tiempos": una línea con los tiempos de cada respuesta."""
import pytest

import launcher
from config.settings_manager import SettingsManager
from core import timing
from core.paths import SETTINGS_FILE
from core.timing import ModelCall, Timings, summary
from providers.ollama_provider import OllamaProvider
from test_confidencial import TTY, FakeProvider, interactive, make_brain

NS = 1_000_000_000

# Lo que devuelve Ollama al final de una respuesta (duraciones en ns).
METRICS = {
    "model": "qwen2.5-coder:7b",
    "load_duration": 2 * NS,
    "prompt_eval_count": 812,
    "prompt_eval_duration": NS // 2,
    "eval_count": 120,
    "eval_duration": 10 * NS,
}


class SimulatedOllama(FakeProvider):
    """Como Ollama: deja las métricas de la respuesta."""

    def complete(self, messages, **kwargs):
        answer = super().complete(messages, **kwargs)
        timing.ollama_metrics(METRICS)
        return answer


class SlowIntent:
    def detect(self, text):
        return {"action": "chat", "params": {}}


def brain_with_ollama():
    brain = make_brain()
    brain.provider_router.providers["ollama"] = SimulatedOllama("ollama")
    return brain


@pytest.fixture
def settings_untouched():
    before = SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None
    yield
    assert (SETTINGS_FILE.read_bytes() if SETTINGS_FILE.exists() else None) == before


# --- La línea ----------------------------------------------------------------------

def test_linea_con_las_metricas_de_ollama():
    timings = Timings(start=0.0, intent=1.25)
    timings.calls.append(ModelCall("ollama", "qwen2.5-coder:7b", 12.0, load=2.0, prompt_eval=0.5,
                                   prompt_tokens=812, tokens=120, eval=10.0))

    assert summary(timings, now=15.0) == (
        "[tiempos] intención 1,2 s · carga 2,0 s · prompt 0,5 s (812 tokens) · "
        "120 tokens generados · 12,0 t/s · total 15,0 s · ollama/qwen2.5-coder:7b"
    )


def test_linea_de_gemini_solo_total_y_proveedor():
    timings = Timings(start=0.0, intent=1.0)
    timings.calls.append(ModelCall("gemini", "qwen2.5-coder:7b", 3.0))

    line = summary(timings, now=4.0)

    assert line == "[tiempos] intención 1,0 s · total 4,0 s · gemini"


def test_varias_llamadas_se_suman():
    timings = Timings(start=0.0)
    for _ in range(3):
        timings.calls.append(ModelCall("ollama", "m:1", 1.0, load=0.1, prompt_eval=0.2,
                                       prompt_tokens=10, tokens=20, eval=1.0))

    line = summary(timings, now=5.0)

    assert "intención —" in line and "60 tokens generados" in line and "20,0 t/s" in line
    assert line.endswith("ollama/m:1 (3 llamadas)")


def test_sin_modelo():
    assert summary(Timings(start=0.0), now=0.0) == "[tiempos] intención — · total 0,0 s · sin modelo"


# --- OllamaProvider toma las métricas de la respuesta ---------------------------

class FakeOllamaClient:
    def __init__(self, stream=False):
        self.stream = stream

    def ps(self):
        raise ConnectionError

    def show(self, model):
        raise ConnectionError

    def chat(self, model, messages, stream=False, options=None, **kwargs):
        if not stream:
            return {"message": {"content": "hola"}, **METRICS}

        return iter([
            {"message": {"content": "ho"}, "done": False},
            {"message": {"content": "la"}, "done": True, **METRICS},
        ])


@pytest.mark.parametrize("stream", [False, True])
def test_ollama_provider_registra_las_metricas(stream):
    provider = OllamaProvider.__new__(OllamaProvider)
    provider.settings = SettingsManager()
    provider.client = FakeOllamaClient()

    with timing.measure_request() as timings:
        chunks = []
        answer = timing.timed("ollama", None, lambda: provider.complete(
            [{"role": "user", "content": "hola"}], on_chunk=chunks.append if stream else None
        ))

    assert answer == "hola"
    [call] = timings.calls
    assert (call.model, call.load, call.prompt_tokens, call.tokens, call.eval) == (
        "qwen2.5-coder:7b", 2.0, 812, 120, 10.0
    )


def test_sin_medicion_abierta_no_se_registra_nada():
    timing.ollama_metrics(METRICS)

    assert timing.timed("ollama", "m", lambda: "x") == "x"
    assert timing.current() is None


# --- De punta a punta ----------------------------------------------------------------

def test_timing_imprime_la_linea_despues_de_la_respuesta(capsys, settings_untouched):
    brain = brain_with_ollama()

    launcher.main(["--timing", "hola"], stdin=TTY, brain_factory=lambda: brain)

    captured = capsys.readouterr()
    assert "respuesta de ollama" in captured.out
    [line] = [l for l in captured.err.splitlines() if l.startswith("[tiempos]")]
    assert "intención " in line and "carga 2,0 s" in line and "prompt 0,5 s (812 tokens)" in line
    assert "120 tokens generados · 12,0 t/s · total" in line
    assert line.endswith("ollama/qwen2.5-coder:7b")


def test_sin_timing_no_cambia_nada(capsys):
    brain = brain_with_ollama()

    launcher.main(["hola"], stdin=TTY, brain_factory=lambda: brain)

    captured = capsys.readouterr()
    assert "[tiempos]" not in captured.out + captured.err
    assert "respuesta de ollama" in captured.out


def test_gemini_total_y_proveedor(capsys):
    brain = make_brain()

    launcher.main(["--timing", "--provider", "gemini", "hola"], stdin=TTY, brain_factory=lambda: brain)

    [line] = [l for l in capsys.readouterr().err.splitlines() if l.startswith("[tiempos]")]
    assert "carga" not in line and "t/s" not in line
    assert " · total " in line and line.endswith(" · gemini")


@pytest.mark.parametrize("on, off", [("/tiempos", "/sin tiempos"), ("muestra tiempos", "oculta tiempos")])
def test_comandos_de_sesion(capsys, settings_untouched, on, off):
    brain = brain_with_ollama()

    out = interactive(brain, ["hola", on, "hola", off, "hola", "salir"], capsys)

    assert "Tiempos activados" in out and "Tiempos ocultos." in out
    assert timing.SETTING not in SettingsManager.overrides


def test_comandos_de_sesion_imprimen_una_sola_linea(capsys):
    brain = brain_with_ollama()
    lines = iter(["hola", "/tiempos", "hola", "/sin tiempos", "hola", "salir"])

    launcher.interactive_mode(brain, read=lambda prompt: next(lines))

    captured = capsys.readouterr()
    assert captured.err.count("[tiempos]") == 1
    assert captured.out.count("respuesta de ollama") == 3


def test_el_intent_engine_se_mide(capsys):
    brain = brain_with_ollama()
    brain.intent_engine = SlowIntent()

    # "hola" iría por la ruta rápida, sin IntentEngine.
    launcher.main(["--timing", "cuéntame un chiste"], stdin=TTY, brain_factory=lambda: brain)

    line = capsys.readouterr().err
    assert "intención 0,0 s" in line


def test_la_ruta_rapida_no_mide_intencion(capsys):
    brain = brain_with_ollama()

    launcher.main(["--timing", "hola"], stdin=TTY, brain_factory=lambda: brain)

    assert "intención —" in capsys.readouterr().err


def test_help_documenta_timing(capsys):
    with pytest.raises(SystemExit):
        launcher.build_parser().parse_args(["--help"])

    out = capsys.readouterr().out
    assert "--timing" in out and "/tiempos" in out and "/sin tiempos" in out


# --- El IntentEngine por dentro ------------------------------------------------------

def test_linea_con_las_metricas_del_intent_engine():
    timings = Timings(start=0.0, intent=21.3)
    timings.intent_call = ModelCall("ollama", "m:1", load=0.0, prompt_eval=19.8, prompt_tokens=2400, tokens=18, eval=1.2)

    assert summary(timings, now=22.0).startswith(
        "[tiempos] intención 21,3 s (prompt 2400 tokens en 19,8 s, 18 generados) · total 22,0 s"
    )


class FakeIntentClient(FakeOllamaClient):
    def chat(self, model, messages, stream=False, options=None, **kwargs):
        return {
            "message": {"content": '{"action": "chat", "params": {}}'},
            **METRICS, "prompt_eval_count": 1900, "eval_count": 14,
        }


def test_intent_engine_registra_sus_metricas_aparte():
    from core.intent_engine import IntentEngine

    engine = IntentEngine.__new__(IntentEngine)
    engine.settings = SettingsManager()
    engine.client = FakeIntentClient()

    with timing.measure_request() as timings:
        with timing.intent_stage():
            assert engine.detect("hola")["action"] == "chat"

    assert (timings.intent_call.prompt_tokens, timings.intent_call.tokens) == (1900, 14)
    assert timings.calls == []
    assert "prompt 1900 tokens en 0,5 s, 14 generados, carga 2,0 s" in summary(timings)
