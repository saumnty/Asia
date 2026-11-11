"""Tareas largas con voz: aviso fijo, revisión desde el primer hallazgo y /buscar más rápido."""
import sys
from pathlib import Path

import pytest

from core.rag.library import is_english, needs_translation
from core.rag.quotes import Quote, numbered_context, quoted_numbers, verify_quotes
from core.timing import Timings, summary
from core.voice.notices import NOTICES, Notices, announce
from core.voice.reading import Reading, first_finding
from test_rag_answer import CONTEXT
from test_rag_language import source
from test_voice_input import FakeSpeaker, FakeTTS

sys.path.insert(0, str(Path(__file__).parent / "manual"))
import check_primer_audio  # noqa: E402


# --- Aviso fijo -----------------------------------------------------------------------

def test_los_avisos_se_sintetizan_una_vez():
    tts = FakeTTS()
    notices = Notices(tts)

    notices.warm()
    notices.audio("review")
    notices.audio("search")

    assert sorted(tts.texts) == sorted(NOTICES.values())


def test_el_aviso_suena_primero_sin_sintetizar_y_se_mide_aparte():
    tts, speaker = FakeTTS(), FakeSpeaker()
    notices = Notices(tts)
    notices.warm()
    tts.texts.clear()
    timings = Timings(start=0.0)
    reading = Reading(tts, speaker, timings, notices)

    reading.notice("search")
    reading.feed("La respuesta. ")
    reading.finish("La respuesta. ")
    assert reading.wait(5)

    assert tts.texts == ["La respuesta."]
    assert reading.spoken == ["La respuesta."] and len(speaker.played) == 2
    assert timings.notice_audio is not None and timings.first_audio >= timings.notice_audio


def test_sin_avisos_no_suena_nada_de_mas():
    tts, speaker = FakeTTS(), FakeSpeaker()
    reading = Reading(tts, speaker)

    reading.notice("search")
    reading.finish("Hola.")
    assert reading.wait(5)
    assert len(speaker.played) == 1


def test_announce_solo_con_voz():
    heard = []
    owner = type("O", (), {})()

    announce(owner, "review")
    owner.action_notice = heard.append
    announce(owner, "review")

    assert heard == ["review"]


def test_el_aviso_en_la_linea_de_tiempos():
    timings = Timings(start=0.0, intent=1.0, answered=9.0, notice_audio=0.4, first_audio=20.0)

    assert "aviso 0,4 s · primer audio 20,0 s" in summary(timings)


# --- Revisión: desde el primer hallazgo -----------------------------------------------

REVIEW = (
    "Revisión del archivo core/timing.py.\n\n### 1. Bugs posibles\n"
    "- **Línea 12**: `timings.start` puede ser None si no se llamó a measure_request antes.\n"
    "- Otra cosa que mirar con calma en la función summary del módulo.\n"
)


def test_el_primer_hallazgo_completo():
    start = REVIEW.index("- **Línea 12**")

    assert first_finding(REVIEW) == start
    assert first_finding(REVIEW[:start + 40]) is None
    assert first_finding("### 1. Bugs posibles\n2. Errores de flujo\n") is None


def review_reading(chunks, answer):
    tts, speaker = FakeTTS(), FakeSpeaker()
    notices = Notices(tts)
    notices.warm()
    tts.texts.clear()
    reading = Reading(tts, speaker, None, notices)
    reading.notice("review")

    for chunk in chunks:
        reading.feed(chunk)

    reading.finish(answer)
    assert reading.wait(5)
    return reading


def test_la_revision_se_lee_desde_el_primer_hallazgo():
    chunks = [REVIEW[i:i + 7] for i in range(0, len(REVIEW), 7)]
    reading = review_reading(chunks, REVIEW)

    assert reading.spoken[0].startswith("Línea 12")
    assert not any("Revisión del archivo" in text or "Bugs posibles" in text for text in reading.spoken)


def test_una_revision_sin_puntos_se_lee_entera():
    answer = "El archivo está bien. No veo problemas."
    reading = review_reading([answer], answer)

    assert reading.spoken == ["El archivo está bien.", "No veo problemas."]


def test_sin_streaming_tambien_se_lee():
    answer = "Todo correcto en este archivo."
    reading = review_reading([], answer)

    assert reading.spoken == ["Todo correcto en este archivo."]


# --- /buscar: números de línea --------------------------------------------------------

def test_el_contexto_numera_las_lineas_del_archivo():
    numbered = numbered_context(CONTEXT)

    assert "40| def salida(self):" in numbered and "41|     self.kp   =   2.5" in numbered
    assert "1| Un robot que balancea una bolita." in numbered
    # La línea de origen no lleva número.
    assert "control/pid.py · Pid.salida\n40|" in numbered


@pytest.mark.parametrize("text, ranges", [("41", [(41, 41)]), ("41, 43-45", [(41, 41), (43, 45)]),
                                          ("41 y 42", [(41, 41), (42, 42)]), ("self.kp = 2.5", None), ("", None)])
def test_solo_numeros(text, ranges):
    assert quoted_numbers(text) == ranges


