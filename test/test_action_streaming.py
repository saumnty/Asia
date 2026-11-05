"""Con voz, explain_file y summarize_file se escriben y se leen frase por frase mientras llega la respuesta."""

import pytest

import launcher
from config.settings_manager import SettingsManager
from core.actions.voice import VOICE_SETTING
from providers.provider_router import ProviderRouter
from test_document_prompts import Actions, Router
from test_launcher import FakeBrain
from test_voice_input import session
from test_voice_output import patient
from test_voice_reading import BlockingSpeaker

FOOTER = "\n\n[Para la explicación completa: explica a.py a fondo.]"
PARTS = ["Este archivo lee el micrófono. ", "Luego llama a Whisper."]


# --- ProviderRouter.ask ------------------------------------------------------------

def test_ask_pasa_on_chunk_al_proveedor_y_no_lo_guarda():
    router = ProviderRouter.__new__(ProviderRouter)
    router.settings = SettingsManager()
    seen = {}

    def complete(request, on_chunk=None, **options):
        seen["on_chunk"] = on_chunk
        on_chunk("hola")
        return "hola"

    router._complete = complete
    chunks = []

    assert router.ask("explica", max_tokens=150, on_chunk=chunks.append) == "hola"
    assert chunks == ["hola"] and seen["on_chunk"] == chunks.append
    # Repetir la petición (por ejemplo, para /enviar) no vuelve a escribir en la lectura de antes.
    assert "on_chunk" not in router.last_request[1]


# --- Las acciones ------------------------------------------------------------------

@pytest.mark.parametrize("action", ["explain_file", "summarize_file"])
@pytest.mark.parametrize("text", ["explica a.py", "explica a.py a fondo"])
def test_con_voz_la_accion_pasa_el_on_chunk_del_launcher(action, text):
    SettingsManager.set_overrides({VOICE_SETTING: True})
    actions = Actions("def f():\n    return 1\n")
    actions.action_stream = stream = []

    getattr(actions, f"handle_{action}")(text, {"file_path": "a.py"})

    [(_, kwargs)] = actions.provider_router.calls
    assert kwargs["on_chunk"] is stream


@pytest.mark.parametrize("action", ["explain_file", "summarize_file"])
def test_sin_on_chunk_la_llamada_es_la_de_siempre(action):
    actions = Actions("def f():\n    return 1\n")

    getattr(actions, f"handle_{action}")("explica a.py", {"file_path": "a.py"})

    [(_, kwargs)] = actions.provider_router.calls
    assert "on_chunk" not in kwargs


# --- El launcher -------------------------------------------------------------------

class StreamingBrain(FakeBrain):
    """Una acción que escribe a trozos por action_stream, si se lo dan, como explain_file con voz."""

    def __init__(self, speaker=None, **settings):
        super().__init__(None, **settings)
        self.speaker = speaker
        self.sounded_before_end = None
        self.streams = []

    def process(self, text):
        self.processed.append(text)
        stream = getattr(self, "action_stream", None)
        self.streams.append(stream is not None)

        if stream is not None:
            stream(PARTS[0])

            # La primera frase suena mientras la segunda todavía no llegó.
            if self.speaker is not None:
                self.sounded_before_end = self.speaker.playing.wait(5)

            stream(PARTS[1])

        return "".join(PARTS) + FOOTER


def test_con_voz_se_lee_desde_la_primera_frase(capsys):
    voice, _ = session([])
    voice._speaker = speaker = BlockingSpeaker(blocking=False)
    brain = StreamingBrain(speaker, **{launcher.VOICE_SETTING: True})

    launcher.interactive_mode(brain, read=patient(["explica a.py", "salir"], voice), voice=voice)

    assert brain.streams == [True] and brain.sounded_before_end is True
    assert voice.tts.texts == ["Este archivo lee el micrófono.", "Luego llama a Whisper."]
    out = capsys.readouterr().out
    # En pantalla una sola vez, con la línea de "a fondo" al final; esa línea no se lee.
    assert out.count("Este archivo lee el micrófono.") == 1 and out.count("[Para la explicación completa") == 1
    assert "Luego llama a Whisper.\n\n[Para la explicación completa: explica a.py a fondo.]\n" in out
    assert getattr(brain, "action_stream", None) is None


def test_sin_voz_nada_cambia(capsys):
    brain = StreamingBrain()

    launcher.interactive_mode(brain, read=patient(["explica a.py", "salir"], session([])[0]))

    assert brain.streams == [False]
    assert ("".join(PARTS) + FOOTER + "\n") in capsys.readouterr().out


@pytest.mark.parametrize("response, streamed, rest", [
    ("hola", "", "hola"),
    ("hola", "hola", ""),
    ("hola\n\n[aviso]", "hola", "\n\n[aviso]"),
    ("otra cosa", "hola", "\notra cosa"),
])
def test_rest_of(response, streamed, rest):
    assert launcher.rest_of(response, streamed) == rest
