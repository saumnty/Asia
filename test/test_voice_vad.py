"""VAD: ruido suelto, recorte del audio para Whisper y "/calibrar voz" (sin micrófono real)."""
import numpy as np
import pytest

import launcher
from core.brain import CALIBRATE_ONLY_INTERACTIVE
from core.commands import COMMANDS, options_text, resolve
from core.timing import Timings, summary
from core.voice.session import calibrated_threshold
from core.voice.vad import SPEAKING, WAITING, EndOfSpeech
from test_confidencial import make_brain
from test_launcher import FakeBrain, reader
from test_voice_input import PER_SECOND, session, silence, speech


def test_un_golpe_suelto_no_abre_la_frase():
    detector = EndOfSpeech(start_timeout_s=10)

    states = [detector.feed(p) for p in [0.9, 0.0, 0.9, 0.0] * 20]

    assert set(states) == {WAITING} and detector.first_speech is None


def test_la_voz_abre_la_frase_y_se_anota_donde_empieza():
    detector = EndOfSpeech()

    states = [detector.feed(p) for p in silence(1) + speech(1)]

    assert states[-1] == SPEAKING
    assert detector.first_speech == len(silence(1))


def test_a_whisper_no_le_llega_la_espera_ni_el_silencio_final():
    # 4 s de espera antes de hablar (como al pulsar Enter y pensar la frase).
    voice, stt = session(silence(4) + speech(1.5) + silence(1))

    heard = voice.listen()

    [audio] = stt.audio
    assert heard.recorded_seconds > 6
    assert len(audio) / 16000 == pytest.approx(1.5 + 0.6, abs=0.1)
    # Lo que se pasa a Whisper empieza 0,3 s antes de la voz.
    assert audio[0] == 0.0 and np.count_nonzero(audio[:int(0.25 * 16000)]) == 0


def test_tiempos_dicen_cuanto_se_grabo_si_es_mucho_mas():
    long = summary(Timings(start=0.0, intent=1.0, stt=(2.5, 2.1, 7.4), answered=5.0))
    short = summary(Timings(start=0.0, intent=1.0, stt=(2.5, 2.1, 2.8), answered=5.0))

    assert "voz a texto 2,5 s (2,1 s de audio de 7,4 s grabados)" in long
    assert "voz a texto 2,5 s (2,1 s de audio)" in short


# --- Calibrar ----------------------------------------------------------------------

def test_umbral_solo_sube_si_el_ruido_parece_voz():
    assert calibrated_threshold([0.02] * 50, 0.5) == 0.5
    assert calibrated_threshold([0.6] * 50, 0.5) == 0.75
    assert calibrated_threshold([0.99] * 50, 0.5) == 0.9
    # Nunca baja.
    assert calibrated_threshold([0.0] * 50, 0.7) == 0.7


def test_calibrar_mide_el_ruido_y_ajusta_la_sesion():
    voice, _ = session([0.6] * (4 * PER_SECOND))

    result = voice.calibrate(seconds=3)

    assert result.threshold_before == 0.5 and result.threshold == 0.75
    assert result.over_threshold == 1.0
    assert voice.config["vad_threshold"] == 0.75
    # Con el umbral nuevo, ese ruido ya no abre la frase.
    assert EndOfSpeech.from_config(voice.config).feed(0.6) == WAITING


def test_comando_en_la_tabla():
    assert any(c.slash == "/calibrar voz" and c.group == "voz" for c in COMMANDS)
    assert "/calibrar voz" in options_text()
    assert resolve("/calibrar voz").command.special == "calibrar"


@pytest.mark.parametrize("text", ["/calibrar voz", "calibra la voz"])
def test_en_el_modo_interactivo_calibra(capsys, text):
    brain = FakeBrain("hecho")
    voice, _ = session([0.6] * (4 * PER_SECOND))

    launcher.interactive_mode(brain, read=reader([text, "salir"]), voice=voice)

    out = capsys.readouterr()
    assert brain.processed == []
    assert "Umbral de voz para esta sesión: 0,75." in out.out
    assert "[Calibrando" in out.err


def test_sin_ruido_no_cambia(capsys):
    brain = FakeBrain("hecho")
    voice, _ = session([0.01] * (4 * PER_SECOND))

    launcher.interactive_mode(brain, read=reader(["/calibrar voz", "salir"]), voice=voice)

    assert "ya deja fuera ese ruido; no lo cambio" in capsys.readouterr().out
    assert voice.config["vad_threshold"] == 0.5


def test_fuera_del_modo_interactivo_lo_explica():
    assert make_brain().process("/calibrar voz") == CALIBRATE_ONLY_INTERACTIVE