def test_el_codigo_copia_las_lineas_de_los_numeros():
    quotes = verify_quotes("[control/pid.py:40-55] 41-42\n[README.md:1-8] 1", CONTEXT)

    assert quotes == [
        Quote("control/pid.py", 41, "Pid.salida", "    self.kp   =   2.5"),
        Quote("control/pid.py", 42, "Pid.salida", "    return self.kp * self.error"),
        Quote("README.md", 1, "", "Un robot que balancea una bolita."),
    ]


def test_un_numero_de_otro_fragmento_del_mismo_archivo_vale():
    [quote] = verify_quotes("[control/pid.py:40-55] 61", CONTEXT)

    assert quote == Quote("control/pid.py", 61, "Pid.reinicia", "    self.error = 0")


def test_numeros_que_no_existen_se_descartan():
    assert verify_quotes("[control/pid.py:40-55] 99\n[inventado.py] 3", CONTEXT) == []


def test_un_rango_enorme_no_cita_todo():
    assert len(verify_quotes("[control/pid.py:40-55] 40-900", CONTEXT)) == 3


def test_el_texto_copiado_sigue_valiendo():
    [quote] = verify_quotes("[control/pid.py:40-55] self.kp = 2.5", CONTEXT)

    assert quote.line == 41


def test_el_prompt_pide_numeros():
    from core import prompts

    prompt = prompts.extract_quotes("qué ganancia", numbered_context(CONTEXT), numbers=True)
    assert "41|" in prompt and "solo los números" in prompt and "textualmente" not in prompt


# --- /buscar: traducción --------------------------------------------------------------

@pytest.mark.parametrize("text, english", [("how do I create a virtual environment", True),
                                           ("cómo se crea un entorno virtual", False),
                                           ("what is QoS", True), ("qué es QoS", False), ("QoS", False)])
def test_ya_esta_en_ingles(text, english):
    assert is_english(text) is english


def test_una_pregunta_en_ingles_no_se_traduce():
    sources = [source("ros2", "en")]

    assert needs_translation("qué es QoS en ros2", sources)
    assert not needs_translation("what is QoS in ros2 en ros2", sources)
    assert not needs_translation("how do I set the QoS of a publisher en ros2", sources)


def test_la_traduccion_va_al_modelo_general(monkeypatch):
    from core.actions.explore import ExploreActions

    asked = []
    actions = ExploreActions.__new__(ExploreActions)
    actions.settings = type("S", (), {"get": lambda self, key, default=None: {"translate_question": True} if key == "rag" else default})()
    actions.provider_router = type("R", (), {"ask": lambda self, prompt, **options: asked.append(options) or "how is QoS set?"})()
    monkeypatch.setattr("core.actions.explore.Library", lambda: type("L", (), {"all": lambda self: [source("ros2", "en")]})())

    assert actions.translated_question("cómo se configura QoS en ros2") == "how is QoS set?"
    assert asked[0]["domain"] == "general"


# --- check_primer_audio: criterios por acción -----------------------------------------

def test_criterios_por_accion():
    medians = {"primer_audio": 20.0, "aviso": 0.4}

    assert check_primer_audio.meets("review_file", medians)
    assert not check_primer_audio.meets("explain_file", medians)
    assert not check_primer_audio.meets("review_file", {"primer_audio": 20.0, "aviso": 1.5})
    assert not check_primer_audio.meets("review_file", {"primer_audio": 20.0, "aviso": None})
    assert check_primer_audio.meets("search_project_rag", {"primer_audio": 29.0, "aviso": 0.3})
    assert not check_primer_audio.meets("search_project_rag", {"primer_audio": 31.0, "aviso": 0.3})
    assert check_primer_audio.meets("explain_file", {"primer_audio": 9.0, "aviso": None})


# --- Embeddings: sin la espera de localhost en Windows --------------------------------

def test_el_embedder_conecta_a_127_0_0_1():
    from core.rag.embedder import OllamaEmbedder, direct_host

    assert direct_host("http://localhost:11434") == "http://127.0.0.1:11434"
    assert direct_host("http://192.168.1.5:11434") == "http://192.168.1.5:11434"

    embedder = OllamaEmbedder(model="nomic-embed-text", host="http://localhost:11434", timeout=5)
    assert embedder.url == "http://127.0.0.1:11434/api/embeddings" and not embedder.external


def test_la_precarga_puede_conservar_nomic():
    from types import SimpleNamespace

    from providers.ollama_models import unload_others

    class Client:
        def __init__(self):
            self.unloaded = []

        def ps(self):
            names = ["qwen3:4b-instruct-2507-q4_K_M", "nomic-embed-text:latest"]
            return SimpleNamespace(models=[SimpleNamespace(model=name) for name in names])

        def generate(self, model, keep_alive=None):
            self.unloaded.append(model)

    client = Client()
    settings = {"ollama_one_model_at_a_time": True}

    assert unload_others(client, "qwen2.5-coder:7b", settings, keep=["nomic-embed-text"]) == ["qwen3:4b-instruct-2507-q4_K_M"]


def test_la_respuesta_por_voz_tiene_tope():
    from core.actions.explore import DEFAULT_ANSWER_LIMITS

    assert DEFAULT_ANSWER_LIMITS["search_answer"]["voice_tokens"] < DEFAULT_ANSWER_LIMITS["search_answer"]["tokens"]
