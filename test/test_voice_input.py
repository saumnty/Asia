"""Voz a texto (J1, paso 3) con audio simulado y motores falsos: sin modelos reales."""
from contextlib import contextmanager

import numpy as np
import pytest

import launcher
from config.settings_manager import SettingsManager, read_json
from core.paths import DEFAULTS_FILE
from core.voice import DEFAULT_VOICE_SETTINGS, build_stt, voice_settings
from core.voice.audio import FRAME
from core.voice.session import VoiceSession
from core.voice.stt import FasterWhisperSTT, MissingModel
from core.voice.vad import DONE, NO_SPEECH, SPEAKING, TOO_LONG, WAITING, EndOfSpeech, SileroVAD
from test_launcher import FakeBrain, reader

# Tramos de 32 ms: 25 por segundo (más o menos).
PER_SECOND = 16000 // FRAME


class FakeMicrophone:
    """Devuelve un tramo por probabilidad; el valor del tramo es su probabilidad."""

    def __init__(self, probabilities):
        self.probabilities = probabilities

    @contextmanager
    def open(self):
        yield (np.full(FRAME, p, dtype=np.float32) for p in self.probabilities)


class FakeVAD:
    def reset(self):
        pass

    def probability(self, frame):
        return float(frame[0])


class FakeSTT:
    def __init__(self, text="hola asia"):
        self.text = text
        self.audio = []

    def transcribe(self, audio):
        self.audio.append(audio)
        return self.text


def session(probabilities, text="hola asia", **voice):
    SettingsManager.set_overrides({"voice": {**DEFAULT_VOICE_SETTINGS, **voice}})
    stt = FakeSTT(text)
    return VoiceSession(SettingsManager(), stt=stt, microphone=FakeMicrophone(probabilities), vad=FakeVAD()), stt


def speech(seconds):
    return [0.9] * int(seconds * PER_SECOND)


def silence(seconds):
    return [0.0] * int(seconds * PER_SECOND)


# --- Fin de frase ------------------------------------------------------------------

def test_fin_de_frase_por_silencio():
    detector = EndOfSpeech(silence_ms=800)
    states = [detector.feed(p) for p in silence(0.5) + speech(1) + silence(1)]

    assert states[0] == WAITING and SPEAKING in states and states[-1] == DONE
    # Termina a los ~800 ms de silencio, no antes.
    assert states.index(DONE) >= len(silence(0.5) + speech(1)) + 24


def test_sin_voz_y_demasiado_larga():
    assert EndOfSpeech(start_timeout_s=1).feed(0.0) == WAITING
    detector = EndOfSpeech(start_timeout_s=1)
    assert [detector.feed(p) for p in silence(1.1)][-1] == NO_SPEECH

    detector = EndOfSpeech(max_seconds=2)
    assert [detector.feed(p) for p in speech(2.1)][-1] == TOO_LONG


# --- Escuchar ----------------------------------------------------------------------

def test_escucha_hasta_el_silencio_y_transcribe():
    voice, stt = session(silence(0.3) + speech(1.5) + silence(1) + speech(5))

    heard = voice.listen()

    assert heard.text == "hola asia" and heard.reason == DONE
    # Se cortó en el silencio: los 5 s de después no se grabaron.
    assert 2.5 < heard.audio_seconds < 3.0
    [audio] = stt.audio
    assert audio.dtype == np.float32 and audio.ndim == 1


def test_enter_termina_la_frase():
    voice, stt = session(speech(10))
    frames = iter(range(1000))

    heard = voice.listen(stop_requested=lambda: next(frames) >= 25)

    assert heard.reason == "enter" and heard.text == "hola asia"
    assert heard.audio_seconds < 1.1


def test_sin_voz_no_transcribe():
    voice, stt = session(silence(10), start_timeout_s=1)

    heard = voice.listen()

    assert heard.text == "" and heard.reason == NO_SPEECH and stt.audio == []


def test_motores_se_crean_al_primer_uso():
    voice = VoiceSession(SettingsManager())

    assert voice._stt is None and voice._vad is None and voice._microphone is None


# --- En el modo interactivo ------------------------------------------------------

def test_enter_en_linea_vacia_escucha_y_procesa_como_tecleado(capsys):
    SettingsManager.set_overrides({launcher.VOICE_SETTING: True})
    brain = FakeBrain("hecho", **{launcher.VOICE_SETTING: True})
    voice, _ = session(speech(1) + silence(1), text="muestra el proyecto activo")

    launcher.interactive_mode(brain, read=reader(["", "salir"]), voice=voice)

    assert brain.processed == ["muestra el proyecto activo"]
    out = capsys.readouterr()
    # Se muestra como si se hubiera escrito.
    assert "Tú: muestra el proyecto activo" in out.out
    assert "[Escuchando" in out.err


