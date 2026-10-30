"""Chat breve por defecto, más largo si se pide detalle, y sin inventar."""
import pytest

from config.settings_manager import SettingsManager, read_json
from core.paths import DEFAULTS_FILE
from core.provenance import USUARIO, Fragment, request_sources
from providers.provider_router import CHAT_RULES, SYSTEM_PROMPT, wants_detail
from test_confidencial import make_brain


class Recording:
    def __init__(self):
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return "ok"


def chat(text, **overrides):
    SettingsManager.set_overrides(overrides)
    brain = make_brain()
    provider = Recording()
    brain.provider_router.providers["ollama"] = provider

    with request_sources(Fragment(USUARIO, text)):
        brain.provider_router.chat(text)

    return provider.calls[0]


LIMITS = read_json(DEFAULTS_FILE)["answer_limits"]["chat"]


def test_valores_en_defaults():
    assert LIMITS["tokens"] < LIMITS["detail_tokens"]


def test_breve_por_defecto():
    messages, kwargs = chat("qué es un grafo bipartito")

    assert kwargs["max_tokens"] == LIMITS["tokens"]
    system = messages[0]["content"]
    assert system.startswith(SYSTEM_PROMPT + "\n\n" + CHAT_RULES)
    assert "2 a 5 frases" in system
    assert "No inventes ejemplos, datos, nombres" in system and "no estoy seguro" in system


@pytest.mark.parametrize(
    "text",
    ["explica a fondo qué es un grafo", "explícame con detalle los grafos", "dame ejemplos de grafos",
     "explica paso a paso el algoritmo", "quiero una explicación detallada"],
)
def test_mas_largo_si_se_pide_detalle(text):
    _, kwargs = chat(text)

    assert kwargs["max_tokens"] == LIMITS["detail_tokens"]


@pytest.mark.parametrize("text", ["hola", "qué es un grafo", "el fondo del mar", "dame un ejemplo"])
def test_sin_detalle(text):
    # "dame un ejemplo" pide uno, cabe en una respuesta breve.
    assert not wants_detail(text)


def test_el_principio_del_prompt_no_cambia_con_el_detalle():
    short, _ = chat("qué es un grafo")
    long, _ = chat("explica a fondo qué es un grafo")

    # Mismo prompt de sistema: Ollama reutiliza su caché.
    assert short[0] == long[0]


def test_con_razonamiento_no_hay_tope():
    SettingsManager.set_overrides({"forced_domain": "math"})
    brain = make_brain()
    provider = Recording()
    brain.provider_router.providers["ollama"] = provider

    with request_sources(Fragment(USUARIO, "resuelve 3x + 7 = 22")):
        brain.provider_router.chat("resuelve 3x + 7 = 22")

    _, kwargs = provider.calls[0]
    assert kwargs["think"] is True and "max_tokens" not in kwargs


def test_las_acciones_no_llevan_las_reglas_del_chat():
    brain = make_brain()
    provider = Recording()
    brain.provider_router.providers["ollama"] = provider

    brain.provider_router.ask("resume esto")

    messages, kwargs = provider.calls[0]
    assert CHAT_RULES not in messages[0]["content"] and "max_tokens" not in kwargs
