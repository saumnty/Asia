"""/voz, /sin voz, --voz y los tiempos de voz en --timing (J1, paso 5)."""
import pytest

import launcher
from config.settings_manager import SettingsManager
from core import timing
from core.actions.voice import VOICE_SETTING
from core.commands import COMMANDS, options_text, resolve
from core.timing import Timings, summary
from core.voice.session import Heard
from test_confidencial import TTY, make_brain
from test_launcher import reader
from test_voice_input import session, silence, speech


@pytest.mark.parametrize("text, phrase", [("/voz", "activa la voz"), ("/sin voz", "desactiva la voz")])
def test_en_la_tabla_de_opciones(text, phrase):
    assert resolve(text).phrase == phrase
    assert any(c.slash == text and c.group == "voz" for c in COMMANDS)
    assert text in options_text()


@pytest.mark.parametrize("on, off", [("/voz", "/sin voz"), ("activa la voz", "desactiva la voz")])
def test_comandos_activan_y_quitan_la_voz(capsys, on, off):
    brain = make_brain()
    lines = iter([on, "salir"])

    launcher.interactive_mode(brain, read=lambda prompt: next(lines))

    assert SettingsManager.overrides[VOICE_SETTING] is True
    assert "Voz activada" in capsys.readouterr().out

    brain.process(off)
    assert VOICE_SETTING not in SettingsManager.overrides


def test_flag_voz():
    SettingsManager.set_overrides(launcher.session_overrides(launcher.build_parser().parse_args(["--voz"]), None))

    assert SettingsManager().get(VOICE_SETTING) is True


def test_help_documenta_voz(capsys):
    with pytest.raises(SystemExit):
        launcher.build_parser().parse_args(["--help"])

    out = capsys.readouterr().out
    assert "--voz" in out and "/voz" in out and "/sin voz" in out


def test_arranque_dice_que_la_voz_esta_activa():
    SettingsManager.set_overrides({VOICE_SETTING: True})

    assert "Voz activa: pulsa Enter en una línea vacía y habla." in launcher.startup_message(SettingsManager())
    SettingsManager.set_overrides({})
    assert "Voz activa" not in launcher.startup_message(SettingsManager())


def test_sin_voz_libera_los_modelos():
    from test_launcher import FakeBrain

    class Toggling(FakeBrain):
        def process(self, text):
            self.processed.append(text)
            self.settings.values[VOICE_SETTING] = None
            return "Voz desactivada."

    brain = Toggling(**{VOICE_SETTING: True})
    voice, _ = session([])
    voice.stt  # ya cargado
    unloaded = []
    voice.unload = lambda: unloaded.append(True)

    launcher.interactive_mode(brain, read=reader(["/sin voz", "hola", "salir"]), voice=voice)

    assert unloaded == [True]


# --- Tiempos -----------------------------------------------------------------------

def test_linea_con_voz_a_texto_y_texto_a_voz():
    timings = Timings(start=0.0, intent=1.0, stt=(2.5, 3.1), tts=(1.1, 8.4), answered=5.0)

    line = summary(timings)

    assert line.startswith("[tiempos] voz a texto 2,5 s (3,1 s de audio) · intención 1,0 s")
    # El total es hasta que la respuesta está en pantalla, sin la lectura.
    assert "total 5,0 s · texto a voz 1,1 s (8,4 s de audio)" in line


def test_sin_voz_la_linea_no_cambia():
    line = summary(Timings(start=0.0, intent=1.0), now=2.0)

    assert line == "[tiempos] intención 1,0 s · total 2,0 s · sin modelo"


def test_timing_en_modo_voz_de_punta_a_punta(capsys):
    from test_launcher import FakeBrain

    brain = FakeBrain("Hecho.", **{VOICE_SETTING: True, timing.SETTING: True})
    voice, _ = session(speech(1) + silence(1), text="hola")

    launcher.interactive_mode(brain, read=reader(["", "salir"]), voice=voice)

    [line] = [l for l in capsys.readouterr().err.splitlines() if l.startswith("[tiempos]")]
    # La línea espera a que suene la primera frase.
    assert line.startswith("[tiempos] voz a texto ") and " · primer audio " in line


def test_respond_registra_lo_oido(capsys):
    from test_launcher import FakeBrain

    brain = FakeBrain("Hecho.", **{timing.SETTING: True})
    heard = Heard("hola", "fin", audio_seconds=1.5, stt_seconds=0.7)

    assert launcher.respond(brain, "hola", heard=heard) == "Hecho."
    assert "[tiempos] voz a texto 0,7 s (1,5 s de audio)" in capsys.readouterr().err


def test_jarvis_voz_con_mensaje_lee_la_respuesta(monkeypatch, capsys):
    from core.voice import session as voice_session

    spoken = []
    monkeypatch.setattr(voice_session.VoiceSession, "speak", lambda self, answer: spoken.append(answer))
    brain = make_brain()

    launcher.main(["--voz", "/opciones"], stdin=TTY, brain_factory=lambda: brain)

    assert spoken and "Comandos de sesión" in spoken[0]