def test_lo_dictado_lleva_la_etiqueta_usuario(monkeypatch):
    from core.provenance import USUARIO, current_fragments

    labels = []
    brain = FakeBrain(None, **{launcher.VOICE_SETTING: True})
    original = brain.process

    def process(text):
        labels.extend(f.label for f in current_fragments())
        return original(text)

    brain.process = process
    voice, _ = session(speech(1) + silence(1), text="qué hora es")

    launcher.interactive_mode(brain, read=reader(["", "salir"]), voice=voice)

    assert labels == [USUARIO]


def test_salir_dictado_cierra(capsys):
    brain = FakeBrain("hecho", **{launcher.VOICE_SETTING: True})
    voice, _ = session(speech(1) + silence(1), text="salir")

    launcher.interactive_mode(brain, read=reader(["", "hola"]), voice=voice)

    assert brain.processed == []
    assert capsys.readouterr().out.rstrip().endswith("Asia apagada.")


def test_sin_modo_voz_la_linea_vacia_no_escucha():
    brain = FakeBrain("hecho")
    voice, stt = session(speech(1) + silence(1))

    launcher.interactive_mode(brain, read=reader(["", "salir"]), voice=voice)

    assert brain.processed == [] and stt.audio == []


def test_no_oi_nada_vuelve_al_prompt(capsys):
    brain = FakeBrain("hecho", **{launcher.VOICE_SETTING: True})
    voice, _ = session(silence(10), start_timeout_s=1)

    launcher.interactive_mode(brain, read=reader(["", "salir"]), voice=voice)

    assert brain.processed == []
    assert "No te oí" in capsys.readouterr().err


def test_error_del_microfono_no_cierra_asia(capsys):
    class Broken:
        def listen(self, stop):
            raise OSError("no hay micrófono")

    brain = FakeBrain("hecho", **{launcher.VOICE_SETTING: True})

    launcher.interactive_mode(brain, read=reader(["", "hola", "salir"]), voice=Broken())

    assert brain.processed == ["hola"]
    assert "No pude escuchar: no hay micrófono" in capsys.readouterr().err


# --- Motores ---------------------------------------------------------------------

def test_config_de_voz_en_defaults():
    voice = read_json(DEFAULTS_FILE)["voice"]

    assert voice["stt_engine"] == "faster_whisper" and voice["stt_model"] == "small"
    assert voice["stt_compute_type"] == "int8" and voice["tts_voice"] == "es_MX-claude-high"
    assert "stt_device" not in voice


def test_motor_desconocido():
    SettingsManager.set_overrides({"voice": {"stt_engine": "otro"}})

    with pytest.raises(ValueError, match="otro"):
        build_stt(SettingsManager())


def test_motor_por_config():
    SettingsManager.set_overrides({"voice": {"stt_engine": "falso"}})

    assert isinstance(build_stt(SettingsManager(), engines={"falso": lambda config: FakeSTT()}), FakeSTT)


def test_whisper_siempre_en_cpu(tmp_path, monkeypatch):
    import faster_whisper

    (tmp_path / "faster-whisper-small").mkdir()
    (tmp_path / "faster-whisper-small" / "model.bin").write_bytes(b"x")
    created = {}
    monkeypatch.setattr(faster_whisper, "WhisperModel", lambda path, **kwargs: created.update(kwargs) or "modelo")

    stt = FasterWhisperSTT({**DEFAULT_VOICE_SETTINGS, "models_dir": str(tmp_path), "stt_device": "cuda"})
    stt.load()

    assert created["device"] == "cpu" and created["compute_type"] == "int8"
    assert created["local_files_only"] is True


def test_modelo_que_falta_dice_como_descargarlo(tmp_path):
    stt = FasterWhisperSTT({**DEFAULT_VOICE_SETTINGS, "models_dir": str(tmp_path)})

    with pytest.raises(MissingModel, match="download_model"):
        stt.load()


def test_silero_real_distingue_silencio():
    # El ONNX de Silero viene con faster-whisper (1,25 MB): no descarga nada.
    vad = SileroVAD()

    assert vad.probability(np.zeros(FRAME, dtype=np.float32)) < 0.2


def test_voice_settings_completa_lo_que_falta():
    assert voice_settings(type("S", (), {"get": lambda self, k, d=None: None})()) == DEFAULT_VOICE_SETTINGS
