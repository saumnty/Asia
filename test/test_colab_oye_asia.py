"""El cuaderno de Colab de "Oye Asia" y empaquetar_mi_voz (sin Colab, sin grabaciones reales)."""
import ast
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import empaquetar_mi_voz as tool  # noqa: E402
import generar_wake  # noqa: E402

NOTEBOOK = Path(__file__).parent / "manual" / "colab" / "entrenar_oye_asia.ipynb"


def notebook():
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def python_of(cell) -> str:
    """El Python de una celda sin las líneas de shell (!) ni las mágicas (%); un ! dentro de un bloque deja un pass."""
    lines = []

    for line in "".join(cell["source"]).splitlines():
        stripped = line.lstrip()

        if stripped.startswith(("!", "%")):
            lines.append(line[:len(line) - len(stripped)] + "pass")
        else:
            lines.append(line)

    # Una línea de shell partida con "\" sigue en la siguiente.
    text, skipping = [], False

    for original, line in zip("".join(cell["source"]).splitlines(), lines):
        if skipping:
            skipping = original.rstrip().endswith("\\")
            continue

        text.append(line)
        skipping = original.lstrip().startswith("!") and original.rstrip().endswith("\\")

    return "\n".join(text)


def test_es_un_cuaderno_valido():
    data = notebook()

    assert data["nbformat"] == 4 and isinstance(data["cells"], list) and data["cells"]
    assert data["metadata"]["accelerator"] == "GPU" and data["metadata"]["colab"]["gpuType"] == "T4"

    for cell in data["cells"]:
        assert cell["cell_type"] in ("markdown", "code") and isinstance(cell["source"], list)

        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None


def test_el_python_de_cada_celda_compila():
    for number, cell in enumerate(notebook()["cells"]):
        if cell["cell_type"] == "code":
            compile(python_of(cell), f"celda {number}", "exec")


def test_la_configuracion_va_primero_y_es_la_de_v0_2():
    code = [cell for cell in notebook()["cells"] if cell["cell_type"] == "code"]
    values = {}

    for node in ast.parse(python_of(code[0])).body:
        if isinstance(node, ast.Assign):
            values[node.targets[0].id] = ast.literal_eval(node.value)

    assert values["MODEL_NAME"] == "oye_asia_v0.2" and values["STEPS"] == 50000 and values["AUGMENTATION_ROUNDS"] == 2
    assert values["ACAV_ROWS"] == 1_000_000 and values["VALIDATION_SHARE"] == 0.5
    assert values["TEST_SHARE_SYNTHETIC"] == 0.10 and values["TEST_SHARE_MINE"] == 0.15 and values["MINE_REPEAT"] == 10
    assert values["THRESHOLDS"] == [0.5, 0.7, 0.9]


def test_lo_que_pide_el_entrenamiento():
    text = "".join("".join(cell["source"]) for cell in notebook()["cells"])

    for needed in ("torch==2.8.0", "torchaudio==2.8.0", "torchvision==0.23.0", '"datasets>=3,<4"', "--no-deps -e ./openwakeword",
                   "ai-edge-litert", "set_audio_backend", "generate_samples = None", "best_model.state_dict()",
                   "val_set_hrs", "resolve/4e17ae0/data/bal_train09.tar", "MIT_environmental_impulse_responses",
                   "files.upload()", "files.download", "nohup", "--augment_clips", "--train_model", "/proc/meminfo",
                   "v0.5.1", "dd"):
        assert needed in text, needed

    for absent in ("tensorflow", "onnx_tf", "piper-phonemize", "fma", "--generate_clips"):
        assert absent not in text.lower().replace("sin fma", "").replace("sin tensorflow", ""), absent


def test_no_lleva_rutas_ni_nombres_del_equipo():
    text = NOTEBOOK.read_text(encoding="utf-8")

    assert "C:\\\\" not in text and "AsiaVoz" not in text and "santy" not in text.lower()


# --- empaquetar_mi_voz ------------------------------------------------------------

def recordings(root, positives=3, negatives=("hoy_hacia", "oye")):
    (root / "positivos" / "oye_asia").mkdir(parents=True)

    for number in range(1, positives + 1):
        (root / "positivos" / "oye_asia" / f"{number:03d}.wav").write_bytes(generar_wake.wav_bytes(np.zeros(16000)))

    for phrase in negatives:
        (root / "negativos" / phrase).mkdir(parents=True)
        (root / "negativos" / phrase / "001.wav").write_bytes(generar_wake.wav_bytes(np.zeros(16000)))

    return root


def test_vuelve_a_armar_el_zip_con_todo(tmp_path):
    destination = tmp_path / "wake"
    destination.mkdir()
    (destination / "mi_voz.zip").write_bytes(b"viejo")
    (destination / "sintetico.zip").write_bytes(b"no se toca")

    counts = tool.repack(recordings(tmp_path / "grabaciones", positives=5), destination)

    assert counts == {"positivos": 5, "negativos": 2}
    with zipfile.ZipFile(destination / "mi_voz.zip") as archive:
        assert len(archive.namelist()) == 7 and "negativos/hoy_hacia/001.wav" in archive.namelist()

    assert (destination / "sintetico.zip").read_bytes() == b"no se toca"
    assert sorted(path.name for path in destination.iterdir()) == ["mi_voz.zip", "sintetico.zip"]


def test_sin_grabaciones_lo_dice(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["empaquetar_mi_voz.py", "--grabaciones", str(tmp_path), "--destino", str(tmp_path)])

    with pytest.raises(SystemExit):
        tool.main()

    assert "no hay grabaciones" in capsys.readouterr().err
