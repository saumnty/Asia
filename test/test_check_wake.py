"""check_wake (fase J3): las partes que no necesitan micrófono ni openWakeWord."""
import queue
import sys
import wave
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import check_wake  # noqa: E402
from core.voice.wake import CHUNK, Chunker  # noqa: E402


class LoudModel:
    """Puntúa cada tramo por su volumen: 0,9 si es fuerte. Cuenta los reset."""

    def __init__(self):
        self.resets = 0
        self.seen = 0

    def reset(self):
        self.resets += 1

    def predict(self, chunk):
        self.seen += 1
        return {"hey_jarvis_v0.1": 0.9 if np.abs(chunk).max() > 16000 else 0.05}


class Stream:
    """Como FrameReader: tramos de 512 en una cola; se puede iterar varias veces."""

    def __init__(self, frames):
        self.frames = queue.Queue()

        for frame in frames:
            self.frames.put(frame)

    def __iter__(self):
        while not self.frames.empty():
            yield self.frames.get()


class Microphone:
    def __init__(self, frames):
        self.stream = Stream(frames)
        self.opened = 0

    @contextmanager
    def open(self):
        self.opened += 1
        yield self.stream


def test_falsas_por_hora():
    assert check_wake.per_hour(3, 1800) == 6.0 and check_wake.per_hour(0, 0) == 0.0


def test_el_modelo_y_el_vad_de_la_linea_de_comandos():
    config = check_wake.config_for("oye_asia", 0.5)

    assert config["wake_word"] == "oye_asia" and config["wake_vad_threshold"] == 0.5
    assert check_wake.config_for(None, None)["wake_word"] == "hey_jarvis_v0.1"


def test_si_falta_algo_lo_dice(monkeypatch, capsys):
    monkeypatch.setattr(check_wake, "missing", lambda config: "Falta openwakeword: ...")
    monkeypatch.setattr(sys, "argv", ["check_wake.py", "--falsas", "1"])

    assert check_wake.main() == 2
    assert "Falta openwakeword" in capsys.readouterr().out


def frames(seconds, value=0.0):
    return [np.full(512, value, dtype=np.float32) for _ in range(round(seconds * 16000 / 512))]


def test_take_no_pierde_muestras_entre_el_calentamiento_y_la_ventana():
    stream, chunker = Stream(frames(3.0, 0.1)), Chunker()

    warmup = list(check_wake.take(stream, chunker, 2.0))
    window = list(check_wake.take(stream, chunker, 0.5))

    assert len(warmup) == 25 and len(window) == 6
    assert all(len(chunk) == CHUNK for chunk in warmup + window)
    # 94 tramos de 512 en la cola: lo que no se pidió sigue en la cola o en chunker.
    left = stream.frames.qsize() * 512 + len(chunker.pending)
    assert 31 * CHUNK + left == 94 * 512


def test_el_calentamiento_no_cuenta_aunque_puntue_alto():
    model = LoudModel()
    loud = [np.full(CHUNK, 20000, dtype=np.int16)] * 25
    quiet = [np.full(CHUNK, 100, dtype=np.int16)] * 75

    row, heard = check_wake.run_trial(model, loud, quiet, 0.5)

    assert row["activó"] is False and row["puntuación máxima"] == 0.05
    assert model.resets == 1 and model.seen == 100 and len(heard) == 100


