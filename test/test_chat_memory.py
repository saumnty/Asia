"""Memoria personal en el chat: solo lo relevante, en tercera persona, y el historial con presupuesto."""
import pytest

from config.settings_manager import SettingsManager
from core.chat_memory import MAX_ENTRIES, TITLE, is_small_talk, memory_note, relevant_memory
from core.provenance import USUARIO, Fragment, request_sources
from test_chat_brevity import Recording
from test_confidencial import make_brain

MEMORY = {"nombre": "Santiago", "proyecto": "Bolitabot", "universidad": "UAM", "color_favorito": "amarillo"}


def setup(memory=MEMORY, **overrides):
    SettingsManager.set_overrides(overrides)
    brain = make_brain()
    brain.provider_router.memory.load = lambda: memory
    provider = Recording()
    brain.provider_router.providers["ollama"] = provider
    return brain.provider_router, provider


def say(router, text):
    with request_sources(Fragment(USUARIO, text)):
        router.chat(text)


def sent(provider):
    return "\n".join(m["content"] for m in provider.calls[-1][0])


@pytest.mark.parametrize("text", ["hola", "Hola!", "buenos días", "gracias", "muchas gracias", "adiós", "ok", "nos vemos"])
def test_charla_breve_sin_memoria(text):
    router, provider = setup()

    say(router, text)

    assert is_small_talk(text)
    assert not any(value in sent(provider) for value in MEMORY.values())
    assert TITLE not in sent(provider)


@pytest.mark.parametrize("text", ["hola, cómo me llamo?", "gracias, y cuál es mi color favorito?", "qué es un grafo"])
def test_no_es_charla_breve(text):
    assert not is_small_talk(text)


@pytest.mark.parametrize(
    "text, key",
    [("cuál es mi color favorito?", "color_favorito"), ("cómo me llamo?", "nombre"),
     ("dónde estudio?", "universidad"), ("en qué proyecto trabajo?", "proyecto")],
)
def test_solo_la_entrada_relevante(text, key):
    assert list(relevant_memory(text, MEMORY)) == [key]


def test_nada_relevante_nada_de_memoria():
    router, provider = setup()

    say(router, "qué es una closure en Python?")

    assert TITLE not in sent(provider)
    assert not any(value in sent(provider) for value in MEMORY.values())


def test_tercera_persona_bajo_el_titulo_y_fuera_del_prompt_de_sistema():
    router, provider = setup()

    say(router, "cuál es mi color favorito?")

    messages = provider.calls[-1][0]
    assert "amarillo" not in messages[0]["content"]
    user = messages[-1]["content"]
    assert user.startswith(f"{TITLE}\n- color favorito del usuario: amarillo\n\nMensaje del usuario:\ncuál es mi color favorito?")
    assert "Santiago" not in user and "UAM" not in user


def test_el_prompt_de_sistema_no_cambia_entre_mensajes():
    router, provider = setup()

    say(router, "hola")
    say(router, "cómo me llamo?")

    assert provider.calls[0][0][0] == provider.calls[1][0][0]


def test_lo_que_sabes_de_mi_tiene_tope():
    many = {f"dato_{i}": f"valor {i}" for i in range(MAX_ENTRIES + 3)}

    assert len(relevant_memory("qué sabes de mí?", many)) == MAX_ENTRIES
    assert relevant_memory("qué sabes de mí?", MEMORY) == MEMORY
    assert memory_note({}) == ""


def test_el_historial_no_guarda_la_nota():
    router, _ = setup()

    say(router, "cómo me llamo?")

    assert router.history[0] == {"role": "user", "content": "cómo me llamo?"}


SMALL = {"models_by_domain": {"code": "big", "math": "big", "general": "small"}, "ollama_model": "big",
         "ollama_num_ctx": 16384, "ollama_model_options": {"small": {"num_ctx": 4096}}}


def long_history(router, turns, chars):
    for i in range(turns):
        router.history += [{"role": "user", "content": f"pregunta {i} " + "x" * chars},
                           {"role": "assistant", "content": f"respuesta {i} " + "y" * chars}]
        router.history_labels += [USUARIO, USUARIO]


def test_historial_que_no_cabe_se_recorta_desde_lo_mas_antiguo():
    router, provider = setup(**SMALL)
    # 10 turnos de ~600 tokens: no caben en 4096 con la respuesta.
    long_history(router, 10, 1000)

    say(router, "qué es un grafo")

    messages, kwargs = provider.calls[-1]
    assert kwargs["model"] == "small"
    kept = [m["content"] for m in messages[1:-1]]
    assert kept and len(kept) % 2 == 0 and len(kept) < 20
    assert kept[-1].startswith("respuesta 9") and not any(m.startswith("pregunta 0 ") for m in kept)
    # El historial guardado no se recorta: otro modelo lo puede usar entero.
    assert len(router.history) == 20


def test_historial_que_cabe_va_entero():
    router, provider = setup(**SMALL)
    long_history(router, 3, 50)

    say(router, "qué es un grafo")

    assert len(provider.calls[-1][0]) == 1 + 6 + 1


def test_si_ni_sin_historial_cabe_responde_el_modelo_grande():
    router, provider = setup(**SMALL)
    long_history(router, 2, 50)

    say(router, "resume esto: " + "z" * 20000)

    messages, kwargs = provider.calls[-1]
    assert kwargs["model"] == "big"
    # Con 16384 el historial corto entra.
    assert len(messages) == 1 + 4 + 1


@pytest.mark.parametrize("text", ["¿cuál es tu color favorito?", "¿quién eres?", "¿cómo te llamas?", "¿qué proyecto te gusta?"])
def test_una_pregunta_a_asia_no_lleva_memoria(text):
    assert relevant_memory(text, MEMORY) == {}


def test_tu_y_mi_juntos_si_llevan_memoria():
    assert list(relevant_memory("¿te acuerdas de mi color favorito?", MEMORY)) == ["color_favorito"]


class RecallIntent:
    def detect(self, text):
        return {"action": "recall", "params": {"key": "color_favorito"}}


@pytest.mark.parametrize("text", ["¿cuál es tu color favorito?", "¿qué sabes de mí?", "háblame sobre mí"])
def test_recall_que_no_pregunta_por_un_dato_del_usuario_va_al_chat(text):
    brain = make_brain()
    brain.intent_engine = RecallIntent()

    assert brain.process(text) is None
    assert brain.last_action == "chat"


def test_recall_de_un_dato_del_usuario_sigue_igual(monkeypatch):
    brain = make_brain()
    brain.intent_engine = RecallIntent()
    brain.memory = type("M", (), {"recall": lambda self, key: "amarillo"})()

    assert brain.process("¿cuál es mi color favorito?") == "color_favorito: amarillo"
