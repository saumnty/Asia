import pytest

from tools.review_findings import (
    NO_FINDINGS_MARK,
    locate_quote,
    numbered,
    parse_findings,
    render_report,
    verify_findings,
)

CONTENT = """import json

def guardar(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

def leer(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
"""


def finding(line, quote, claim):
    return {"line": line, "quote": quote, "claim": claim}


def test_parse_findings_bloques_con_markdown_y_acentos():
    response = """Aquí van:

**HALLAZGO 1:**
LÍNEA: 4
CITA: `4 | with open(path, "w", encoding="utf-8") as f:`
CLAIM: trunca el archivo antes de escribir
y un fallo deja el archivo vacío.

HALLAZGO:
- LINEA: línea 9
- CITA: "return json.load(f)"
- CLAIM: falla si el JSON está corrupto
"""

    assert parse_findings(response) == [
        finding(
            4,
            'with open(path, "w", encoding="utf-8") as f:',
            "trunca el archivo antes de escribir\ny un fallo deja el archivo vacío.",
        ),
        finding(9, "return json.load(f)", "falla si el JSON está corrupto"),
    ]


def test_parse_findings_lista_markdown_como_la_escribe_qwen():
    # Formato real de qwen2.5-coder:7b: ignora los bloques y escribe una lista.
    response = """ANALISIS:

1. **Línea 9**: `json.dump(data, f)`
   - CLAIM: esto se descarta, es del análisis

HALLAZGOS:

1. **Línea 4**: `with open(path, "w", encoding="utf-8") as f:`
   - CLAIM: trunca el archivo antes de escribir.

2. **LINEA: 9**
   ```python
   return json.load(f)
   ```
   Falla si el JSON está corrupto.
"""

    assert parse_findings(response) == [
        finding(4, 'with open(path, "w", encoding="utf-8") as f:', "trunca el archivo antes de escribir."),
        finding(9, "return json.load(f)", "Falla si el JSON está corrupto."),
    ]


def test_parse_findings_sin_hallazgos():
    assert parse_findings(NO_FINDINGS_MARK) == []
    assert parse_findings("No encontré problemas.") == []


def test_locate_quote_ignora_indentacion_y_espacios():
    assert locate_quote('with open(path,"w",encoding="utf-8")  as f:', CONTENT) == 4


def test_locate_quote_elige_la_aparicion_mas_cercana():
    assert locate_quote('encoding="utf-8") as f:', CONTENT, hint=1) == 4
    assert locate_quote('encoding="utf-8") as f:', CONTENT, hint=12) == 8


def test_locate_quote_varias_lineas():
    quote = 'def guardar(path, data):\n with open(path, "w"'
    assert locate_quote(quote, CONTENT) == 3


@pytest.mark.parametrize("quote", ["", "f)", "no existe en el archivo"])
def test_locate_quote_sin_coincidencia(quote):
    assert locate_quote(quote, CONTENT) is None


def test_verify_corrige_linea_descarta_y_deduplica():
    findings = [
        finding(40, 'with open(path, "w", encoding="utf-8") as f:', "trunca el archivo"),
        finding(4, 'open(path, "w", encoding="utf-8")', "trunca el archivo"),
        finding(5, 'with open(path, "w", encoding="utf-8") as f:', "otra cosa distinta"),
        finding(2, "data = cargar(path)", "KeyError inventado"),
        finding(3, "data = cargar(path)", "KeyError inventado"),
        finding(9, "return json.load(f)", "falla con JSON corrupto"),
    ]

    result = verify_findings(findings, CONTENT)

    assert result["verified"] == [
        finding(4, 'with open(path, "w", encoding="utf-8") as f:', "trunca el archivo"),
        finding(9, "return json.load(f)", "falla con JSON corrupto"),
    ]
    assert result["unverified"] == [finding(2, "data = cargar(path)", "KeyError inventado")]
    assert result["discarded"] == 2
    assert result["duplicates"] == 3


def test_verify_sin_cita_no_cuenta_como_repetido():
    findings = [finding(1, "", "uno"), finding(2, "", "algo totalmente distinto")]

    result = verify_findings(findings, CONTENT)

    assert len(result["unverified"]) == 2
    assert result["duplicates"] == 0


def test_render_omite_sin_verificar_por_defecto():
    response = """HALLAZGO:
LINEA: 1
CITA: return json.load(f)
CLAIM: falla con JSON corrupto

HALLAZGO:
LINEA: 2
CITA: data = cargar(path)
CLAIM: KeyError inventado
"""

    report = render_report("a.py", response, CONTENT)

    assert "Citas encontradas en el archivo (análisis del modelo, no verificado):" in report
    assert "VERIFICADO" not in report
    assert "1. Línea 9: `return json.load(f)`" in report
    assert "KeyError" not in report
    assert "SIN VERIFICAR" not in report
    assert "Descartados por cita no encontrada: 1" in report
    assert "CONFIRMED" not in report

    report = render_report("a.py", response, CONTENT, show_unverified=True)

    assert "SIN VERIFICAR (cita no encontrada en el archivo):" in report
    assert "KeyError inventado" in report


def test_render_sin_hallazgos_verificables():
    report = render_report("a.py", NO_FINDINGS_MARK, CONTENT)

    assert "El modelo no reportó problemas con una cita que exista en el archivo." in report
    assert "Detección automática" not in report
    assert "Descartados por cita no encontrada: 0" in report


def test_numbered_alinea_numeros():
    assert numbered("a\nb") == "1 | a\n2 | b"
    assert numbered("\n" * 9 + "x").splitlines()[-1] == "10 | x"


@pytest.mark.parametrize("tail", ["\n\nSIN_HALLAZGOS", "\nSIN_HALLAZGOS\n", "\n**SIN_HALLAZGOS**", " SIN_HALLAZGOS"])
def test_sin_hallazgos_despues_de_un_hallazgo_no_se_filtra(tail):
    # Visto en "revisa a fondo X": el modelo cierra con SIN_HALLAZGOS aunque
    # haya reportado algo, y quedaba suelto debajo del último hallazgo.
    response = (
        "ANALISIS:\nnada raro\n\nHALLAZGOS:\nHALLAZGO:\nLINEA: 16\n"
        "CITA: json.dump(data, f)\nCLAIM: no es atómico" + tail
    )

    assert parse_findings(response) == [finding(16, "json.dump(data, f)", "no es atómico")]
    assert NO_FINDINGS_MARK not in render_report("a.py", response, CONTENT)
