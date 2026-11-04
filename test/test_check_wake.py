"""check_wake (fase J3): las partes que no necesitan micrófono ni openWakeWord."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import check_wake  # noqa: E402


def test_junta_los_tramos_del_microfono_en_80_ms_int16():
    chunker = check_wake.Chunker()

    assert chunker.feed(np.full(512, 0.5, dtype=np.float32)) == []
    assert chunker.feed(np.full(512, 0.5, dtype=np.float32)) == []
    chunks = chunker.feed(np.full(512, 2.0, dtype=np.float32))

    assert len(chunks) == 1 and chunks[0].dtype == np.int16 and len(chunks[0]) == 1280
    assert chunks[0][0] == 16383 and chunks[0][-1] == 32767 and len(chunker.pending) == 256


def test_una_frase_cuenta_una_vez_aunque_dispare_varios_tramos():
    found = check_wake.Activations(threshold=0.5, refractory_s=2.0, chunk_s=0.08)
    scores = [0.1, 0.9, 0.95, 0.8] + [0.0] * 30 + [0.7]

    fired = [found.feed(score) for score in scores]

    assert fired.count(True) == 2 and found.times == pytest.approx([0.08, 34 * 0.08])
    assert found.peak == 0.95


def test_bajo_el_umbral_no_activa():
    found = check_wake.Activations(threshold=0.6)

    assert not any(found.feed(score) for score in [0.2, 0.59, 0.4]) and found.times == []


def test_falsas_por_hora():
    assert check_wake.per_hour(3, 1800) == 6.0 and check_wake.per_hour(0, 0) == 0.0


def test_sin_openwakeword_dice_que_falta(monkeypatch, capsys):
    monkeypatch.setattr(check_wake, "load_model", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["check_wake.py", "--falsas", "1"])

    assert check_wake.main() == 2
    assert "Falta openwakeword" in capsys.readouterr().out
