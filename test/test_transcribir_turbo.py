"""transcribir_turbo: dataset inventado en una carpeta temporal, con Whisper de mentira."""
import csv
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import preparar_voz  # noqa: E402
import transcribir_turbo as tool  # noqa: E402

SMALL = ["Hola, ¿cómo estás?", "Ya no pasó el tren.", "Compré pan en la tienda", "dos perros"]
TURBO = ["hola como estas", "Ya no, pasó el tranvía.", "Compré pan en la tienda.", "2 perros"]


@pytest.fixture
def dataset(tmp_path):
    folder = tmp_path / "fa"
    (folder / "wavs").mkdir(parents=True)
    phrases = []

    for number, text in enumerate(SMALL, 1):
        phrase = preparar_voz.Phrase(id=f"{number:04d}", origen="audio.opus", inicio_s=number * 3.0, segundos=2.5,
                                     texto=text, avg_logprob=-0.2 if number != 2 else -0.9, no_speech_prob=0.01,
                                     compression_ratio=1.1)
        phrase.motivos = preparar_voz.review_reasons(phrase)
        preparar_voz.save_wav(folder / "wavs" / f"{phrase.id}.wav", np.full(int(2.5 * 48000), 0.2), 48000)
        phrases.append(phrase)

    preparar_voz.write_outputs(phrases, folder, 0.0)
    return folder


class Turbo:
    def __init__(self):
        self.lengths = []

    def __call__(self, audio16):
        self.lengths.append(len(audio16))
        return TURBO[len(self.lengths) - 1], -0.3, 0.02, 1.2


def test_compara_sin_mayusculas_acentos_ni_puntuacion():
    assert tool.comparable("¿Hola, cómo ESTÁS?") == tool.comparable("hola como estas") == "hola como estas"
    assert tool.comparable("dos perros") != tool.comparable("2 perros")


def test_las_dos_transcripciones_en_revisar_csv(dataset):
    rows = tool.read_rows(dataset)
    whisper = Turbo()
    results, _ = tool.transcribe_all(dataset, rows, whisper, log=lambda *a, **k: None)
    merged = tool.merged_rows(rows, results)
    tool.write_rows(dataset, merged)

    # A Whisper le llega cada frase a 16 kHz.
    assert whisper.lengths == [int(2.5 * 16000)] * 4
    with open(dataset / "revisar.csv", encoding="utf-8-sig") as source:
        saved = list(csv.DictReader(source))

    assert list(saved[0]) == tool.COLUMNS
    assert [row["coinciden"] for row in saved] == ["sí", "", "sí", ""]
    assert saved[1]["texto_small"] == "Ya no pasó el tren." and saved[1]["texto_turbo"] == "Ya no, pasó el tranvía."
    assert saved[1]["revisar_small"] == "sí" and "avg_logprob" in saved[1]["motivos_small"]
    assert saved[1]["revisar_turbo"] == "" and saved[1]["avg_logprob_turbo"] == "-0.3"
    # El de antes queda guardado, y metadata.csv no cambia.
    assert (dataset / "revisar_small.csv").exists()
    assert (dataset / "metadata.csv").read_text(encoding="utf-8").count("\n") == 3


def test_resumen(dataset):
    rows = tool.read_rows(dataset)
    results, _ = tool.transcribe_all(dataset, rows, Turbo(), log=lambda *a, **k: None)

    text = tool.summary(tool.merged_rows(rows, results), 120)

    assert "2.0 min para 4 frases" in text and "Coinciden con small: 2 de 4." in text
    assert "Pasan los umbrales con turbo: 4 (0.2 min); con small eran 3." in text


def test_si_va_lento_se_detiene_sin_tocar_nada(dataset, monkeypatch, capsys):
    rows = tool.read_rows(dataset) * 6  # 24 frases de 2,5 s
    now = [0.0]

    def slow_whisper(audio):
        now[0] += 6  # 6 s por frase: 2,4× su duración
        return "x", 0, 0, 0

    with pytest.raises(tool.TooSlow) as slow:
        tool.transcribe_all(dataset, rows, slow_whisper, clock=lambda: now[0], log=lambda *a, **k: None)

    assert slow.value.ratio == pytest.approx(2.4) and slow.value.estimate_s == pytest.approx(2.4 * 60)

    before = (dataset / "revisar.csv").read_bytes()
    monkeypatch.setattr(tool, "transcribe_all", lambda *a, **k: (_ for _ in ()).throw(tool.TooSlow(2.4, 3600)))
    monkeypatch.setattr(sys, "argv", ["transcribir_turbo.py", "--dataset", str(dataset)])
    assert tool.main(transcriber=Turbo()) == 3
    assert "todo tardaría unos 60 min" in capsys.readouterr().out
    assert (dataset / "revisar.csv").read_bytes() == before and not (dataset / "revisar_small.csv").exists()


def test_no_transcribe_dos_veces(dataset, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["transcribir_turbo.py", "--dataset", str(dataset)])
    assert tool.main(transcriber=Turbo()) == 0

    with pytest.raises(SystemExit):
        tool.main(transcriber=Turbo())

    assert "ya tiene texto_turbo" in capsys.readouterr().err
