import pytest

from core.paths import PROJECT_ROOT
from tools.write_safety import find_truncating_rewrites

CASES = PROJECT_ROOT / "test" / "manual" / "casos"


def lines_of(code):
    return [finding["line"] for finding in find_truncating_rewrites(code)]


def test_lee_y_reescribe_el_mismo_archivo():
    code = """import json
ruta = "datos.json"
with open(ruta, encoding="utf-8") as f:
    datos = json.load(f)
datos["n"] = 1
with open(ruta, "w", encoding="utf-8") as f:
    json.dump(datos, f)
"""
    findings = find_truncating_rewrites(code)

    assert len(findings) == 1
    assert findings[0]["line"] == 6
    assert findings[0]["quote"] == 'with open(ruta, "w", encoding="utf-8") as f:'
    assert "línea 3" in findings[0]["claim"]
    assert "vacía el archivo antes de escribir" in findings[0]["claim"]
    assert "corrupto" in findings[0]["claim"]


@pytest.mark.parametrize(
    "read",
    [
        'data, meta = arff.loadarff(ruta)',
        'df = pd.read_csv(ruta)',
        'texto = open(ruta).read()',
        'texto = open(ruta, "rb").read()',
        'texto = Path(ruta).read_text()',
        'texto = open("datos.txt").read()',
    ],
)
def test_distintas_formas_de_leer(read):
    code = f'ruta = "datos.txt"\n{read}\nopen(ruta, "w").write("x")\n'

    assert lines_of(code) == [3]


@pytest.mark.parametrize(
    "write",
    [
        'open(ruta, mode="w")',
        'open(ruta, "wb")',
        'open(ruta, "w+")',
        'Path(ruta).write_text("x")',
        'Path(ruta).open("w")',
    ],
)
def test_distintas_formas_de_escribir_truncando(write):
    code = f'ruta = "datos.txt"\ntexto = open(ruta).read()\n{write}\n'

    assert lines_of(code) == [3]


@pytest.mark.parametrize(
    "code",
    [
        # Escribe sin haber leído.
        'ruta = "a.txt"\nopen(ruta, "w").write("x")\n',
        # Escribe antes de leer.
        'ruta = "a.txt"\nopen(ruta, "w").write("x")\nopen(ruta).read()\n',
        # Lee un archivo y escribe otro.
        'open("a.txt").read()\nopen("b.txt", "w").write("x")\n',
        # Modos que no truncan.
        'ruta = "a.txt"\nopen(ruta).read()\nopen(ruta, "a").write("x")\n',
        'ruta = "a.txt"\nopen(ruta).read()\nopen(ruta, "r+").write("x")\n',
        # Respaldo antes de reescribir.
        'ruta = "a.txt"\nopen(ruta).read()\nshutil.copy2(ruta, ruta + ".bak")\nopen(ruta, "w").write("x")\n',
        # Temporal antes de reescribir.
        'ruta = "a.txt"\nopen(ruta).read()\nfd, tmp = tempfile.mkstemp()\nopen(ruta, "w").write("x")\n',
        # Escribe primero a otro archivo (temporal) y luego al original.
        'ruta = "a.txt"\nopen(ruta).read()\nopen("a.tmp", "w").write("x")\nopen(ruta, "w").write("x")\n',
    ],
)
def test_no_avisa(code):
    assert lines_of(code) == []


def test_codigo_invalido_no_avisa():
    assert find_truncating_rewrites("def (:\n") == []


def test_variable_reasignada_no_se_confunde_con_constante():
    # ruta toma dos valores: no se resuelve a "a.txt", se compara por nombre.
    code = 'ruta = "a.txt"\nruta = "b.txt"\nopen("a.txt").read()\nopen(ruta, "w").write("x")\n'

    assert lines_of(code) == []


@pytest.mark.parametrize("case, line", [("moda.py", 30), ("eliminar.py", 23)])
def test_casos_del_banco_avisan_en_el_open_w(case, line):
    content = (CASES / case).read_text(encoding="utf-8")

    assert lines_of(content) == [line]


def test_caso_seguro_del_banco_no_avisa():
    content = (CASES / "guardar_seguro.py").read_text(encoding="utf-8")

    assert lines_of(content) == []
