"""Lectura frase por frase (J2): suena mientras se escribe; Enter, Ctrl+C o escuchar la cortan."""
import signal
import threading

import numpy as np
import pytest

import launcher
from core import timing
from core.timing import Timings, summary
from core.voice.reading import Reading, SentenceSplitter
from test_launcher import FakeBrain, reader
from test_voice_input import FakeSpeaker, FakeTTS, session, silence, speech
from test_voice_output import patient


def split(*chunks):
    splitter = SentenceSplitter()
    parts = [part for chunk in chunks for part in splitter.feed(chunk)]
    return parts, splitter.flush()


class BlockingSpeaker(FakeSpeaker):
    """Cada frase "suena" hasta stop(); con blocking=False, al momento."""

    def __init__(self, blocking=True):
        super().__init__()
        self.blocking = blocking
        self.playing = threading.Event()
        self.current = threading.Event()
        self.stops = 0

    def play(self, audio, rate):
        self.played.append((len(audio), rate))
        self.current = threading.Event()
        self.playing.set()

        if self.blocking:
            self.current.wait(5)

    def stop(self):
        self.stops += 1
        self.current.set()


class StreamingRouter:
    """Escribe frase a frase; antes de la última espera a que suene la primera."""

    def __init__(self, chunks, speaker=None):
        self.chunks = chunks
        self.speaker = speaker
        self.sounded_before_end = None

    def chat(self, prompt, on_chunk=None, history_prompt=None):
        for i, chunk in enumerate(self.chunks):
            if i == len(self.chunks) - 1 and self.speaker is not None:
                self.sounded_before_end = self.speaker.playing.wait(5)

            on_chunk(chunk)

        return "".join(self.chunks)


# --- Cortar en frases ------------------------------------------------------------

def test_corta_cada_frase_en_cuanto_termina():
    parts, rest = split("Un grafo bipar", "tito tiene dos lados. Las aris", "tas van de uno al otro. Fin")

    assert parts == ["Un grafo bipartito tiene dos lados.", " Las aristas van de uno al otro."]
    assert rest == " Fin"


def test_no_corta_numeros_listas_ni_archivos():
    parts, rest = split("Pesa 3.5 GB. ", "1. Abre brain.py y mira. ", "2. Listo")

    assert parts == ["Pesa 3.5 GB.", " 1. Abre brain.py y mira."]
    assert rest == " 2. Listo"


def test_espera_a_que_se_cierre_el_bloque_de_codigo():
    parts, _ = split("Usa esto:\n```\nx = 1. ", "y = 2\n", "```\nY listo. ")

    # Nada dentro del bloque: el bloque entero va en un solo tramo.
    assert parts[0] == "Usa esto:\n"
    assert "```\nx = 1. y = 2\n```\n" in "".join(parts[1:])
    assert not any(part.startswith("x = 1") for part in parts)


def test_una_fila_de_tabla_no_se_corta_por_un_punto():
    parts, _ = split("| a. b | c. d |\n", "Sigue. ")

    assert parts == ["| a. b | c. d |\n", "Sigue."]


# --- Leer en orden -----------------------------------------------------------------

def test_lee_en_orden_y_dice_lo_del_codigo_al_final():
    tts, speaker = FakeTTS(), FakeSpeaker()
    reading = Reading(tts, speaker)

    for chunk in ["Primera. ", "Segunda.\n```\nx = 1\n```\n", "Tercera."]:
        reading.feed(chunk)

    reading.finish("Primera. Segunda.\n```\nx = 1\n```\nTercera.")
    assert reading.wait(5)

    assert tts.texts == ["Primera.", "Segunda.", "Tercera.", "Te dejo el código en pantalla."]
    assert reading.spoken == tts.texts and len(speaker.played) == 4


def test_genera_la_siguiente_mientras_suena_la_anterior():
    tts, speaker = FakeTTS(), BlockingSpeaker()
    reading = Reading(tts, speaker)

    reading.feed("Primera. Segunda. ")
    assert speaker.playing.wait(5)

    # La primera sigue sonando y la segunda ya está generada.
    for _ in range(100):
        if len(tts.texts) == 2:
            break
        threading.Event().wait(0.01)

    assert tts.texts == ["Primera.", "Segunda."] and len(speaker.played) == 1
    reading.stop()


def test_stop_corta_y_vacia_la_cola():
    tts, speaker = FakeTTS(), BlockingSpeaker()
    reading = Reading(tts, speaker)

    reading.feed("Una. Dos. Tres. Cuatro. ")
    assert speaker.playing.wait(5)
    reading.stop()
    reading.feed("Cinco. ")
    reading.finish()

    assert reading.wait(5) and not reading.active
    assert speaker.stops >= 1 and len(speaker.played) == 1
    assert reading.texts.qsize() <= 1 and "Cinco." not in tts.texts


