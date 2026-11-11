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


# --- --audios: grabaciones de check_wake ------------------------------------------

import check_wake  # noqa: E402
from core.voice.wake import CHUNK  # noqa: E402


def chunks(count, value):
    return [np.full(CHUNK, value, dtype=np.int16)] * count


def recordings(folder, peaks, false_peaks=(), minutes=10):
    """intento_NN.wav con 2,56 s de calentamiento (32 tramos) y 6 s de ventana con la frase a cada volumen; un falsas_01.wav
    de minutes con un golpe de cada volumen de false_peaks, separados más que el refractario."""
    for index, value in enumerate(peaks, 1):
        check_wake.save_wav(folder / f"intento_{index:02d}.wav", chunks(32, 100) + chunks(10, 100) + chunks(5, value) + chunks(60, 100))

    total = round(minutes * 60 * 16000 / CHUNK)
    quiet = chunks(total, 100)
    spikes = []

    for index, value in enumerate(false_peaks):
        spikes += chunks(50, 100) + chunks(2, value)

    check_wake.save_wav(folder / "falsas_01.wav", spikes + quiet[len(spikes):])


def test_barrido_aciertos_y_falsas_por_hora(tmp_path):
    # 20 intentos: 18 a 0,82 de puntuación y 2 a 0,3; en 10 min, golpes de 0,6 y 0,4.
    recordings(tmp_path, [int(0.82 * 32767)] * 18 + [int(0.3 * 32767)] * 2, [int(0.6 * 32767), int(0.4 * 32767)])
    positives, negatives = tool.recorded(tmp_path)

    rows = {row["umbral"]: row for row in tool.sweep(tool.score_recordings(LoudModel(), positives, negatives))}

    assert rows[0.25]["aciertos"] == 20 and rows[0.25]["falsas"] == 2 and rows[0.25]["por_hora"] == pytest.approx(12, abs=0.1)
    assert rows[0.5]["aciertos"] == 18 and rows[0.5]["falsas"] == 1
    assert rows[0.7]["aciertos"] == 18 and rows[0.7]["falsas"] == 0 and rows[0.7]["por_hora"] == 0
    assert rows[0.85]["aciertos"] == 0


def test_elige_el_de_mas_aciertos_y_si_empatan_el_mas_alto(tmp_path):
    recordings(tmp_path, [int(0.82 * 32767)] * 18 + [int(0.3 * 32767)] * 2, [int(0.6 * 32767)])
    positives, negatives = tool.recorded(tmp_path)
    rows = tool.sweep(tool.score_recordings(LoudModel(), positives, negatives))

    chosen = tool.choose(rows)

    # Cumplen de 0,65 a 0,80 (18/20, 0 falsas): el más alto.
    assert tool.meets(chosen) and chosen["umbral"] == 0.8 and chosen["aciertos"] == 18


def test_si_ninguno_cumple_el_mas_cercano():
    rows = [
        {"umbral": 0.3, "aciertos": 18, "intentos": 20, "falsas": 6, "horas": 1, "por_hora": 6.0},   # 11 de distancia
        {"umbral": 0.5, "aciertos": 15, "intentos": 20, "falsas": 1, "horas": 1, "por_hora": 1.0},   # 2 + 1 = 3
        {"umbral": 0.7, "aciertos": 14, "intentos": 20, "falsas": 0, "horas": 1, "por_hora": 0.0},   # 3
    ]

    chosen = tool.choose(rows)

    assert not tool.meets(chosen) and chosen["umbral"] == 0.5


def test_sin_falsas_grabadas_no_cumple_pero_elige(tmp_path):
    recordings(tmp_path, [int(0.82 * 32767)] * 20)
    (tmp_path / "falsas_01.wav").unlink()

    text, result = tool.compare_recordings({"v": LoudModel()}, tmp_path)

    assert "no hay falsas_*.wav" in text
    assert not tool.meets(result["elegido"]) and result["elegido"]["aciertos"] == 20


def test_sin_intentos_lo_dice(tmp_path):
    with pytest.raises(ValueError, match="intento_"):
        tool.compare_recordings({"v": LoudModel()}, tmp_path)


def test_dos_modelos_sobre_los_mismos_audios_y_la_linea_de_config(tmp_path):
    recordings(tmp_path, [int(0.82 * 32767)] * 20, [int(0.6 * 32767)])

    class Half(LoudModel):
        def predict(self, chunk):
            return {"oye_asia_v0.1": super().predict(chunk)["oye_asia_v0.1"] / 2}

    text, result = tool.compare_recordings({"v1": Half(), "v2": LoudModel()}, tmp_path)

    # v1 puntúa la mitad: con 0,41 en los intentos llega a 20/20 solo hasta 0,40, y el golpe (0,3) no lo activa.
    assert result["v1"]["recomendado"]["umbral"] == 0.4 and result["v2"]["recomendado"]["umbral"] == 0.8
    assert result["elegido"]["modelo"] in ("v1", "v2") and tool.meets(result["elegido"])
    assert '"wake_threshold": ' in text and "config/defaults.json" in text


def test_el_mismo_modelo_dos_veces(monkeypatch):
    import core.voice.wake as wake

    monkeypatch.setattr(wake, "missing", lambda config: None)
    monkeypatch.setattr(wake, "load_model", lambda config: LoudModel())

    models = tool.load_models(["oye_asia_v0.1", "oye_asia_v0.1"])

    assert list(models) == ["oye_asia_v0.1", "oye_asia_v0.1 (2)"]


def test_el_resultado_se_guarda_en_json(tmp_path):
    import json

    recordings(tmp_path, [int(0.82 * 32767)] * 20, [int(0.6 * 32767)])

    class NumpyModel(LoudModel):
        # openWakeWord puntúa con float32 de numpy: las comparaciones dan numpy.bool_.
        def predict(self, chunk):
            return {"oye_asia_v0.1": np.float32(super().predict(chunk)["oye_asia_v0.1"])}

    _, result = tool.compare_recordings({"v": NumpyModel()}, tmp_path)

    assert json.loads(json.dumps(result))["elegido"]["aciertos"] == 20
