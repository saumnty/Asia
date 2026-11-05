"""separar_audios_voz: con una exportación de WhatsApp inventada en una carpeta temporal."""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import separar_audios_voz as tool  # noqa: E402

CHAT = "\n".join([
    # Android en español.
    "12/03/24, 14:05 - Ana Pérez: PTT-20240312-WA0001.opus (archivo adjunto)",
    "12/03/24, 14:06 - Beto: PTT-20240312-WA0002.opus (archivo adjunto)",
    "12/03/24, 14:07 - Ana Pérez: un mensaje secreto que no debe salir",
    # Android en inglés, con p. m. y espacio fino.
    "3/12/24, 2:08 p. m. - Ana Pérez: PTT-20240312-WA0003.opus (file attached)",
    # iOS en español y en inglés, con la marca invisible.
    "[12/03/24, 14:09:33] Ana Pérez: ‎<adjunto: 00000012-AUDIO-2024-03-12-14-09-33.opus>",
    "‎[3/12/24, 2:10:00 PM] ~ Ana Pérez: ‎<attached: 00000013-AUDIO-2024-03-12-14-10-00.opus>",
    # Un adjunto que no es audio y uno que falta en la carpeta.
    "12/03/24, 14:11 - Ana Pérez: IMG-20240312-WA0004.jpg (archivo adjunto)",
    "12/03/24, 14:12 - Ana Pérez: PTT-20240312-WA0099.opus (archivo adjunto)",
    # Mensaje del sistema con un audio: sin remitente.
    "12/03/24, 14:13 - PTT-20240312-WA0005.opus (archivo adjunto)",
    "texto de una línea que sigue al mensaje anterior",
])

AUDIOS = ["PTT-20240312-WA0001.opus", "PTT-20240312-WA0002.opus", "PTT-20240312-WA0003.opus",
          "00000012-AUDIO-2024-03-12-14-09-33.opus", "00000013-AUDIO-2024-03-12-14-10-00.opus",
          "PTT-20240312-WA0005.opus", "PTT-20240312-WA0006.opus"]


@pytest.fixture
def export(tmp_path):
    folder = tmp_path / "export"
    folder.mkdir()
    (folder / "Chat de WhatsApp con Ana.txt").write_text(CHAT, encoding="utf-8")

    for name in AUDIOS:
        (folder / name).write_bytes(name.encode())

    (folder / "IMG-20240312-WA0004.jpg").write_bytes(b"jpg")
    (folder / "STK-1.webp").write_bytes(b"webp")
    return folder


def snapshot(folder):
    return {path.relative_to(folder): hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.rglob("*")}


def test_copia_solo_los_audios_del_remitente(export, tmp_path):
    before = snapshot(export)

    result = tool.separate(export, "ana pérez", tmp_path / "fuente" / "ana")

    assert sorted(result["copiados"]) == sorted(["PTT-20240312-WA0001.opus", "PTT-20240312-WA0003.opus",
                                                 "00000012-AUDIO-2024-03-12-14-09-33.opus",
                                                 "00000013-AUDIO-2024-03-12-14-10-00.opus"])
    copied = sorted(path.name for path in (tmp_path / "fuente" / "ana").iterdir())
    assert copied == sorted(result["copiados"])
    assert (tmp_path / "fuente" / "ana" / "PTT-20240312-WA0001.opus").read_bytes() == b"PTT-20240312-WA0001.opus"
    # Copia, no mueve: la exportación queda igual.
    assert snapshot(export) == before


def test_lista_los_sin_remitente_y_los_que_faltan(export, tmp_path):
    result = tool.separate(export, "Ana Pérez", tmp_path / "destino")

    assert result["faltan"] == ["PTT-20240312-WA0099.opus"]
    # El del mensaje del sistema y el que el chat no nombra.
    assert sorted(result["sin_remitente_claro"]) == ["PTT-20240312-WA0005.opus", "PTT-20240312-WA0006.opus"]
    assert result["de_otros"] == 1


def test_no_lee_ni_imprime_el_texto_de_los_mensajes(export, tmp_path, monkeypatch, capsys):
    lines = tool.read_audio_lines(tool.chat_file(export))

    assert all(set(vars(line)) == {"date", "sender", "name"} for line in lines)
    assert not any("secreto" in str(vars(line)) for line in lines)

    monkeypatch.setattr(sys, "argv", ["separar_audios_voz.py", "--export", str(export), "--remitente", "Ana Pérez",
                                      "--destino", str(tmp_path / "destino")])
    assert tool.main() == 0
    out = capsys.readouterr().out
    assert "secreto" not in out and "Copiados de «Ana Pérez»: 4." in out and "Beto" not in out


def test_una_segunda_vez_no_pisa_lo_copiado(export, tmp_path):
    tool.separate(export, "Ana Pérez", tmp_path / "destino")
    (tmp_path / "destino" / "PTT-20240312-WA0001.opus").write_bytes(b"editado")

    result = tool.separate(export, "Ana Pérez", tmp_path / "destino")

    assert result["copiados"] == [] and len(result["ya_estaban"]) == 4
    assert (tmp_path / "destino" / "PTT-20240312-WA0001.opus").read_bytes() == b"editado"


def test_remitente_que_no_esta(export, tmp_path):
    result = tool.separate(export, "Carla", tmp_path / "destino")

    assert result["copiados"] == [] and "revisa el nombre (en el chat hay 2 remitentes)" in tool.report(result, "Carla")
    assert not (tmp_path / "destino").exists()


def test_el_destino_no_puede_estar_en_la_exportacion(export):
    with pytest.raises(SystemExit):
        tool.separate(export, "Ana Pérez", export / "ana")


@pytest.mark.parametrize("line, sender, name", [
    ("1/2/2023 9:15 - Ana: audio.m4a (file attached)", "Ana", "audio.m4a"),
    ("[01.02.23, 09:15:00] Ana: <attached: 0001-AUDIO.opus>", "Ana", "0001-AUDIO.opus"),
    ("12/03/24, 14:05 - Ana: hola", None, None),
    ("sin fecha: PTT.opus (archivo adjunto)", None, None),
])
def test_formatos(line, sender, name):
    found = tool.audio_line(line)

    assert (found.sender, found.name) == (sender, name) if name else found is None
