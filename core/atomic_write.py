"""Escritura atómica de JSON: o queda el archivo nuevo completo o el viejo.

open(ruta, "w") vacía el archivo al abrirlo; si el proceso se interrumpe a
mitad de json.dump, el archivo queda vacío o cortado. Aquí se escribe a un
temporal en la misma carpeta (misma partición, así os.replace es un
renombrado atómico) y solo al final se reemplaza el destino.
"""
import contextlib
import json
import os
import stat
import tempfile
from pathlib import Path


def write_json_atomic(path, data, *, indent=4, ensure_ascii=False):
    """Escribe data como JSON en path sin dejarlo nunca a medias.

    El formato es el mismo que json.dump con open(path, "w", encoding="utf-8")
    (modo texto, así que en Windows los saltos de línea siguen siendo \\r\\n).
    Si algo falla antes del reemplazo, path queda intacto y el temporal se
    borra; la excepción se propaga.
    """
    path = Path(path)

    fd, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp"
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
            f.flush()
            os.fsync(f.fileno())

        # mkstemp crea el temporal con permisos 0600; se conservan los del
        # archivo original (importa en Linux, en Windows no cambia nada).
        if path.exists():
            os.chmod(temp_name, stat.S_IMODE(path.stat().st_mode))

        os.replace(temp_name, path)
    except BaseException:
        # BaseException: también Ctrl+C (KeyboardInterrupt) a mitad de escribir.
        with contextlib.suppress(FileNotFoundError):
            os.remove(temp_name)
        raise
