"""Palabra de activación (fase J3): core/voice/wake.py, "/escucha" y el launcher, sin micrófono ni modelo real."""
import threading
from collections import deque
from contextlib import contextmanager

import numpy as np
import pytest

import launcher
from config.settings_manager import SettingsManager
from core.actions.voice import VOICE_SETTING, WAKE_SETTING
from core.voice import wake
from core.voice.wake import Activations, Chunker, WakeListener, missing, model_files
from test_launcher import FakeBrain, FakeSettings


# --- Tramos y activaciones -------------------------------------------------------

def test_junta_los_tramos_del_microfono_en_80_ms_int16():
    chunker = Chunker()

    assert chunker.feed(np.full(512, 0.5, dtype=np.float32)) == []
    assert chunker.feed(np.full(512, 0.5, dtype=np.float32)) == []
    chunks = chunker.feed(np.full(512, 2.0, dtype=np.float32))

    assert len(chunks) == 1 and chunks[0].dtype == np.int16 and len(chunks[0]) == 1280
    assert chunks[0][0] == 16383 and chunks[0][-1] == 32767 and len(chunker.pending) == 256


def test_una_frase_cuenta_una_vez_aunque_dispare_varios_tramos():
    found = Activations(threshold=0.5, refractory_s=2.0, chunk_s=0.08)

    fired = [found.feed(score) for score in [0.1, 0.9, 0.95, 0.8] + [0.0] * 30 + [0.7]]

    assert fired.count(True) == 2 and found.times == pytest.approx([0.08, 34 * 0.08])
    assert found.peak == 0.95


def test_bajo_el_umbral_no_activa():
    found = Activations(threshold=0.6)

    assert not any(found.feed(score) for score in [0.2, 0.59, 0.4]) and found.times == []


# --- Modelos ----------------------------------------------------------------------

def test_los_modelos_van_en_wake_models_dir(tmp_path):
    files = model_files({"wake_models_dir": str(tmp_path), "wake_word": "hey_jarvis_v0.1"})

    assert files["word"] == tmp_path / "hey_jarvis_v0.1.onnx" and files["melspec"] == tmp_path / "melspectrogram.onnx"
    assert model_files({"wake_word": "C:/x/oye_asia.onnx"})["word"].name == "oye_asia.onnx"


def test_dice_que_modelos_faltan(tmp_path):
    for name in ("melspectrogram", "embedding_model"):
        (tmp_path / f"{name}.onnx").write_bytes(b"x")

    config = {"wake_models_dir": str(tmp_path), "wake_word": "hey_jarvis_v0.1", "wake_vad_threshold": 0.0}
    assert "hey_jarvis_v0.1.onnx" in missing(config) and "silero_vad" not in missing(config)

    (tmp_path / "hey_jarvis_v0.1.onnx").write_bytes(b"x")
    assert missing(config) == ""
    assert "silero_vad.onnx" in missing({**config, "wake_vad_threshold": 0.5})


# --- WakeListener -----------------------------------------------------------------

class FakeModel:
    """Puntuación 0 hasta el tramo número fire_at; luego 0,9."""

    def __init__(self, fire_at=None):
        self.fire_at = fire_at
        self.chunks = 0
        self.resets = 0

    def reset(self):
        self.resets += 1

    def predict(self, chunk):
        self.chunks += 1
        return {"hey_jarvis_v0.1": 0.9 if self.fire_at is not None and self.chunks >= self.fire_at else 0.0}


class FakeMicrophone:
    """Tramos de silencio mientras está abierto; frames=None, sin fin."""

    def __init__(self, frames=None):
        self.frames = frames
        self.opened = 0
        self.is_open = False
        self.closed = threading.Event()

    @contextmanager
    def open(self):
        self.opened += 1
        self.is_open = True

        def stream():
            count = 0

            while self.frames is None or count < self.frames:
                count += 1
                yield np.zeros(512, dtype=np.float32)
                # Como el micrófono de verdad, que da un tramo cada 32 ms.
                threading.Event().wait(0.001)

        try:
            yield stream()
        finally:
            self.is_open = False
            self.closed.set()


def test_al_oir_la_palabra_suelta_el_microfono_y_avisa():
    microphone = FakeMicrophone()
    seen = []
    listener = WakeListener(FakeModel(fire_at=3), microphone, 0.5, lambda: seen.append(microphone.is_open)).start()

    assert listener.heard.wait(5)
    listener.stop()
    # on_wake llega con el micrófono ya cerrado: lo abre Whisper.
    assert seen == [False] and microphone.opened == 1


class FakeVad:
    def __init__(self):
        self.prediction_buffer = deque([0.9, 0.8], maxlen=125)
        self.resets = 0

    def reset_states(self):
        self.resets += 1


def test_cada_escucha_empieza_con_el_vad_vacio():
    model = FakeModel()
    model.vad, model.vad_threshold = FakeVad(), 0.5
    listener = WakeListener(model, FakeMicrophone(frames=3), 0.5, lambda: None)

    assert listener.listen_once() is False
    # Con las puntuaciones viejas del VAD, la primera frase se filtraba (o no) por audio de antes.
    assert model.resets == 1 and model.vad.resets == 1 and list(model.vad.prediction_buffer) == []


