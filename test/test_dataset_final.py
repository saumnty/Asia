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


# --- Silencios atenuados y una sola frecuencia ----------------------------------------

def runs_segments(audio16, min_gap=0.3):
    """VAD de mentira con varios tramos: las rachas con |x| > 0,01 separadas por más de min_gap s."""
    voiced = np.flatnonzero(np.abs(audio16) > 0.01)

    if not len(voiced):
        return []

    cuts = np.flatnonzero(np.diff(voiced) > min_gap * 16000)
    starts = np.concatenate([[voiced[0]], voiced[cuts + 1]])
    ends = np.concatenate([voiced[cuts], [voiced[-1]]]) + 1
    return [(int(a), int(b)) for a, b in zip(starts, ends)]


def with_pause(pause_s, level=0.2, noise=0.005):
    """1 s de voz, una pausa con ruido de fondo y otro segundo de voz, a 48 kHz."""
    t = np.arange(RATE) / RATE
    voice = level * np.sin(2 * np.pi * 220 * t)
    gap = noise * np.sin(2 * np.pi * 50 * np.arange(int(pause_s * RATE)) / RATE)
    return np.concatenate([voice, gap, voice]).astype(np.float32)


def test_una_pausa_larga_se_atenua_sin_recortar_nada():
    audio = with_pause(1.0)
    out = tool.attenuate_silences(audio, RATE, runs_segments)

    assert len(out) == len(audio)
    middle = slice(int(1.5 * RATE), int(1.6 * RATE))
    assert np.max(np.abs(out[middle])) < 0.1 * np.max(np.abs(audio[middle]))
    # La voz queda igual, y también lo que rodea a la voz (0,1 s).
    assert np.allclose(out[: int(0.9 * RATE)], audio[: int(0.9 * RATE)], atol=1e-4)
    assert np.allclose(out[int(1.05 * RATE): int(1.08 * RATE)], audio[int(1.05 * RATE): int(1.08 * RATE)], atol=1e-4)


def test_una_pausa_corta_se_deja():
    audio = with_pause(0.3)

    assert np.array_equal(tool.attenuate_silences(audio, RATE, runs_segments), audio)


def test_sin_voz_no_cambia():
    audio = np.zeros(RATE, dtype=np.float32)

    assert np.array_equal(tool.attenuate_silences(audio, RATE, runs_segments), audio)


def test_variante_atenuada_y_solo_22050(dataset, tmp_path):
    tool.write_wav(dataset / "wavs" / "0001.wav", np.concatenate([np.zeros(RATE), with_pause(1.0), np.zeros(RATE)]).astype(np.float32), RATE)
    normal = tool.build(dataset, METADATA, tmp_path / "normal", segments=runs_segments, rates=(22050,))
    quiet = tool.build(dataset, METADATA, tmp_path / "atenuado", segments=runs_segments, rates=(22050,), quiet=True)

    assert not (tmp_path / "normal" / "16000").exists() and list(quiet["zips"]) == [22050]
    assert normal["frases"] == quiet["frases"] == 3 and normal["minutos"] == pytest.approx(quiet["minutos"], abs=0.01)
    peak = lambda folder: np.max(np.abs(tool.read_wav(tmp_path / folder / "22050" / "wavs" / "0001.wav")[0][int(1.7 * 22050): int(1.9 * 22050)]))
    assert peak("atenuado") < 0.15 * peak("normal")
    assert (tmp_path / "normal" / "22050" / "metadata.csv").read_text(encoding="utf-8") == (tmp_path / "atenuado" / "22050" / "metadata.csv").read_text(encoding="utf-8")


# --- Reemplazos: los números en palabras ------------------------------------------------

def test_los_reemplazos_cambian_el_texto_de_metadata(dataset, tmp_path):
    csv_path = tmp_path / "numeros.csv"
    csv_path.write_text("id,texto_actual,propuesta,final,nota\n0002,Tengo 2 perros,x,Tengo dos perros | y un gato,\n", encoding="utf-8-sig")
    replacements, notes = tool.read_replacements(csv_path, METADATA)

    result = tool.build(dataset, METADATA, tmp_path / "final", segments=loud_segments, rates=(22050,),
                        replacements=replacements, replacement_notes=notes)
    lines = (tmp_path / "final" / "22050" / "metadata.csv").read_text(encoding="utf-8").splitlines()

    assert "0002.wav|Tengo dos perros y un gato" in lines and "0001.wav|Hola, ¿cómo estás?" in lines
    assert result["reemplazados"] == 1 and "Textos reemplazados: 1" in tool.summary(result)
    # Con la frase en letra, ya no avisa de dígitos.
    assert not any(line.startswith("0002") and "dígitos" in line for line in result["avisos"])


def test_excel_quita_los_ceros_y_usa_punto_y_coma(tmp_path):
    csv_path = tmp_path / "numeros.csv"
    csv_path.write_text("ID;texto_actual;Final\n2;a las 8;a las ocho\n", encoding="utf-8-sig")

    assert tool.read_replacements(csv_path, METADATA) == ({"0002": "a las ocho"}, [])


def test_con_tabuladores_tambien(tmp_path):
    csv_path = tmp_path / "numeros.csv"
    csv_path.write_text("id\tfinal\n0001\tHola\n", encoding="utf-8")

    assert tool.read_replacements(csv_path, METADATA) == ({"0001": "Hola"}, [])


def test_un_final_vacio_o_un_id_que_no_existe_se_avisan(dataset, tmp_path):
    csv_path = tmp_path / "numeros.csv"
    csv_path.write_text("id,final\n0001,\n0099,algo\n0003,Ya mismo.\n", encoding="utf-8")
    replacements, notes = tool.read_replacements(csv_path, METADATA)

    result = tool.build(dataset, METADATA, tmp_path / "final", segments=loud_segments, rates=(22050,),
                        replacements=replacements, replacement_notes=notes)
    lines = (tmp_path / "final" / "22050" / "metadata.csv").read_text(encoding="utf-8").splitlines()

    assert "0001.wav|Hola, ¿cómo estás?" in lines and "0003.wav|Ya mismo." in lines
    assert any("0001" in note and "vacía" in note for note in result["reemplazos_avisos"])
    assert any("0099" in note for note in result["reemplazos_avisos"])
    assert "Reemplazos con problemas: 2" in tool.summary(result)


def test_el_csv_sin_la_columna_final_se_rechaza(tmp_path):
    csv_path = tmp_path / "numeros.csv"
    csv_path.write_text("id,texto\n0001,Hola\n", encoding="utf-8")

    with pytest.raises(ValueError, match="id y final"):
        tool.read_replacements(csv_path, METADATA)


def test_sin_reemplazos_todo_sigue_igual(dataset, tmp_path):
    result = run(dataset, tmp_path)

    assert result["reemplazados"] == 0 and result["reemplazos_avisos"] == []
    assert "reemplazados" not in tool.summary(result)
