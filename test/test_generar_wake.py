"""generar_wake: con Piper de mentira y grabaciones inventadas en carpetas temporales."""
import csv
import io
import sys
import wave
import zipfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import generar_wake as tool  # noqa: E402


def fake_synth(voice, clip):
    """22 050 Hz como Piper; la duración crece con el texto y con length_scale."""
    seconds = 0.08 * len(clip.text) * clip.length_scale
    return np.full(int(seconds * 22050), 0.3, dtype=np.float32), 22050


def run(tmp_path, positives=40, negatives=20):
    loaded = []
    clips = tool.generate(tmp_path, positives, negatives, load_voice=lambda name: loaded.append(name) or name,
                          synth=fake_synth, log=lambda *a, **k: None)
    return clips, loaded


def read(archive, name):
    with wave.open(io.BytesIO(archive.read(name)), "rb") as clip:
        return clip.getframerate(), clip.getnchannels(), clip.getsampwidth(), clip.getnframes()


def test_positivos_y_negativos_en_el_zip(tmp_path):
    clips, loaded = run(tmp_path)

    with zipfile.ZipFile(tmp_path / "sintetico.zip") as archive:
        names = archive.namelist()
        assert sum(name.startswith("positivos/") for name in names) == 40
        assert sum(name.startswith("negativos/") for name in names) == 20
        assert "clips.csv" in names
        rate, channels, width, frames = read(archive, "positivos/p00001.wav")
        assert (rate, channels, width) == (16000, 1, 2) and 16000 <= frames <= 48000
        rows = list(csv.DictReader(io.StringIO(archive.read("clips.csv").decode("utf-8"))))

    # Cada voz se carga una vez; sharvard da dos hablantes.
    assert sorted(loaded) == ["es_ES-sharvard-medium", "es_MX-ald-medium", "es_MX-claude-high"]
    assert {(c.voice, c.speaker) for c in clips} == set(tool.VOICES)
    assert len(rows) == 60 and rows[0]["texto"] == "oye Asia"


def test_de_1_a_3_s(tmp_path):
    # 200 positivos: todos los textos de cada grupo con las 4 voces.
    clips, _ = run(tmp_path, positives=200)

    assert all(tool.MIN_S <= clip.seconds <= tool.MAX_S for clip in clips)
    # "oye Asia, explica este archivo" pasa de 3 s: se corta.
    assert any(clip.trimmed for clip in clips) and not all(clip.trimmed for clip in clips)


def test_reparto_de_positivos_y_negativos():
    clips = tool.all_clips(5000, 3000)
    positives = [c for c in clips if c.kind == "positivos"]
    negatives = [c for c in clips if c.kind == "negativos"]
    groups = {group: sum(c.group == group for c in positives) for group in tool.POSITIVE_SHARES}

    assert len(positives) == 5000 and groups == {"sola": 2500, "detrás": 1750, "delante": 750}
    assert {c.text for c in positives if c.group == "sola"} == set(tool.WAKE)
    assert all(c.text.startswith("oye Asia, ") for c in positives if c.group == "detrás")
    assert all(c.text.endswith(", oye Asia") for c in positives if c.group == "delante")
    # Los difíciles, 250 cada uno, con y sin frase detrás; el resto para las demás parecidas.
    assert len(negatives) == 3000
    assert {family: sum(c.group == family for c in negatives) for family in tool.HARD_NEGATIVES} == dict.fromkeys(
        tool.HARD_NEGATIVES, 250)
    assert {c.text for c in negatives if c.group == "hoy hacia"} == {"hoy hacia", "hoy hacia el centro, ¿vienes?"}
    assert sum(c.group == "parecidas" for c in negatives) == 1500
    # Nombres únicos, numerados dentro de cada tipo (como en v0.1).
    assert len({c.name for c in clips}) == 8000 and positives[-1].name == "p05000.wav" and negatives[0].name == "n00001.wav"


def test_sola_lleva_silencio_despues_y_delante_conserva_el_final(tmp_path):
    clips, _ = run(tmp_path, positives=200)

    alone = [c for c in clips if c.group == "sola"]
    assert all(tool.SILENCE_AFTER_S[0] <= c.silence_after <= tool.SILENCE_AFTER_S[1] for c in alone)
    assert all(c.silence_after == 0 for c in clips if c.group != "sola")
    assert all(c.keep_end for c in clips if c.group == "delante") and not any(c.keep_end for c in clips if c.group != "delante")

    with zipfile.ZipFile(tmp_path / "sintetico.zip") as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("clips.csv").decode("utf-8"))))

    assert {row["grupo"] for row in rows} >= {"sola", "detrás", "delante", "hoy hacia", "parecidas"}


def test_variaciones_en_su_rango_y_repetibles(tmp_path):
    clips, _ = run(tmp_path)
    again, _ = run(tmp_path / "otra")

    assert all(0.8 <= c.length_scale <= 1.3 and 0.4 <= c.noise_scale <= 0.9 and 0.5 <= c.noise_w <= 1.1 for c in clips)
    assert len({c.length_scale for c in clips}) > 10
    assert [(c.text, c.length_scale) for c in clips] == [(c.text, c.length_scale) for c in again]


