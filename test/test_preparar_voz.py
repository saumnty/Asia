"""preparar_voz: audio sintético en una carpeta temporal, con el VAD y Whisper de mentira."""
import csv
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import preparar_voz as tool  # noqa: E402

RATE = 48000


def signal(rate, parts):
    """parts: [(segundos, nivel)]; nivel 0 es silencio."""
    return np.concatenate([np.full(int(seconds * rate), level, dtype=np.float32) for seconds, level in parts])


# Un audio: frase de 3 s, una de 1 s que se une a la siguiente de 2 s, una saturada y una de 20 s.
PARTS = [(0.5, 0), (3, 0.3), (0.5, 0), (1, 0.3), (0.4, 0), (2, 0.3), (0.5, 0), (3, 1.0), (0.5, 0), (20, 0.3), (0.5, 0)]


def decoder(path, rate=None):
    rate = rate or RATE
    return signal(rate, PARTS), rate


def loud_segments(audio16):
    """VAD de mentira: cada parte con nivel, en muestras a 16 kHz."""
    voiced = np.abs(audio16) > 0.05
    edges = np.flatnonzero(np.diff(np.concatenate([[0], voiced.astype(int), [0]])))
    return [(int(start), int(end)) for start, end in zip(edges[::2], edges[1::2])]


