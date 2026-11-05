"""inventario_voz: audio sintético en una carpeta temporal; el VAD es de mentira (sin modelos)."""
import csv
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import inventario_voz as tool  # noqa: E402


def write_wav(path, samples, rate=16000, channels=1):
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def tone(seconds, amplitude, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    return amplitude * np.sin(2 * np.pi * 440 * t)


def loud_parts(audio):
    """VAD de mentira: un tramo por cada parte seguida con |x| > 0,05 (en muestras a 16 kHz)."""
    voiced = np.abs(audio) > 0.05
    edges = np.flatnonzero(np.diff(np.concatenate([[0], voiced.astype(int), [0]])))
    return [(int(start), int(end)) for start, end in zip(edges[::2], edges[1::2])]


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "whatsapp"
    write_wav(root / "a.wav", np.concatenate([np.zeros(16000), tone(2, 0.5), np.zeros(16000)]))
    # Estéreo a 44,1 kHz, saturado.
    loud = np.repeat(tone(1, 1.2, 44100), 2)
    write_wav(root / "viejos" / "b.wav", loud, rate=44100, channels=2)
    (root / "viejos" / "roto.opus").write_bytes(b"esto no es opus")
    (root / "foto.jpg").write_bytes(b"jpg")
    (root / "STK-1.webp").write_bytes(b"webp")
    return root


def test_una_fila_por_audio(folder):
    rows, _, _, _ = tool.inventory(folder, segments=loud_parts)
    by_name = {row.archivo: row for row in rows}

    assert sorted(by_name) == ["a.wav", "b.wav", "roto.opus"]
    a = by_name["a.wav"]
    assert (a.formato, a.codec, a.hz, a.canales, a.segundos) == ("wav", "pcm_s16le", 16000, 1, 4.0)
    assert a.pico_dbfs == pytest.approx(-6.0, abs=0.1) and a.saturadas_pct == 0 and not a.saturado
    assert a.voz_s == pytest.approx(2.0, abs=0.2) and a.tramos_voz >= 1

    b = by_name["b.wav"]
    assert (b.hz, b.canales, b.segundos, b.subcarpeta) == (44100, 2, 1.0, "viejos")
    assert b.pico_dbfs == pytest.approx(0.0, abs=0.1) and b.saturado and b.saturadas_pct > 10


def test_lo_que_no_se_puede_leer_se_lista(folder):
    rows, by_folder, total, skipped = tool.inventory(folder, segments=loud_parts)

    [broken] = [row for row in rows if row.error]
    assert broken.archivo == "roto.opus" and broken.formato == "opus"
    assert total.ilegibles == 1 and "roto.opus" in tool.summary(by_folder, total, skipped)
    assert skipped == {".jpg": 1, ".webp": 1}


def test_resumen_por_subcarpeta_y_total(folder):
    _, by_folder, total, skipped = tool.inventory(folder, segments=loud_parts)

    assert set(by_folder) == {".", "viejos"}
    assert (by_folder["."].archivos, by_folder["viejos"].archivos, total.archivos) == (1, 2, 3)
    assert total.saturados == 1 and total.segundos == pytest.approx(5.0)
    assert total.voz_s == pytest.approx(by_folder["."].voz_s + by_folder["viejos"].voz_s)
    text = tool.summary(by_folder, total, skipped)
    assert text.splitlines()[-3].startswith("Total: 3 archivos") and "Saltados (no son audio ni vídeo): .jpg 1, .webp 1" in text


def test_el_csv_y_la_carpeta_queda_igual(folder, tmp_path, monkeypatch, capsys):
    before = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    monkeypatch.setattr(tool, "silero_segments", loud_parts)
    monkeypatch.setattr(sys, "argv", ["inventario_voz.py", "--carpeta", str(folder), "--salida", str(tmp_path / "inv.csv")])

    assert tool.main() == 0

    with open(tmp_path / "inv.csv", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))

    assert [row["archivo"] for row in rows] == ["a.wav", "b.wav", "roto.opus"] and list(rows[0]) == tool.COLUMNS
    assert {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()} == before
    assert "Total: 3 archivos" in capsys.readouterr().out


def test_el_vad_recibe_mono_a_16_khz():
    stereo = np.repeat(np.linspace(-1, 1, 44100, dtype=np.float32), 2)

    audio = tool.to_vad_audio(stereo, 44100, 2)

    assert audio.dtype == np.float32 and len(audio) == 16000
