"""dataset_final: un dataset y una revisión inventados en una carpeta temporal, con el VAD de mentira."""
import json
import sys
import wave
import zipfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import dataset_final as tool  # noqa: E402

RATE = 48000


def phrase(voice_s, before_s=1.0, after_s=1.0, level=0.2):
    """Silencio, voz (un tono) y silencio, a 48 kHz."""
    t = np.arange(int(voice_s * RATE)) / RATE
    voice = level * np.sin(2 * np.pi * 220 * t)
    return np.concatenate([np.zeros(int(before_s * RATE)), voice, np.zeros(int(after_s * RATE))]).astype(np.float32)


def loud_segments(audio16):
    """VAD de mentira: de la primera a la última muestra con |x| > 0,01."""
    voiced = np.flatnonzero(np.abs(audio16) > 0.01)
    return [(int(voiced[0]), int(voiced[-1]) + 1)] if len(voiced) else []


@pytest.fixture
def dataset(tmp_path):
    folder = tmp_path / "voz"
    (folder / "wavs").mkdir(parents=True)

    for id_, voice_s in (("0001", 2.0), ("0002", 3.0), ("0003", 0.5), ("0004", 2.0)):
        tool.write_wav(folder / "wavs" / f"{id_}.wav", phrase(voice_s), RATE)

    return folder


METADATA = {"0001": "Hola, ¿cómo estás?", "0002": "Tengo 2 perros | y un gato", "0003": "Ya.", "0004": "  "}


def run(dataset, tmp_path, revision=None):
    return tool.build(dataset, METADATA, tmp_path / "final", revision, segments=loud_segments, log=lambda *a: None)


def seconds_of(path):
    with wave.open(str(path), "rb") as clip:
        return clip.getnframes() / clip.getframerate(), clip.getframerate()


def test_dos_versiones_recortadas_y_normalizadas(dataset, tmp_path):
    run(dataset, tmp_path)

    for version in (22050, 16000):
        seconds, rate = seconds_of(tmp_path / "final" / str(version) / "wavs" / "0001.wav")
        # 2 s de voz más 0,15 s a cada lado: el segundo de silencio de cada extremo se fue.
        assert rate == version and seconds == pytest.approx(2.3, abs=0.02)
        audio, _ = tool.read_wav(tmp_path / "final" / str(version) / "wavs" / "0001.wav")
        assert 20 * np.log10(np.abs(audio).max()) == pytest.approx(-3.0, abs=0.05)


def test_solo_las_aceptadas_con_su_texto_y_sin_las_vacias(dataset, tmp_path):
    result = run(dataset, tmp_path)

    for version in (22050, 16000):
        lines = (tmp_path / "final" / str(version) / "metadata.csv").read_text(encoding="utf-8").splitlines()
        # Con el nombre del archivo, como lo pide piper1-gpl.
        assert lines == ["0001.wav|Hola, ¿cómo estás?", "0002.wav|Tengo 2 perros y un gato", "0003.wav|Ya."]

    assert result["frases"] == 3 and result["fuera"] == ["0004: texto vacío, no entra"]


def test_avisos_de_texto_y_de_duracion(dataset, tmp_path):
    result = run(dataset, tmp_path)

    assert "0002: dígitos: van en letra" in result["avisos"]
    assert any(line.startswith("0003: dura 0.80 s") for line in result["avisos"])
    assert not any(line.startswith("0001") for line in result["avisos"])
    assert tool.text_warnings("precio: 5 € @casa") == ["dígitos: van en letra", "símbolos raros: @ €"]
    assert tool.text_warnings("¡Hola! ¿Qué tal?, ya... (bien) - sí; «no»")[0].startswith("símbolos raros: «")


def test_zip_por_version_y_resumen(dataset, tmp_path):
    result = run(dataset, tmp_path)

    for version in (22050, 16000):
        with zipfile.ZipFile(tmp_path / "final" / f"final_{version}.zip") as archive:
            assert sorted(archive.namelist()) == ["metadata.csv", "wavs/0001.wav", "wavs/0002.wav", "wavs/0003.wav"]

    text = (tmp_path / "final" / "resumen.txt").read_text(encoding="utf-8")
    assert "Frases: 3;" in text and "Zip de 22050 Hz" in text and "Zip de 16000 Hz" in text
    assert dict(result["distribucion"]) == {"0–1 s": 1, "1–2 s": 0, "2–4 s": 2, "4–6 s": 0, "6–10 s": 0, "10–15 s": 0,
                                            "15 s o más": 0}


def test_avisa_si_metadata_y_revision_no_cuadran(dataset, tmp_path):
    revision = {"0001": {"estado": "aceptada", "texto": "Hola, ¿cómo estás?"},
                "0002": {"estado": "aceptada", "texto": "Tengo dos perros"},
                "0005": {"estado": "aceptada", "texto": "otra"},
                "0003": {"estado": "descartada", "texto": "Ya."}}

    result = run(dataset, tmp_path, revision)

    assert "0005: aceptada en revision.json pero no está en metadata.csv" in result["no_cuadra"]
    assert "0003: en metadata.csv pero no aceptada en revision.json" in result["no_cuadra"]
    assert "0002: el texto de metadata.csv y el de revision.json no coinciden" in result["no_cuadra"]


def test_el_dataset_de_origen_queda_igual(dataset, tmp_path):
    before = {path.name: path.read_bytes() for path in (dataset / "wavs").iterdir()}

    run(dataset, tmp_path)

    assert {path.name: path.read_bytes() for path in (dataset / "wavs").iterdir()} == before


def test_main_lee_lo_exportado_y_no_pisa(dataset, tmp_path, monkeypatch, capsys):
    (tmp_path / "metadata.csv").write_text("0001|Hola, ¿cómo estás?\n", encoding="utf-8")
    (tmp_path / "revision.json").write_text(json.dumps({"0001": {"estado": "aceptada", "texto": "Hola, ¿cómo estás?"}}),
                                            encoding="utf-8")
    monkeypatch.setattr(tool, "silero_segments", loud_segments)
    monkeypatch.setattr(sys, "argv", ["dataset_final.py", "--dataset", str(dataset), "--metadata", str(tmp_path / "metadata.csv"),
                                      "--revision", str(tmp_path / "revision.json"), "--destino", str(tmp_path / "salida")])

    assert tool.main() == 0
    assert "Frases: 1;" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        tool.main()
    assert "ya tiene archivos" in capsys.readouterr().err