def probabilities(audio16):
    """Voz en todo, salvo un tramo más tranquilo a los 19 s (dentro de la frase de 20 s)."""
    probs = np.full(len(audio16) // tool.VAD_FRAME + 1, 0.9)
    quiet = int(19.0 * tool.VAD_RATE) // tool.VAD_FRAME
    probs[quiet:quiet + 5] = 0.1
    return probs


class Whisper:
    """Texto por duración: la de 3 s dice una palabra; la saturada, bien; el resto, frases."""

    def __init__(self):
        self.lengths = []

    def __call__(self, audio16):
        seconds = len(audio16) / tool.VAD_RATE
        self.lengths.append(round(seconds, 2))

        if abs(seconds - 3) < 0.01 and audio16.max() < 0.5:
            return "Hola.", -0.2, 0.01, 1.1

        return "Esta es una frase | de prueba.", -0.3, 0.02, 1.2


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "fuente"
    folder.mkdir()
    (folder / "audio1.opus").write_bytes(b"opus")
    (folder / "nota.txt").write_text("no es audio", encoding="utf-8")
    return folder


def run(source, destination):
    whisper = Whisper()
    phrases, _ = tool.prepare(source, destination, transcribe=whisper, decoder=decoder, segments=loud_segments,
                              probabilities=probabilities, log=lambda *a, **k: None)
    return phrases, whisper


def test_frases_de_2_a_15_s(source, tmp_path):
    phrases, whisper = run(source, tmp_path / "dataset")

    # 3 s; 1 s + 0,4 s + 2 s unidas (3,4 s); la saturada de 3 s; y la de 20 s (desde 11,4 s) partida
    # en su tramo tranquilo, a los 19 s del audio.
    assert [phrase.segundos for phrase in phrases] == pytest.approx([3.0, 3.4, 3.0, 7.66, 12.34], abs=0.05)
    assert all(tool.MIN_S <= phrase.segundos <= tool.MAX_S for phrase in phrases)
    assert [phrase.origen for phrase in phrases] == ["audio1.opus"] * 5
    assert phrases[1].inicio_s == pytest.approx(4.0, abs=0.01)
    # A Whisper le llega cada frase a 16 kHz.
    assert whisper.lengths == pytest.approx([phrase.segundos for phrase in phrases], abs=0.05)


def test_marca_lo_que_hay_que_revisar(source, tmp_path):
    phrases, _ = run(source, tmp_path / "dataset")

    assert phrases[0].motivos == ["una sola palabra"]
    assert phrases[2].motivos == [f"saturación > {tool.MAX_SATURATED_PCT} %"] and phrases[2].pico_dbfs == 0.0
    assert [phrase.revisar for phrase in phrases] == [True, False, True, False, False]


@pytest.mark.parametrize("values, reason", [
    ({"avg_logprob": -0.7}, "avg_logprob < -0.6"),
    ({"no_speech_prob": 0.5}, "no_speech_prob > 0.4"),
    ({"compression_ratio": 2.5}, "compression_ratio > 2.4"),
    ({"texto": ""}, "texto vacío"),
    ({"segundos": 1.5}, "fuera de 2–15 s"),
    ({"segundos": 16.0}, "fuera de 2–15 s"),
])
def test_cada_motivo(values, reason):
    phrase = tool.Phrase(id="0001", origen="a", inicio_s=0, segundos=5, texto="una frase normal", avg_logprob=-0.2,
                         no_speech_prob=0.01, compression_ratio=1.2)

    for key, value in values.items():
        setattr(phrase, key, value)

    assert tool.review_reasons(phrase) == [reason]


def test_salida_en_formato_ljspeech(source, tmp_path):
    destination = tmp_path / "dataset"
    run(source, destination)

    assert sorted(path.name for path in (destination / "wavs").iterdir()) == [f"000{n}.wav" for n in range(1, 6)]

    with wave.open(str(destination / "wavs" / "0002.wav"), "rb") as clip:
        assert (clip.getframerate(), clip.getnchannels(), clip.getsampwidth()) == (RATE, 1, 2)

    # Solo las aceptadas, id|texto, sin el "|" del texto.
    assert (destination / "metadata.csv").read_text(encoding="utf-8").splitlines() == [
        "0002|Esta es una frase de prueba.", "0004|Esta es una frase de prueba.", "0005|Esta es una frase de prueba."]

    with open(destination / "revisar.csv", encoding="utf-8-sig") as source_csv:
        rows = list(csv.DictReader(source_csv))

    assert [row["id"] for row in rows] == ["0001", "0002", "0003", "0004", "0005"] and list(rows[0]) == tool.COLUMNS
    assert rows[0]["revisar"] == "sí" and rows[0]["motivos"] == "una sola palabra" and rows[1]["revisar"] == ""

    text = (destination / "resumen.txt").read_text(encoding="utf-8")
    assert "Frases: 5; aceptadas 3, a revisar 2." in text and "una sola palabra: 1" in text
    assert "Minutos aceptados: 0.4 de 0.5." in text


def test_la_fuente_queda_igual(source, tmp_path):
    before = {path.name: path.read_bytes() for path in source.iterdir()}

    run(source, tmp_path / "dataset")

    assert {path.name: path.read_bytes() for path in source.iterdir()} == before


def test_no_pisa_un_dataset_anterior(source, tmp_path, monkeypatch, capsys):
    destination = tmp_path / "dataset"
    destination.mkdir()
    (destination / "metadata.csv").write_text("0001|ya revisada\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["preparar_voz.py", "--fuente", str(source), "--destino", str(destination)])

    with pytest.raises(SystemExit):
        tool.main()

    assert "ya hay un dataset" in capsys.readouterr().err


def test_unir_y_partir():
    min_samples, max_samples = 2 * 16000, 15 * 16000

    assert tool.merge_short([(0, 16000), (20000, 50000), (60000, 100000)], min_samples, max_samples) == [
        (0, 50000), (60000, 100000)]
    # Un corto al final se une al anterior.
    assert tool.merge_short([(0, 40000), (50000, 60000)], min_samples, max_samples) == [(0, 60000)]
    # Sin silencio claro, se parte en el tramo menos seguro de ser voz.
    probs = np.full(20 * 16000 // 512 + 1, 0.9)
    probs[300] = 0.6
    parts = tool.split_long((0, 20 * 16000), probs, min_samples, max_samples)
    assert len(parts) == 2 and parts[0][1] == 300 * 512 + 256
