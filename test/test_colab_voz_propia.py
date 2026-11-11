"""El cuaderno de Colab de la voz propia (sin Colab, sin audios): válido, compila y cumple lo pedido."""
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_colab_oye_asia import python_of  # noqa: E402

NOTEBOOK = Path(__file__).parent / "manual" / "colab" / "entrenar_voz_propia.ipynb"


def notebook():
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def code_cells():
    return [cell for cell in notebook()["cells"] if cell["cell_type"] == "code"]


def all_code() -> str:
    return "\n".join("".join(cell["source"]) for cell in code_cells())


def test_es_un_cuaderno_valido_y_compila():
    data = notebook()

    assert data["nbformat"] == 4 and data["metadata"]["accelerator"] == "GPU"

    for number, cell in enumerate(data["cells"]):
        assert cell["cell_type"] in ("markdown", "code") and isinstance(cell["source"], list)

        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
            compile(python_of(cell), f"celda {number}", "exec")


def test_la_configuracion_va_primero():
    values = {}

    for node in ast.parse(python_of(code_cells()[0])).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass

    assert values["BASE"] == "ald" and values["BATCH_SIZE"] == 16 and values["ESPEAK_VOICE"] == "es-419"
    assert set(values["BASES"]) == {"ald", "sharvard"}
    assert values["BASES"]["ald"]["path"] == "es_MX/ald/medium" and values["BASES"]["sharvard"]["path"] == "es_ES/sharvard/medium"
    assert all(len(base["sha256"]) == 64 for base in values["BASES"].values())
    assert values["DATASET_ZIP"].endswith("_22050.zip")


def test_checkpoints_en_drive_y_se_puede_reanudar():
    text = all_code()

    assert "drive.mount" in text and "/checkpoints" in text
    assert "--ckpt_path" in text and "--model.warmstart_ckpt" in text
    assert "os.replace" in text  # la copia a Drive es atómica


def test_exporta_a_onnx_con_su_json():
    text = all_code()

    assert "piper.train.export_onnx" in text and ".onnx.json" in text and "--output-file" in text


def test_borra_los_audios_de_drive_al_terminar():
    last = "".join(code_cells()[-1]["source"])

    assert "DELETE_AUDIO" in last and "rmtree" in last and "entrada" in last
    assert "Papelera" in "".join(notebook()["cells"][-2]["source"])


def test_las_instalaciones_solo_van_dentro_del_cuaderno():
    # Todo pip/apt va como línea de shell de Colab (!): nunca se ejecuta en el PC.
    installs = [line.strip() for line in all_code().splitlines() if "pip install" in line or "apt-get" in line]

    assert len(installs) >= 2 and all(line.startswith("!") for line in installs)


def test_no_lleva_datos_ni_claves():
    raw = NOTEBOOK.read_text(encoding="utf-8")

    for forbidden in ("GEMINI", "api_key", "AIza", "AsiaVoz"):
        assert forbidden not in raw


# --- Modo humo ------------------------------------------------------------------------

def verdicts():
    """Las funciones puras de la sección 4b, ejecutadas aquí sin Colab."""
    import os

    cell = next(c for c in code_cells() if "def judge_max_time" in "".join(c["source"]))
    namespace = {"os": os}
    exec(compile(python_of(cell), "veredictos", "exec"), namespace)
    return namespace


def config_values():
    values = {}

    for node in ast.parse(python_of(code_cells()[0])).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass

    return values


def test_el_modo_humo_se_activa_con_una_variable_al_inicio():
    values = config_values()

    assert values["SMOKE"] is False and values["SMOKE_PHRASES"] == 20 and values["SMOKE_MAX_TIME"] == "00:00:03:00"
    assert "lines[:SMOKE_PHRASES]" in all_code()


def test_los_segundos_de_max_time():
    v = verdicts()

    assert v["seconds_of"]("00:00:03:00") == 180 and v["seconds_of"]("00:03:30:00") == 12600 and v["seconds_of"]("01:00:00:00") == 86400


def test_a_max_time_se_respeta():
    judge = verdicts()["judge_max_time"]

    assert judge(0, 200, False, 180, 240)[0]
    assert not judge(0, 200, True, 180, 240)[0]    # hubo que matarlo
    assert not judge(1, 200, False, 180, 240)[0]   # falló
    assert not judge(0, 20, False, 180, 240)[0]    # paró antes: no fue por max_time
    assert not judge(0, 600, False, 180, 240)[0]   # tardó demasiado


def test_b_reanudar_sigue_contando_y_no_empieza_de_cero():
    judge = verdicts()["judge_resume"]
    before = {"epoch": 40, "global_step": 80}

    assert judge(0, before, {"epoch": 42, "global_step": 84})[0]
    assert not judge(0, before, {"epoch": 1, "global_step": 2})[0]    # empezó de cero
    assert not judge(0, before, before)[0]                            # no avanzó
    assert not judge(0, None, None)[0]                                # no había checkpoint
    assert not judge(1, before, {"epoch": 42, "global_step": 84})[0]  # falló


def write_wav(path, seconds, level):
    import math
    import struct
    import wave

    rate = 22050
    with wave.open(str(path), "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(rate)
        clip.writeframes(b"".join(struct.pack("<h", int(level * 32767 * math.sin(2 * math.pi * 220 * i / rate)))
                                  for i in range(int(seconds * rate))))


def test_c_exporta_y_sintetiza_una_frase_que_suena(tmp_path):
    judge = verdicts()["judge_synth"]
    good, silent, short = tmp_path / "bien.wav", tmp_path / "silencio.wav", tmp_path / "corta.wav"
    write_wav(good, 1.0, 0.3)
    write_wav(silent, 1.0, 0.0)
    write_wav(short, 0.2, 0.3)

    assert judge(True, True, str(good))[0]
    assert not judge(False, False, str(good))[0]                   # no se exportó
    assert not judge(True, False, str(good))[0]                    # no se sintetizó
    assert not judge(True, True, str(tmp_path / "nada.wav"))[0]    # no hay audio
    assert not judge(True, True, str(silent))[0] and not judge(True, True, str(short))[0]


def test_cada_punto_imprime_check_o_cruz():
    text = all_code()

    assert "✅" in text and "❌" in text and text.count("show(judge_") == 3
    assert "(a)" in text and "(b)" in text and "(c)" in text


def test_el_modo_humo_no_toca_lo_real():
    text = all_code()

    # Rutas propias para los checkpoints, los registros y la voz de la prueba.
    assert "checkpoints_humo" in text and 'LOGS = f"{LOCAL}/humo"' in text and 'ONNX = f"{LOCAL}/humo/' in text
    # Reanuda con --ckpt_path desde el last.ckpt de Drive, y en la primera vuelta no.
    assert "run_training(100000, SMOKE_MAX_TIME, False" in text and 'run_training(before["epoch"] + 2, "00:00:10:00", True' in text
    # En humo, el borrado solo quita lo suyo (y no el zip de entrada).
    last = "".join(code_cells()[-1]["source"])
    smoke_branch = last[last.index("if SMOKE:"):last.index("elif DELETE_AUDIO")]
    assert "entrada" not in smoke_branch.replace("el zip de entrada", "") and "humo" in smoke_branch
    # El entrenamiento real no corre en modo humo.
    assert "if SMOKE:" in text and "run_training(MAX_EPOCHS, SESSION_MAX_TIME" in text
