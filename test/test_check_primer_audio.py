"""check_primer_audio: el desglose por etapas, sin modelos."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import check_primer_audio as tool  # noqa: E402
from core.timing import ModelCall, Timings  # noqa: E402


def timings(start=100.0, intent=1.8, call_start=2.0, first_audio=8.5, load=0.2):
    measured = Timings(start=start, intent=intent, first_audio=start + first_audio if first_audio else None)
    measured.calls.append(ModelCall("ollama", "qwen3", 5.0, load=load, tokens=40))
    measured.answer_call_start = call_start
    return measured


def probe(start=100.0, first_text=7.0):
    found = tool.Probe()
    found.first_text = start + first_text if first_text else None
    return found


def test_etapas_que_suman_el_primer_audio():
    result = tool.breakdown(timings(), probe())

    assert result["intencion"] == pytest.approx(1.8)
    assert result["herramienta"] == pytest.approx(0.2)
    assert result["generacion"] == pytest.approx(5.0)
    assert result["sintesis"] == pytest.approx(1.5)
    assert result["primer_audio"] == pytest.approx(8.5)
    # Las cuatro primeras suman el primer audio; el aviso va aparte.
    assert sum(result[s] for s in tool.STAGES[:4]) == pytest.approx(result["primer_audio"])
    assert result["aviso"] is None and result["llamadas"][-1]["modelo"] == "qwen3"
    assert (result["carga"], result["modelo"], result["tokens"]) == (0.2, "qwen3", 40)


def test_sin_llamada_al_modelo_todo_es_herramienta():
    measured = Timings(start=100.0, intent=None, first_audio=101.6)

    result = tool.breakdown(measured, probe(first_text=1.3))

    assert result["intencion"] == 0.0 and result["generacion"] is None
    assert result["herramienta"] == pytest.approx(1.3) and result["sintesis"] == pytest.approx(0.3)


def test_sin_audio_no_inventa_etapas():
    result = tool.breakdown(timings(first_audio=None), probe(first_text=None))

    assert result["primer_audio"] is None and result["generacion"] is None and result["sintesis"] is None


def test_la_sonda_anota_solo_la_primera_frase_y_su_audio(monkeypatch):
    from core.voice import reading

    said = []
    monkeypatch.setattr(reading.Reading, "say", lambda self, text: said.append(text))

    class TTS:
        def synthesize(self, text):
            return [0.0], 22050

    tts = TTS()
    found = tool.Probe()
    found.install(tts)

    reading.Reading.say(None, "")
    assert found.first_text is None
    reading.Reading.say(None, "Hola.")
    first = found.first_text
    reading.Reading.say(None, "Otra.")
    tts.synthesize("Hola.")
    synth = found.first_synth
    tts.synthesize("Otra.")

    assert first is not None and found.first_text == first and found.first_synth == synth
    assert said == ["", "Hola.", "Otra."]


def test_mediana_ignora_lo_que_falta():
    assert tool.median([3.0, None, 1.0, 2.0]) == 2.0 and tool.median([None]) is None