def test_textos():
    assert {"oye Asia", "oye, Asia", "¡oye Asia!", "¿oye Asia?", "oye... Asia"} <= set(tool.positive_texts())
    assert {"oye Asia, abre el bloc de notas", "bueno, oye Asia"} <= set(tool.positive_texts())
    assert {"oye", "Asia", "hoy hacia", "hoy hacía frío", "oye Alicia", "o ya sí a", "oye, así", "Malasia", "fantasía",
            "Anastasia", "hacia allá"} <= set(tool.negative_texts())
    assert not set(tool.negative_texts()) & set(tool.positive_texts())


def test_split_count_no_pierde_clips():
    assert tool.split_count(40, [0.5, 0.35, 0.15]) == [20, 14, 6]
    assert sum(tool.split_count(7, [1 / 6] * 6)) == 7


def test_corte_con_desvanecido_y_relleno():
    long, trimmed = tool.fit(np.ones(5 * 16000, dtype=np.float32))
    short, padded = tool.fit(np.ones(8000, dtype=np.float32))

    assert trimmed and len(long) == 3 * 16000 and long[-1] == 0.0 and long[0] == 1.0
    assert not padded and len(short) == 16000 and short[-1] == 0.0
    # "bueno, oye Asia" largo: se corta por delante, la palabra queda entera.
    ramp = np.linspace(0, 1, 5 * 16000, dtype=np.float32)
    end, trimmed = tool.fit(ramp, keep_end=True)
    assert trimmed and len(end) == 3 * 16000 and end[0] == 0.0 and end[-1] == ramp[-1]
    assert len(tool.to_16k(np.zeros(22050, dtype=np.float32), 22050)) == 16000


def test_mi_voz_y_leeme(tmp_path):
    wake = tmp_path / "wake"
    (wake / "positivos" / "oye_asia").mkdir(parents=True)
    (wake / "negativos" / "hoy_hacia").mkdir(parents=True)
    (wake / "positivos" / "oye_asia" / "001.wav").write_bytes(tool.wav_bytes(np.zeros(16000)))
    (wake / "negativos" / "hoy_hacia" / "001.wav").write_bytes(tool.wav_bytes(np.zeros(16000)))
    (wake / "intento_01.wav").write_bytes(b"no va")
    out = tmp_path / "salida"
    clips, _ = run(out)

    recorded = tool.pack_recordings(wake, out)
    text = tool.readme(clips, recorded)

    with zipfile.ZipFile(out / "mi_voz.zip") as archive:
        assert sorted(archive.namelist()) == ["negativos/hoy_hacia/001.wav", "positivos/001.wav"]

    assert recorded == {"positivos": 1, "negativos": 1} == tool.count_recordings(out / "mi_voz.zip")
    assert "positivos/: 40 clips" in text and "negativos/: 20 clips" in text
    assert "Apache-2.0" in text and "Unlicense" in text and "CC BY 3.0" in text and "atribución" in text
    assert "no comercial" in text and "ACAV100M" in text


def test_no_pisa_un_paquete_anterior(tmp_path, monkeypatch, capsys):
    (tmp_path / "sintetico.zip").write_bytes(b"")
    monkeypatch.setattr(sys, "argv", ["generar_wake.py", "--destino", str(tmp_path)])

    with pytest.raises(SystemExit):
        tool.main()

    assert "ya hay un sintetico.zip" in capsys.readouterr().err


def test_respalda_el_anterior_y_no_rehace_mi_voz(tmp_path, monkeypatch, capsys):
    (tmp_path / "sintetico.zip").write_bytes(b"v0.1")
    tool.pack_recordings(tmp_path / "sin_grabaciones", tmp_path)
    before = (tmp_path / "mi_voz.zip").read_bytes()
    monkeypatch.setattr(tool, "load_piper", lambda name: name)
    monkeypatch.setattr(tool, "synthesize", fake_synth)
    monkeypatch.setattr(tool, "POSITIVES", 20)
    monkeypatch.setattr(sys, "argv", ["generar_wake.py", "--destino", str(tmp_path), "--respaldo", "sintetico_v01.zip",
                                      "--positivos", "20", "--negativos", "12"])

    assert tool.main() == 0

    assert (tmp_path / "sintetico_v01.zip").read_bytes() == b"v0.1"
    assert (tmp_path / "mi_voz.zip").read_bytes() == before
    with zipfile.ZipFile(tmp_path / "sintetico.zip") as archive:
        assert sum(name.endswith(".wav") for name in archive.namelist()) == 32
    assert "reparto v0.2" in (tmp_path / "LEEME.txt").read_text(encoding="utf-8")

    # Una segunda vez con el mismo respaldo: no lo pisa.
    monkeypatch.setattr(sys, "argv", ["generar_wake.py", "--destino", str(tmp_path), "--respaldo", "sintetico_v01.zip"])
    with pytest.raises(SystemExit):
        tool.main()
    assert "ya existe sintetico_v01.zip" in capsys.readouterr().err
