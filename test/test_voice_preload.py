"""La voz de Piper se precarga al activar /voz: la primera lectura no detiene los tokens."""
import threading

import launcher
from core.voice import DEFAULT_VOICE_SETTINGS
from core.voice.tts import PiperTTS
from test_launcher import FakeBrain, reader
from test_voice_input import FakeTTS, session
from test_voice_output import patient


class LoadingTTS(FakeTTS):
    def __init__(self):
        super().__init__()
        self.loads = []

    def load(self):
        self.loads.append(threading.current_thread().name)


def voice_session():
    voice, _ = session([])
    voice._tts = LoadingTTS()
    return voice


def test_con_voz_desde_el_arranque_se_precarga_en_otro_hilo():
    voice = voice_session()
    brain = FakeBrain("hecho", **{launcher.VOICE_SETTING: True})

    launcher.interactive_mode(brain, read=patient(["salir"], voice), voice=voice)
    voice.voice_preload.join(5)

    assert voice._tts.loads == ["asia-voz"]


def test_al_activarla_en_la_sesion_se_precarga_antes_del_siguiente_prompt():
    voice = voice_session()
    brain = FakeBrain("hecho")
    process = brain.process

    def turning_on(text):
        brain.settings.values[launcher.VOICE_SETTING] = True
        return process(text)

    brain.process = turning_on

    launcher.interactive_mode(brain, read=reader(["/voz", "salir"]), voice=voice)
    voice.voice_preload.join(5)

    assert voice._tts.loads == ["asia-voz"]


def test_sin_voz_no_precarga():
    voice = voice_session()

    launcher.interactive_mode(FakeBrain("hecho"), read=reader(["hola", "salir"]), voice=voice)

    assert voice.voice_preload is None and voice._tts.loads == []


def test_se_precarga_una_vez_y_liberar_permite_otra():
    voice = voice_session()
    tts = voice._tts

    first = voice.preload_voice()

    assert voice.preload_voice() is first
    first.join(5)
    voice.unload()
    assert voice.voice_preload is None and tts.loads == ["asia-voz"]


def test_un_fallo_de_la_precarga_no_se_muestra(capsys):
    class Broken(FakeTTS):
        def load(self):
            raise RuntimeError("falta la voz")

    voice, _ = session([])
    voice._tts = Broken()

    voice.preload_voice().join(5)

    assert capsys.readouterr().err == ""


def test_piper_carga_una_sola_vez_aunque_lleguen_dos_a_la_vez(monkeypatch):
    tts = PiperTTS(DEFAULT_VOICE_SETTINGS)
    reads = []

    def read_voice():
        reads.append(1)
        threading.Event().wait(0.05)
        return "voz"

    monkeypatch.setattr(tts, "read_voice", read_voice)
    threads = [threading.Thread(target=tts.load) for _ in range(3)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    assert reads == [1] and tts.voice == "voz"
