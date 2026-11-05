"""pagina_revision: con un revisar.csv inventado en una carpeta temporal."""
import csv
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "manual"))

import pagina_revision as tool  # noqa: E402
import transcribir_turbo  # noqa: E402

# id, small, turbo, coinciden, logprob turbo, motivos turbo
ROWS = [
    ("0001", "Hola amigo", "Hola amigo.", "sí", -0.2, ""),
    ("0002", "Ya no pasó el tren", "Ya no, pasó el tranvía", "", -0.5, ""),
    ("0003", "fui a la tienda", "fui a la tienda", "sí", -0.7, "avg_logprob < -0.6"),
    ("0004", "Mmm...", "Mmm.", "sí", -1.2, "avg_logprob < -0.6; una sola palabra"),
    ("0005", "es la una", "es la una", "sí", -0.9, "avg_logprob < -0.6"),
    ("0006", "tengo 2 perros", "tengo dos perros", "", -0.3, ""),
    ("0007", "</script><b>x</b>", "</script><b>x</b>", "sí", -0.1, ""),
]


def write_dataset(folder, turbo=True):
    folder.mkdir(parents=True, exist_ok=True)
    columns = transcribir_turbo.COLUMNS if turbo else ["id", "revisar", "motivos", "segundos", "texto", "avg_logprob"]

    with open(folder / "revisar.csv", "w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()

        for id_, small, turbo_text, agree, logprob, reasons in ROWS:
            writer.writerow({"id": id_, "segundos": "2.5", "coinciden": agree, "texto_small": small, "texto_turbo": turbo_text,
                             "avg_logprob_turbo": logprob, "motivos_turbo": reasons, "texto": small,
                             "avg_logprob": logprob, "motivos": reasons, "revisar": "sí" if reasons else ""})

    return folder


def embedded(text):
    return json.loads(re.search(r"const ROWS = (.*);\n", text).group(1).replace("<\\/", "</"))


def test_orden_primero_las_dudosas_luego_aceptadas_al_final_las_peores(tmp_path):
    page = tool.build(write_dataset(tmp_path / "fa")).read_text(encoding="utf-8")

    rows = embedded(page)
    # No coinciden (0002, 0006) y logprob de -0,8 a -0,6 (0003); aceptadas; peores, de mejor a peor.
    assert [row["id"] for row in rows] == ["0002", "0003", "0006", "0001", "0007", "0005", "0004"]
    assert [row["grupo"] for row in rows] == [1, 1, 1, 2, 2, 3, 3]
    assert "no coinciden" in rows[0]["motivos"]


def test_diferencias_marcadas_y_texto_inicial_de_turbo(tmp_path):
    rows = {row["id"]: row for row in embedded(tool.build(write_dataset(tmp_path / "fa")).read_text(encoding="utf-8"))}

    assert rows["0006"]["small"] == [["tengo", False], ["2", True], ["perros", False]]
    assert rows["0006"]["turbo"] == [["tengo", False], ["dos", True], ["perros", False]]
    # Mayúsculas, acentos y puntuación no cuentan como diferencia.
    assert not any(changed for _, changed in rows["0001"]["turbo"])
    assert rows["0002"]["texto"] == "Ya no, pasó el tranvía"


def test_un_solo_archivo_sin_internet_y_con_lo_pedido(tmp_path):
    page = tool.build(write_dataset(tmp_path / "fa")).read_text(encoding="utf-8")

    assert "http" not in page and "<link" not in page and "src=\"http" not in page
    assert "wavs/${row.id}.wav" in page
    # Un texto con </script> no rompe la página.
    assert page.count("</script>") == 1
    assert tool.RULE in page or "escritos en letra" in page
    assert "try { localStorage.setItem" in page and "try { saved = JSON.parse(localStorage.getItem" in page
    for needed in ("Aceptar", "Descartar", "Saltar", "Exportar", "metadata.csv", "revision.json",
                   "state-filter", "reason-filter", "min aceptados", "ArrowDown", 'key === "d"'):
        assert needed in page


def test_sin_turbo_usa_el_texto_de_small(tmp_path):
    rows = embedded(tool.build(write_dataset(tmp_path / "fa", turbo=False)).read_text(encoding="utf-8"))

    assert {row["id"]: row["texto"] for row in rows}["0002"] == "Ya no pasó el tren"
    assert all(row["turbo"] == [] for row in rows)


def test_main(tmp_path, monkeypatch, capsys):
    folder = write_dataset(tmp_path / "fa")
    monkeypatch.setattr(sys, "argv", ["pagina_revision.py", "--dataset", str(folder)])

    assert tool.main() == 0
    assert (folder / "revisar.html").exists() and "revisar.html" in capsys.readouterr().out


@pytest.mark.parametrize("words, other, expected", [
    (["a", "b"], ["a", "b"], [False, False]),
    (["a", "x", "b"], ["a", "b"], [False, True, False]),
    (["¡Hola!"], ["hola"], [False]),
])
def test_marked(words, other, expected):
    assert [changed for _, changed in tool.marked(words, other)] == expected
