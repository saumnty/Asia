"""El prototipo del orbe (test/manual/visual/asia_orbe.html): un solo archivo, sin internet, y amarillo, no naranja."""
import colorsys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "test" / "manual" / "visual" / "asia_orbe.html"
DOC = ROOT / "docs" / "IDENTIDAD_VISUAL.md"


def palette() -> dict:
    block = re.search(r"const PALETTE = \{(.*?)\};", PAGE.read_text(encoding="utf-8"), re.S).group(1)
    return dict(re.findall(r'(\w+): "(#[0-9A-Fa-f]{6})"', block))


def hue(hex_color) -> tuple:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    return h * 360, saturation, r == g == b


def test_ningun_tono_tira_a_naranja():
    colors = palette()

    assert set(colors) == {"nucleo", "brillo", "fragmentos", "sombras", "fondo", "apagado"}
    for name, value in colors.items():
        degrees, saturation, gray = hue(value)

        if name == "fondo":
            # Neutro: mezclar el amarillo con él no le cambia el matiz.
            assert gray, value
        else:
            assert 44 <= degrees <= 50, (name, value, degrees)


def test_la_paleta_del_css_y_la_del_documento_son_la_del_script():
    text = PAGE.read_text(encoding="utf-8")
    doc = DOC.read_text(encoding="utf-8")

    for name, value in palette().items():
        assert f"--{name}: {value};" in text
        assert f"`{value}`" in doc, (name, value)


def test_un_solo_archivo_sin_internet():
    text = PAGE.read_text(encoding="utf-8")

    assert "http" not in text and "<link" not in text and "src=" not in text and "import " not in text


def test_estados_controles_y_menos_movimiento():
    text = PAGE.read_text(encoding="utf-8")

    for state in ("reposo", "esperando", "escuchando", "pensando", "hablando", "error"):
        assert f'data-state="{state}"' in text and f"  {state}:" in text
    assert 'type="range" id="volume"' in text
    assert "prefers-reduced-motion: reduce" in text and "reducedMotion()" in text
