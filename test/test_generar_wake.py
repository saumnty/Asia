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
    # 80 positivos: los 19 textos con las 4 voces.
    clips, _ = run(tmp_path, positives=80)

    assert all(tool.MIN_S <= clip.seconds <= tool.MAX_S for clip in clips)
    # "oye Asia, explica este archivo" pasa de 3 s: se corta.
    assert any(clip.trimmed for clip in clips) and not all(clip.trimmed for clip in clips)


def test_variaciones_en_su_rango_y_repetibles(tmp_path):
    clips, _ = run(tmp_path)
    again, _ = run(tmp_path / "otra")

    assert all(0.8 <= c.length_scale <= 1.3 and 0.4 <= c.noise_scale <= 0.9 and 0.5 <= c.noise_w <= 1.1 for c in clips)
    assert len({c.length_scale for c in clips}) > 10
    assert [(c.text, c.length_scale) for c in clips] == [(c.text, c.length_scale) for c in again]


def test_textos():
    assert {"oye Asia", "oye, Asia", "¡oye Asia!", "¿oye Asia?"} <= set(tool.positive_texts())
    assert "oye Asia, abre el bloc de notas" in tool.positive_texts()
    assert {"oye", "Asia", "hoy hacia", "oye Alicia", "Malasia", "fantasía", "Anastasia", "hacia allá"} <= set(
        tool.NEGATIVE_PHRASES)
    assert not set(tool.NEGATIVE_PHRASES) & set(tool.positive_texts())


def test_corte_con_desvanecido_y_relleno():
    long, trimmed = tool.fit(np.ones(5 * 16000, dtype=np.float32))
    short, padded = tool.fit(np.ones(8000, dtype=np.float32))

    assert trimmed and len(long) == 3 * 16000 and long[-1] == 0.0 and long[0] == 1.0
    assert not padded and len(short) == 16000 and short[-1] == 0.0
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

    assert recorded == {"positivos": 1, "negativos": 1}
    assert "positivos/: 40 clips" in text and "negativos/: 20 clips" in text
    assert "Apache-2.0" in text and "Unlicense" in text and "CC BY 3.0" in text and "atribución" in text
    assert "no comercial" in text and "ACAV100M" in text


def test_no_pisa_un_paquete_anterior(tmp_path, monkeypatch, capsys):
    (tmp_path / "sintetico.zip").write_bytes(b"")
    monkeypatch.setattr(sys, "argv", ["generar_wake.py", "--destino", str(tmp_path)])

    with pytest.raises(SystemExit):
        tool.main()

    assert "ya hay un sintetico.zip" in capsys.readouterr().err