def test_primer_audio_en_la_linea_de_tiempos():
    timings = Timings(start=0.0, intent=1.0, answered=9.0, first_audio=2.4)

    assert "total 9,0 s · primer audio 2,4 s" in summary(timings)


# --- En el modo interactivo ------------------------------------------------------

def voice_brain(chunks, speaker=None, **settings):
    brain = FakeBrain(None, stream_output=True, **{launcher.VOICE_SETTING: True, **settings})
    brain.provider_router = StreamingRouter(chunks, speaker)
    return brain


def test_la_primera_frase_suena_antes_de_que_termine_la_respuesta(capsys):
    voice, _ = session([])
    voice._speaker = speaker = BlockingSpeaker(blocking=False)
    brain = voice_brain(["Un grafo bipartito tiene dos lados. ", "Las aristas cruzan. ", "Fin."], speaker,
                        **{timing.SETTING: True})

    launcher.interactive_mode(brain, read=patient(["qué es un grafo bipartito", "salir"], voice), voice=voice)

    assert brain.provider_router.sounded_before_end is True
    assert voice.tts.texts == ["Un grafo bipartito tiene dos lados.", "Las aristas cruzan.", "Fin."]
    [line] = [l for l in capsys.readouterr().err.splitlines() if l.startswith("[tiempos]")]
    assert " · primer audio " in line


def test_una_linea_nueva_corta_la_lectura():
    voice, _ = session([])
    voice._speaker = speaker = BlockingSpeaker()
    brain = voice_brain(["Una. ", "Dos. ", "Tres."])
    lines = ["hola", "otra", "salir"]
    sent = []

    def read(prompt):
        # Después de la primera, cada línea llega mientras suena "Una.".
        if sent:
            assert speaker.playing.wait(5)
            speaker.playing.clear()

        sent.append(lines[len(sent)])
        return sent[-1]

    launcher.interactive_mode(brain, read=read, voice=voice)

    # Cada línea cortó la lectura: no sonó el resto.
    assert speaker.stops >= 2 and len(speaker.played) == 2
    assert brain.processed == ["hola", "otra"]


def test_enter_mientras_escribe_corta_la_lectura(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "enter_pressed", lambda: True)
    voice, _ = session([])
    brain = voice_brain(["Una. ", "Dos. ", "Tres."])

    launcher.interactive_mode(brain, read=patient(["hola", "salir"], voice), voice=voice)

    out = capsys.readouterr()
    assert "(Lectura cortada.)" in out.err
    # La respuesta se escribe entera.
    assert "Una. Dos. Tres." in out.out
    assert len(voice.tts.texts) <= 1


def test_ctrl_c_en_el_prompt_corta_la_lectura_y_asia_sigue(capsys):
    voice, _ = session([])
    voice._speaker = speaker = BlockingSpeaker()
    brain = voice_brain(["Una. ", "Dos."])
    lines = iter(["hola", KeyboardInterrupt, "otra", "salir"])

    def read(prompt):
        line = next(lines)

        if line is KeyboardInterrupt:
            assert speaker.playing.wait(5)
            raise KeyboardInterrupt

        return line

    launcher.interactive_mode(brain, read=read, voice=voice)

    out = capsys.readouterr()
    assert brain.processed == ["hola", "otra"]
    assert "(Lectura cortada.)" in out.err and speaker.stops >= 1


def test_ctrl_c_sin_lectura_cierra_asia(capsys):
    def read(prompt):
        raise KeyboardInterrupt

    launcher.interactive_mode(FakeBrain("hecho"), read=read)

    assert capsys.readouterr().out.rstrip().endswith("Asia apagada.")


def test_ctrl_c_mientras_escribe_corta_la_lectura_no_la_respuesta():
    reading = Reading(FakeTTS(), BlockingSpeaker())
    reading.feed("Una. ")

    with launcher.ctrl_c_stops(reading):
        signal.raise_signal(signal.SIGINT)

    assert not reading.active

    # Sin nada sonando, Ctrl+C es Ctrl+C.
    with pytest.raises(KeyboardInterrupt), launcher.ctrl_c_stops(reading):
        signal.raise_signal(signal.SIGINT)


def test_volver_a_escuchar_corta_la_lectura():
    voice, _ = session(speech(1) + silence(1))
    voice._speaker = speaker = BlockingSpeaker()
    reading = voice.start_reading()
    reading.feed("Una. Dos. ")
    assert speaker.playing.wait(5)

    voice.listen()

    assert not reading.active and speaker.stops >= 1


def test_jarvis_voz_con_mensaje_lee_todo_y_espera():
    voice, _ = session([])

    spoken = voice.speak("Hola. ¿Qué tal?")

    assert voice.tts.texts == ["Hola.", "¿Qué tal?"]
    assert spoken.text == "Hola. ¿Qué tal?" and len(voice.speaker.played) == 2
