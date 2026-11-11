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