def test_activa_en_la_ventana_y_da_los_niveles():
    quiet = [np.zeros(CHUNK, dtype=np.int16)] * 25
    window = [np.full(CHUNK, 100, dtype=np.int16)] * 70 + [np.full(CHUNK, 32767 // 2, dtype=np.int16)] * 5

    row, _ = check_wake.run_trial(LoudModel(), quiet, window, 0.5)

    assert row["activó"] is True and row["puntuación máxima"] == 0.9
    assert row["pico_dbfs"] == -6.0 and row["rms_calentamiento_dbfs"] == check_wake.SILENCE_DBFS


def test_niveles_en_dbfs():
    assert check_wake.levels([np.full(CHUNK, 32767, dtype=np.int16)]) == (0.0, 0.0)
    assert check_wake.levels([np.zeros(CHUNK, dtype=np.int16)]) == (-120.0, -120.0)
    assert check_wake.levels([]) == (-120.0, -120.0)


def test_drain_tira_lo_que_llego_mientras_esperaba():
    stream = Stream(frames(1.0))

    check_wake.drain(stream)

    assert stream.frames.empty()


def test_un_microfono_para_toda_la_prueba_y_guarda_cada_intento(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    microphone = Microphone([])
    model = LoudModel()

    # Cada intento: Enter (drain tira lo viejo), y luego 2 s de calentamiento y 6 s de ventana.
    def refill(stream):
        while not stream.frames.empty():
            stream.frames.get()

        for frame in frames(2.0) + frames(1.0) + frames(1.0, 0.9) + frames(4.5):
            stream.frames.put(frame)

    monkeypatch.setattr(check_wake, "drain", refill)
    result = check_wake.hits(model, 2, 0.5, tmp_path, microphone)

    assert microphone.opened == 1 and model.resets == 2
    assert result["aciertos"] == 2 and [row["intento"] for row in result["filas"]] == [1, 2]
    assert [path.name for path in check_wake.trial_files(tmp_path)] == ["intento_01.wav", "intento_02.wav"]

    with wave.open(str(tmp_path / "intento_01.wav"), "rb") as saved:
        assert (saved.getframerate(), saved.getnchannels(), saved.getsampwidth()) == (16000, 1, 2)
        assert saved.getnframes() == 100 * CHUNK


def test_repuntuar_lo_guardado_sin_microfono(tmp_path, capsys):
    quiet = [np.full(CHUNK, 100, dtype=np.int16)]
    check_wake.save_wav(tmp_path / "intento_01.wav", quiet * 100)
    check_wake.save_wav(tmp_path / "intento_02.wav", quiet * 60 + [np.full(CHUNK, 20000, dtype=np.int16)] * 5 + quiet * 35)
    # El volumen alto en el calentamiento no cuenta.
    check_wake.save_wav(tmp_path / "intento_03.wav", [np.full(CHUNK, 20000, dtype=np.int16)] * 25 + quiet * 75)

    result = check_wake.rescore(LoudModel(), tmp_path, 0.5)

    assert [row["activó"] for row in result["filas"]] == [False, True, False] and result["aciertos"] == 1
    assert "intento_02.wav: sí" in capsys.readouterr().out


def test_repuntuar_rechaza_otro_formato(tmp_path):
    with wave.open(str(tmp_path / "intento_01.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(44100)
        out.writeframes(b"\0\0" * 100)

    with pytest.raises(ValueError, match="16000 Hz"):
        check_wake.read_wav(tmp_path / "intento_01.wav")


def test_no_pisa_una_grabacion_anterior(tmp_path, monkeypatch, capsys):
    check_wake.save_wav(tmp_path / "intento_01.wav", [np.zeros(CHUNK, dtype=np.int16)])
    monkeypatch.setattr(sys, "argv", ["check_wake.py", "--aciertos", "1", "--guardar-audio", str(tmp_path)])

    with pytest.raises(SystemExit):
        check_wake.main()

    assert "ya hay intentos guardados" in capsys.readouterr().err


def test_repuntuar_sin_wav_lo_dice(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_wake.py", "--repuntuar", str(tmp_path)])

    with pytest.raises(SystemExit):
        check_wake.main()

    assert "no hay intento_*.wav" in capsys.readouterr().err



# --- Grabar clips para entrenar ----------------------------------------------------

class LevelVAD:
    """Voz si el tramo pasa de 0,05 (los tramos de prueba son constantes)."""

    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1

    def probability(self, frame):
        return 0.9 if abs(frame[0]) > 0.05 else 0.0


def clip_frames(level=0.3, voice_s=1.0):
    """Lo que da el micrófono en un clip: 2 s de calentamiento y 6 s de ventana con voz a 1 s."""
    return frames(2.0) + frames(1.0) + frames(voice_s, level) + frames(6.0 - 1.0 - voice_s)


def refill_with(*clips):
    """drain de mentira: en cada clip, la cola tiene lo de ese clip."""
    pending = list(clips)

    def refill(stream):
        while not stream.frames.empty():
            stream.frames.get()

        for frame in pending.pop(0):
            stream.frames.put(frame)

    return refill


def answers(*values):
    values = list(values)
    return lambda prompt="": values.pop(0) if values else ""


def test_slug_y_numeracion(tmp_path):
    assert check_wake.slug("Oye Asia") == "oye_asia" and check_wake.slug("¿O ya sí a?") == "o_ya_si_a"
    assert check_wake.next_index(tmp_path) == 1

    for name in ("001.wav", "007.wav", "nota.wav"):
        (tmp_path / name).write_bytes(b"")

    assert check_wake.next_index(tmp_path) == 8


def test_recorta_a_la_voz_con_margen():
    window = frames(1.0) + frames(1.0, 0.3) + frames(1.0)

    clip = check_wake.trim_to_voice(frames(2.0, 0.3), window, LevelVAD(), 0.5)

    # 31 tramos de voz y 9 (0,3 s) a cada lado; el calentamiento no entra.
    assert len(clip) == (31 + 2 * 9) * 512
    assert check_wake.trim_to_voice([], frames(2.0), LevelVAD(), 0.5) is None


def test_avisa_si_satura_o_si_es_muy_bajo():
    loud = check_wake.clip_report(np.full(16000, 0.995, dtype=np.float32))
    quiet = check_wake.clip_report(np.full(16000, 0.01, dtype=np.float32))
    fine = check_wake.clip_report(np.full(16000, 0.3, dtype=np.float32))

    assert loud["satura"] and not loud["bajo"] and "satura" in check_wake.describe_clip(loud)
    assert quiet["bajo"] and not quiet["satura"] and "muy bajo" in check_wake.describe_clip(quiet)
    assert not fine["satura"] and not fine["bajo"] and "Aviso" not in check_wake.describe_clip(fine)
    assert fine["segundos"] == 1.0 and fine["pico_dbfs"] == -10.5


def test_graba_repite_y_sigue_la_numeracion(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "positivos" / "oye_asia"
    folder.mkdir(parents=True)
    check_wake.save_wav(folder / "004.wav", [np.zeros(CHUNK, dtype=np.int16)])
    # Clip 1 sin voz (se repite solo), clip 2 lo repite el usuario, clips 3 y 4 se guardan.
    monkeypatch.setattr(check_wake, "drain", refill_with(frames(8.0), clip_frames(), clip_frames(), clip_frames(0.995)))
    microphone = Microphone([])

    saved = check_wake.record([("oye Asia", 2)], tmp_path / "positivos", LevelVAD(), 0.5, microphone,
                              ask=answers("", "", "r", "", "", "", ""))

    assert microphone.opened == 1
    assert [row["archivo"] for row in saved["oye Asia"]] == ["005.wav", "006.wav"]
    assert saved["oye Asia"][1]["satura"] is True
    out = capsys.readouterr().out
    assert "No oí voz" in out and "Habla ahora: «oye Asia»" in out and "satura" in out

    with wave.open(str(folder / "005.wav"), "rb") as clip:
        assert (clip.getframerate(), clip.getnchannels(), clip.getsampwidth()) == (16000, 1, 2)
        assert clip.getnframes() == (31 + 2 * 9) * 512


def test_grabar_necesita_la_frase(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_wake.py", "--grabar", "3"])

    with pytest.raises(SystemExit):
        check_wake.main()

    assert "--grabar necesita --frase" in capsys.readouterr().err



def test_negativos_una_frase_tras_otra_en_su_carpeta(tmp_path, monkeypatch, capsys):
    plan = check_wake.negative_plan(1)
    monkeypatch.setattr(check_wake, "drain", refill_with(*[clip_frames() for _ in plan]))

    saved = check_wake.record(plan, tmp_path / "negativos", LevelVAD(), 0.5, Microphone([]), ask=answers())

    assert [phrase for phrase, _ in plan] == ["oye", "Asia", "hoy hacia", "oye Alicia", "Asia Menor", "o ya sí a", "hey"]
    assert sorted(path.name for path in (tmp_path / "negativos").iterdir()) == sorted(
        ["oye", "asia", "hoy_hacia", "oye_alicia", "asia_menor", "o_ya_si_a", "hey"])
    assert all(len(rows) == 1 for rows in saved.values())
    assert (tmp_path / "negativos" / "oye_alicia" / "001.wav").is_file()
    out = capsys.readouterr().out
    assert out.index("Habla ahora: «oye»") < out.index("Habla ahora: «Asia Menor»")


def test_negativos_por_defecto_tres_por_frase(monkeypatch):
    plans = []
    monkeypatch.setattr(check_wake, "record", lambda plan, root, *args, **kwargs: plans.append((plan, root)))
    monkeypatch.setattr(check_wake, "voice_vad", lambda: LevelVAD())
    monkeypatch.setattr(sys, "argv", ["check_wake.py", "--negativos"])

    assert check_wake.main() == 0

    [(plan, root)] = plans
    assert {count for _, count in plan} == {3} and root.name == "negativos" and root.parent.name == "wake"



def test_con_23_entradas_el_calentamiento_es_de_2_56_s(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    model = LoudModel()
    model.model_inputs = {"oye_asia_v0.1": 23}

    def refill(stream):
        while not stream.frames.empty():
            stream.frames.get()

        for frame in frames(2.56) + frames(1.0) + frames(1.0, 0.9) + frames(4.5):
            stream.frames.put(frame)

    monkeypatch.setattr(check_wake, "drain", refill)
    check_wake.hits(model, 1, 0.5, tmp_path, Microphone([]))

    # 32 tramos de calentamiento y 75 de ventana.
    with wave.open(str(tmp_path / "intento_01.wav"), "rb") as saved:
        assert saved.getnframes() == (32 + 75) * CHUNK


def test_repuntuar_completa_el_calentamiento_con_silencio(tmp_path):
    quiet = [np.full(CHUNK, 100, dtype=np.int16)]
    check_wake.save_wav(tmp_path / "intento_01.wav", quiet * 100)
    model = LoudModel()
    model.model_inputs = {"oye_asia_v0.1": 23}

    check_wake.rescore(model, tmp_path, 0.5)

    # 7 tramos de silencio delante de los 25 del archivo, y los 75 de la ventana.
    assert model.seen == 7 + 100
