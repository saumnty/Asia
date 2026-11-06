"""comparar_wake: con un modelo y una voz de mentira (sin Piper ni openWakeWord)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import comparar_wake as tool  # noqa: E402


class LoudModel:
    """Puntúa por volumen; 23 entradas como oye_asia_v0.1. Cuenta tramos y resets."""

    model_inputs = {"oye_asia_v0.1": 23}

    def __init__(self):
        self.resets = 0
        self.chunks = 0

    def reset(self):
        self.resets += 1

    def predict(self, chunk):
        self.chunks += 1
        return {"oye_asia_v0.1": float(np.abs(chunk).max()) / 32767}


def speak(text, voice, speaker):
    """Más fuerte lo que debe activarse: así se ve que cada caso usa su audio."""
    return np.full(16000, 0.9 if "oye Asia" in text else 0.2, dtype=np.float32)


def test_cada_caso_y_cada_voz():
    model = LoudModel()

    results = tool.compare({"v": model}, speak)

    assert set(results) == {("v", case.name) for case in tool.CASES}
    assert all(len(scores) == len(tool.VOICES) for scores in results.values())
    # La voz a LEVEL: 0,9 × 0,5 y 0,2 × 0,5.
    assert results[("v", "sola")][0] == pytest.approx(0.45, abs=0.01)
    assert results[("v", "hoy hacia, sin fondo")][0] == pytest.approx(0.10, abs=0.01)
    assert model.resets == len(tool.CASES) * len(tool.VOICES)


def test_el_calentamiento_no_cuenta():
    model = LoudModel()
    # El fondo fuerte durante el calentamiento no puntúa; la frase, en silencio digital, sí.
    audio = np.zeros(16000, dtype=np.float32)

    assert tool.best_score(model, audio, None, np.random.default_rng(0)) == 0.0
    assert tool.best_score(model, audio, -6, np.random.default_rng(0)) > 0.3


def test_tabla():
    results = tool.compare({"v1": LoudModel(), "v2": LoudModel()}, speak)
    text = tool.table(results, ["v1", "v2"])

    assert "\nv1\n" in text and "\nv2\n" in text and "hoy hacia, fondo -45 dBFS" in text
    assert text.count("con frase delante") == 2
