"""Tiempos de cada respuesta (--timing, "/tiempos").

El launcher abre una medición por mensaje (measure_request) solo si los
tiempos están activos; sin medición abierta, nada se registra y el
comportamiento no cambia. Se anotan:
- el IntentEngine (intent_stage, desde Brain);
- cada llamada a un proveedor (timed, desde ProviderRouter), con las
  métricas que devuelve Ollama (ollama_metrics: carga del modelo,
  procesamiento del prompt y tokens generados). Gemini no las da: solo su
  tiempo total.
"""
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

SETTING = "show_timing"

# Ollama da las duraciones en nanosegundos.
NS = 1e9


@dataclass
class ModelCall:
    provider: str
    model: str = None
    seconds: float = 0.0
    load: float = None
    prompt_eval: float = None
    prompt_tokens: int = None
    tokens: int = None
    eval: float = None


@dataclass
class Timings:
    start: float = field(default_factory=time.perf_counter)
    intent: float = None
    # Métricas de Ollama de la llamada del IntentEngine (ModelCall).
    intent_call: ModelCall = None
    calls: list = field(default_factory=list)
    # Métricas de Ollama de la llamada en curso (las recoge timed).
    pending: dict = None


_current = ContextVar("asia_timings", default=None)


def enabled(settings) -> bool:
    return bool(settings.get(SETTING))


def current():
    return _current.get()


@contextmanager
def measure_request():
    timings = Timings()
    token = _current.set(timings)

    try:
        yield timings
    finally:
        _current.reset(token)


@contextmanager
def intent_stage():
    start = time.perf_counter()

    try:
        yield
    finally:
        timings = current()

        if timings is not None:
            timings.intent = (timings.intent or 0) + time.perf_counter() - start


def timed(provider, model, call):
    """Ejecuta call() (una llamada a un proveedor) y anota su tiempo."""
    timings = current()

    if timings is None:
        return call()

    timings.pending = None
    start = time.perf_counter()

    try:
        return call()
    finally:
        metrics = timings.pending or {}
        timings.pending = None
        timings.calls.append(ModelCall(
            provider, metrics.pop("model", None) or model, time.perf_counter() - start, **metrics
        ))


def metrics_of(response) -> dict:
    def seconds(key):
        value = response.get(key)
        return value / NS if value is not None else None

    return {
        "model": response.get("model"),
        "load": seconds("load_duration"),
        "prompt_eval": seconds("prompt_eval_duration"),
        "prompt_tokens": response.get("prompt_eval_count"),
        "tokens": response.get("eval_count"),
        "eval": seconds("eval_duration"),
    }


def ollama_metrics(response):
    """Guarda las métricas de una respuesta de Ollama (la final, si es streaming)."""
    timings = current()

    if timings is not None and response is not None:
        timings.pending = metrics_of(response)


def intent_metrics(response):
    """Las métricas de la llamada del IntentEngine, aparte de las de la respuesta.

    prompt_tokens son los tokens que Ollama procesó: si reutiliza el prompt
    de la llamada anterior (caché), solo cuenta los nuevos.
    """
    timings = current()

    if timings is not None and response is not None:
        metrics = metrics_of(response)
        timings.intent_call = ModelCall("ollama", metrics.pop("model"), **metrics)


# --- La línea que se imprime ---------------------------------------------------

def number(value, digits=1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def total_of(calls, key):
    values = [getattr(c, key) for c in calls if getattr(c, key) is not None]
    return sum(values) if values else None


def intent_part(timings: Timings) -> str:
    """"intención 21,3 s (prompt 2400 tokens en 19,8 s, 18 generados)"."""
    if timings.intent is None:
        return "intención —"

    text = f"intención {number(timings.intent)} s"
    call = timings.intent_call

    if call is None or call.prompt_tokens is None:
        return text

    prompt = f"prompt {call.prompt_tokens} tokens en {number(call.prompt_eval or 0)} s"
    load = f", carga {number(call.load)} s" if call.load else ""
    return f"{text} ({prompt}, {call.tokens or 0} generados{load})"


def summary(timings: Timings, now=None) -> str:
    """[tiempos] intención · carga · prompt · tokens · t/s · total · proveedor/modelo."""
    total = (now if now is not None else time.perf_counter()) - timings.start
    parts = [intent_part(timings)]
    calls = timings.calls

    load = total_of(calls, "load")

    if load is not None:
        prompt_eval = total_of(calls, "prompt_eval") or 0
        prompt_tokens = total_of(calls, "prompt_tokens")
        tokens = total_of(calls, "tokens") or 0
        eval_seconds = total_of(calls, "eval")
        rate = number(tokens / eval_seconds) if eval_seconds else "—"
        prompt_tokens = f" ({prompt_tokens} tokens)" if prompt_tokens is not None else ""

        parts += [
            f"carga {number(load)} s",
            f"prompt {number(prompt_eval)} s{prompt_tokens}",
            f"{tokens} tokens generados",
            f"{rate} t/s",
        ]

    parts.append(f"total {number(total)} s")

    if calls:
        used = []

        for call in calls:
            # Gemini usa gemini_model, no el modelo de Ollama que le pasa el router.
            name = f"{call.provider}/{call.model}" if call.provider == "ollama" and call.model else call.provider

            if name not in used:
                used.append(name)

        count = f" ({len(calls)} llamadas)" if len(calls) > 1 else ""
        parts.append(", ".join(used) + count)
    else:
        parts.append("sin modelo")

    return "[tiempos] " + " · ".join(parts)
