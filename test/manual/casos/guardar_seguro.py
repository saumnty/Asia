import json
import os
import tempfile

nombre_archivo = "config.json"

with open(nombre_archivo, encoding="utf-8") as f:
    datos = json.load(f)

datos["version"] = datos.get("version", 0) + 1

carpeta = os.path.dirname(os.path.abspath(nombre_archivo))
descriptor, temporal = tempfile.mkstemp(dir=carpeta, suffix=".tmp")

try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)
    os.replace(temporal, nombre_archivo)
except Exception:
    os.remove(temporal)
    raise