def test_sin_vad_solo_reinicia_el_modelo():
    model = FakeModel()
    model.vad, model.vad_threshold = FakeVad(), 0.0

    wake.reset_model(model)

    assert model.resets == 1 and model.vad.resets == 0


def test_stop_corta_la_escucha_sin_avisar():
    microphone = FakeMicrophone()
    seen = []
    listener = WakeListener(FakeModel(), microphone, 0.5, lambda: seen.append("despierta")).start()

    listener.stop()

    assert not listener.thread.is_alive() and microphone.closed.is_set() and seen == []


def test_no_escucha_mientras_asia_lee_en_voz_alta():
    microphone = FakeMicrophone()
    speaking = threading.Event()
    speaking.set()
    listener = WakeListener(FakeModel(fire_at=3), microphone, 0.5, lambda: None, paused=speaking.is_set).start()

    # Mientras suena, ni abre el micrófono.
    assert not listener.heard.wait(0.3) and microphone.opened == 0

    speaking.clear()
    assert listener.heard.wait(5) and microphone.opened == 1
    listener.stop()


# --- "/escucha" -------------------------------------------------------------------

def brain_with_voice_actions():
    from core.brain import Brain

    brain = Brain.__new__(Brain)
    brain.settings = SettingsManager()
    return brain


def test_escucha_activa_la_voz_y_la_palabra(monkeypatch):
    monkeypatch.setattr(wake, "missing", lambda config: "")

    answer = brain_with_voice_actions().handle_voice_command("wake_on")

    assert "«Hey Jarvis»" in answer
    assert SettingsManager().get(WAKE_SETTING) is True and SettingsManager().get(VOICE_SETTING) is True


def test_escucha_sin_modelos_dice_que_falta(monkeypatch):
    monkeypatch.setattr(wake, "missing", lambda config: "Falta openwakeword: ...")

    answer = brain_with_voice_actions().handle_voice_command("wake_on")

    assert "Falta openwakeword" in answer and SettingsManager().get(WAKE_SETTING) is None


def test_sin_escucha_y_sin_voz_la_quitan():
    SettingsManager.set_overrides({VOICE_SETTING: True, WAKE_SETTING: True})
    brain = brain_with_voice_actions()

    brain.handle_voice_command("wake_off")
    assert SettingsManager().get(WAKE_SETTING) is None and SettingsManager().get(VOICE_SETTING) is True

    SettingsManager.set_overrides({VOICE_SETTING: True, WAKE_SETTING: True})
    brain.handle_voice_command("off")
    assert SettingsManager().get(WAKE_SETTING) is None and SettingsManager().get(VOICE_SETTING) is None


def test_los_comandos_de_escucha():
    from core.actions.voice import voice_command

    assert voice_command("activa la escucha") == "wake_on" and voice_command("desactiva la escucha") == "wake_off"


# --- Launcher ---------------------------------------------------------------------

def test_el_prompt_dice_que_espera_la_palabra():
    assert launcher.user_prompt(FakeSettings(**{WAKE_SETTING: True})) == "\nTú [esperando «Hey Jarvis»]: "
    assert launcher.user_prompt(FakeSettings()) == "\nTú: "


def test_una_interrupcion_antes_del_prompt_no_se_pierde():
    class Session:
        app = type("App", (), {"loop": None, "is_running": False})()

        def prompt(self, text):
            return "tecleado"

    reader = launcher.PromptReader(Session())
    reader.interrupt()

    assert reader("Tú: ") == launcher.WAKE_LINE and reader("Tú: ") == "tecleado"


class WakeVoice:
    """Una sesión de voz que oye la palabra en cuanto empieza a escuchar."""

    speaking = False

    def __init__(self, heard):
        self.heard = heard
        self.listened = 0
        self.started = 0

    def wake_listener(self, on_wake):
        voice = self

        class Listener:
            def start(self):
                voice.started += 1

                if voice.started == 1:
                    on_wake()

                return self

            def stop(self):
                pass

        return Listener()

    def listen(self, stop_requested):
        from core.voice.session import Heard

        self.listened += 1
        return Heard(self.heard, "done")

    def preload_voice(self):
        pass

    def stop_speaking(self):
        return False


class InterruptibleRead:
    """Como PromptReader: lo que manda interrupt() se devuelve en la siguiente lectura."""

    def __init__(self, lines):
        self.lines = list(lines)
        self.pending = None

    def interrupt(self, result=launcher.WAKE_LINE):
        self.pending = result

    def __call__(self, prompt=""):
        pending, self.pending = self.pending, None
        return pending if pending is not None else self.lines.pop(0)


def test_la_palabra_escucha_la_frase_y_la_manda(capsys):
    brain = FakeBrain(**{VOICE_SETTING: True, WAKE_SETTING: True})
    voice = WakeVoice("qué hora es")

    launcher.interactive_mode(brain, read=InterruptibleRead(["salir"]), voice=voice)

    err = capsys.readouterr().err
    assert "Escuchando…" in err and voice.listened == 1
    assert brain.processed == ["qué hora es"]



@pytest.mark.parametrize("inputs, chunks", [({"hey_jarvis_v0.1": 16}, 25), ({"oye_asia_v0.1": 23}, 32), (None, 25)])
def test_el_calentamiento_depende_de_la_entrada_del_modelo(inputs, chunks):
    model = FakeModel()

    if inputs is not None:
        model.model_inputs = inputs

    assert wake.warmup_chunks(model) == chunks
