"""En modo voz el chat responde en 1 a 3 frases, sin listas, salvo que se pida detalle."""
from config.settings_manager import read_json
from core.actions.voice import VOICE_SETTING
from core.paths import DEFAULTS_FILE
from core.voice.speakable import to_speakable
from providers.ollama_provider import cut_notice
from providers.provider_router import BRIEF_REMINDER, VOICE_REMINDER
from test_chat_brevity import chat

LIMITS = read_json(DEFAULTS_FILE)["answer_limits"]["chat"]


def test_valor_en_answer_limits():
    assert LIMITS["voice_tokens"] < LIMITS["tokens"]


def test_en_voz_recordatorio_y_tope_de_voz():
    messages, kwargs = chat("sobre el blog de notas", **{VOICE_SETTING: True})

    assert messages[-1]["content"] == "sobre el blog de notas" + VOICE_REMINDER
    assert "1 a 3 frases" in VOICE_REMINDER and "sin listas" in VOICE_REMINDER
    assert kwargs["max_tokens"] == LIMITS["voice_tokens"]


def test_en_voz_el_prompt_de_sistema_no_cambia():
    # Mismo principio del prompt que sin voz: Ollama reutiliza su caché.
    with_voice, _ = chat("qué es un grafo", **{VOICE_SETTING: True})
    without, _ = chat("qué es un grafo")

    assert with_voice[0] == without[0]


def test_sin_voz_sigue_igual():
    messages, kwargs = chat("qué es un grafo")

    assert messages[-1]["content"].endswith(BRIEF_REMINDER)
    assert kwargs["max_tokens"] == LIMITS["tokens"]


def test_en_voz_con_detalle_no_se_acorta():
    messages, kwargs = chat("explica a fondo qué es un grafo", **{VOICE_SETTING: True})

    assert kwargs["max_tokens"] == LIMITS["detail_tokens"]
    assert VOICE_REMINDER not in messages[-1]["content"]


def test_el_aviso_de_recorte_no_se_lee():
    answer = "Un blog de notas es un diario." + cut_notice({"done_reason": "length"}, 150)

    assert to_speakable(answer) == "Un blog de notas es un diario."
