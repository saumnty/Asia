"""Texto de una imagen (fase V, primera parte): el OCR integrado de Windows, sin instalar nada.

Para capturas de texto (errores, código, enunciados): el texto va al modelo como un
adjunto, con la etiqueta "adjunto" (local por defecto). Las fotos sin texto necesitan
un modelo con visión, que es la segunda parte. La imagen no sale de la máquina.
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = Path(__file__).with_name("ocr_windows.ps1")
TIMEOUT_S = 60
PASTE_DIR = Path(tempfile.gettempdir()) / "asia_pegado"


class OcrError(Exception):
    pass


def image_text(path: Path) -> str:
    """El texto reconocido en la imagen (una línea por renglón); "" si no hay texto."""
    if sys.platform != "win32":
        raise OcrError("el OCR integrado solo está en Windows")

    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-Path", str(path)],
            capture_output=True, timeout=TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OcrError(f"no pude ejecutar el OCR de Windows ({e})") from e

    if done.returncode != 0:
        error = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise OcrError(error[-1] if error else f"el OCR de Windows salió con {done.returncode}")

    return done.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()


def pasted_image(grab=None, folder: Path = None):
    """La imagen del portapapeles guardada como PNG en una carpeta temporal; None si no hay imagen."""
    if grab is None:
        from PIL import ImageGrab

        grab = ImageGrab.grabclipboard

    image = grab()

    # Con archivos copiados, grabclipboard devuelve la lista de rutas, no una imagen.
    if image is None or isinstance(image, list) or not hasattr(image, "save"):
        return None

    folder = folder or PASTE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"pegado_{time.strftime('%Y%m%d_%H%M%S')}.png"
    image.save(path, "PNG")
    return path
