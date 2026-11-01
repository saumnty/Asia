"""El código de los modelos de Simulink (fase H).

Un .slx es un zip con XML. El de cada bloque "MATLAB Function", y el de las
funciones MATLAB de Stateflow, está en simulink/stateflow/chart_N.xml, en un
<P Name="script"> dentro de un <chart> con el nombre del bloque. No se lee nada más:
los bloques gráficos no son texto, y los estados y transiciones de Stateflow tampoco
se extraen.

El archivo se indexa como un texto: un bloque tras otro, cada uno con su marca. Las
líneas de un fragmento son las del bloque, las que se ven al abrirlo en MATLAB.
"""
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SUFFIX = ".slx"
CHARTS = "simulink/stateflow/"
BLOCK_MARK = "%%%% Bloque de Simulink: "
# Un chart real pesa kilobytes: un zip que se infla a esto no es un modelo.
MAX_XML_BYTES = 16 * 1024 * 1024
UNNAMED = "bloque sin nombre"


def is_model_name(path: Path) -> bool:
    return path.suffix.lower() == SUFFIX


def is_model(path: Path) -> bool:
    return is_model_name(path) and zipfile.is_zipfile(path)


def parameter(element, name: str) -> str:
    return next((p.text or "" for p in element.findall("P") if p.get("Name") == name), "")


def parsed(data: bytes):
    """El XML de un chart, o None si declara entidades: un modelo real no las usa."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return None

    return ET.fromstring(data)


def blocks_of(path: Path) -> list:
    """[(nombre del bloque, código)] del modelo."""
    blocks = []

    with zipfile.ZipFile(path) as model:
        names = sorted(
            info.filename for info in model.infolist()
            if info.filename.startswith(CHARTS) and info.filename.endswith(".xml")
            and info.file_size <= MAX_XML_BYTES
        )

        for name in names:
            root = parsed(model.read(name))

            for chart in root.iter("chart") if root is not None else ():
                blocks += [
                    (parameter(chart, "name") or UNNAMED, script.text)
                    for script in chart.iter("P")
                    if script.get("Name") == "script" and (script.text or "").strip()
                ]

    return blocks


def model_text(path: Path) -> str:
    """Los bloques como un solo texto, para indexarlo y comparar su hash."""
    return "\n".join(f"{BLOCK_MARK}{name}\n{script}" for name, script in blocks_of(path))


def split_blocks(text: str) -> list:
    """[(nombre del bloque, código)] de lo que escribió model_text."""
    blocks = []

    for line in text.splitlines():
        if line.startswith(BLOCK_MARK):
            blocks.append((line.removeprefix(BLOCK_MARK), []))
        elif blocks:
            blocks[-1][1].append(line)

    return [(name, "\n".join(lines)) for name, lines in blocks]
