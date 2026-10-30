"""Texto a voz (J1, paso 4): qué se lee y cuándo, con motores falsos. Ctrl+C y Enter: test_voice_reading.py."""
import numpy as np
import pytest

import launcher
from core.voice import DEFAULT_VOICE_SETTINGS, project_path
from core.voice.speakable import to_speakable
from core.voice.tts import MissingVoice, PiperTTS
from test_launcher import FakeBrain, reader
from test_voice_input import FakeSpeaker, FakeTTS, session, silence, speech


# --- Qué se lee ------------------------------------------------------------------

def test_quita_bloques_de_codigo_y_lo_dice():
    answer = "Puedes usar esta función:\n\n```python\ndef f():\n    return 1\n```\n\nDevuelve uno."

    assert to_speakable(answer) == "Puedes usar esta función: Devuelve uno. Te dejo el código en pantalla."


def test_quita_tablas_y_lo_dice():
    answer = "Comparación:\n\n| Modelo | t/s |\n|---|---|\n| 7B | 7 |\n\nEl 7B es más lento."

    assert to_speakable(answer) == "Comparación: El 7B es más lento. Te dejo la tabla en pantalla."


def test_codigo_y_tabla():
    answer = "Mira:\n```\nx = 1\n```\n| a | b |\n|---|---|"

    assert to_speakable(answer).endswith("Te dejo el código y la tabla en pantalla.")


def test_quita_markdown():
    answer = "## Resumen\n\n**Un grafo bipartito** tiene *dos* conjuntos.\n- Sin aristas dentro.\n1. Se colorea con dos colores"

    assert to_speakable(answer) == (
        "Resumen. Un grafo bipartito tiene dos conjuntos. Sin aristas dentro. Se colorea con dos colores."
    )


@pytest.mark.parametrize(
    "answer, expected",
    [
        (r"El error está en C:\Asia\core\brain.py, línea 3.", "El error está en línea 3."),
        ("Revisa core/actions/explore.py antes.", "Revisa antes."),
        ("Mira `launcher.py` y la función `respond`.", "Mira y la función respond."),
        ("Más en https://ollama.com/library y [la guía](https://x.y).", "Más en y la guía."),
    ],
)
def test_quita_rutas_urls_y_codigo_en_linea(answer, expected):
    assert to_speakable(answer) == expected


def test_solo_codigo():
    assert to_speakable("```\nprint(1)\n```") == "Te dejo el código en pantalla."


def test_vacio():
    assert to_speakable("") == ""


# --- Leer la respuesta --------------------------------------------------------------

def patient(lines, voice):
    """Como reader, pero cada línea llega cuando terminó de sonar la respuesta anterior.

    Una línea nueva corta la lectura (como Enter): sin esperar, no sonaría nada.
    """
    read = reader(lines)

    def patient_read(prompt):
        voice.wait_reading(5)
        return read(prompt)

    return patient_read


def test_lee_la_respuesta_y_la_muestra_entera(capsys):
    brain = FakeBrain("Hecho.\n```\nx = 1\n```", **{launcher.VOICE_SETTING: True})
    voice, _ = session(speech(1) + silence(1), text="arregla el archivo")

    launcher.interactive_mode(brain, read=patient(["", "salir"], voice), voice=voice)

    assert voice.tts.texts == ["Hecho.", "Te dejo el código en pantalla."]
    assert voice.speaker.played == [(2205, 22050)] * 2
    # En pantalla, la respuesta completa, con el código.
    assert "Hecho.\n```\nx = 1\n```" in capsys.readouterr().out


def test_tambien_lee_lo_tecleado_en_modo_voz():
    brain = FakeBrain("Proyecto activo: asia", **{launcher.VOICE_SETTING: True})
    voice, _ = session([])

    launcher.interactive_mode(brain, read=patient(["muestra el proyecto activo", "salir"], voice), voice=voice)

    assert voice.tts.texts == ["Proyecto activo: asia."]


def test_sin_modo_voz_no_lee():
    brain = FakeBrain("hola")
    voice, _ = session([])

    launcher.interactive_mode(brain, read=patient(["hola", "salir"], voice), voice=voice)

    assert voice.tts.texts == []


def test_chat_en_streaming_tambien_se_lee():
    brain = FakeBrain(None, stream_output=True, **{launcher.VOICE_SETTING: True})
    voice, _ = session([])

    launcher.interactive_mode(brain, read=patient(["cuéntame algo", "salir"], voice), voice=voice)

    assert voice.tts.texts == ["respuesta del chat."]


def test_un_fallo_de_la_voz_no_pierde_la_respuesta(capsys):
    class BrokenTTS:
        def synthesize(self, text):
            raise RuntimeError("sin altavoces")

    brain = FakeBrain("Hecho.", **{launcher.VOICE_SETTING: True})
    voice, _ = session([])
    voice._tts = BrokenTTS()

    launcher.interactive_mode(brain, read=patient(["hola", "otra", "salir"], voice), voice=voice)

    out = capsys.readouterr()
    assert "Hecho." in out.out and "No pude leer la respuesta en voz alta: sin altavoces" in out.err
    assert brain.processed == ["hola", "otra"]


# --- Piper -----------------------------------------------------------------------

def test_voz_que_falta(tmp_path):
    tts = PiperTTS({**DEFAULT_VOICE_SETTINGS, "voices_dir": str(tmp_path)})

    with pytest.raises(MissingVoice, match="es_MX-claude-high"):
        tts.load()


def test_voz_propia_por_config(tmp_path, monkeypatch):
    import piper

    (tmp_path / "mi_voz.onnx").write_bytes(b"x")
    (tmp_path / "mi_voz.onnx.json").write_text("{}", encoding="utf-8")
    loaded = []
    monkeypatch.setattr(piper.PiperVoice, "load", staticmethod(lambda path: loaded.append(path) or "voz"))

    PiperTTS({**DEFAULT_VOICE_SETTINGS, "voices_dir": str(tmp_path), "tts_voice": "mi_voz"}).load()

    assert loaded == [tmp_path / "mi_voz.onnx"]


@pytest.mark.skipif(
    not (project_path("data/voices") / "es_MX-claude-high.onnx").exists(),
    reason="voz no descargada",
)
def test_piper_real_genera_audio():
    audio, rate = PiperTTS(DEFAULT_VOICE_SETTINGS).synthesize("Hola.")

    assert rate == 22050 and audio.dtype == np.float32 and 0.2 < len(audio) / rate < 3
