"""Tiempos de una sesión real con --timing (Ollama de verdad).

Corre en una sola sesión interactiva, como un uso normal, los mensajes de
la medición: así se ve si el prompt del IntentEngine se reutiliza (caché de
Ollama) de un mensaje al siguiente.

    .venv\\Scripts\\python.exe test\\manual\\check_speed.py
    .venv\\Scripts\\python.exe test\\manual\\check_speed.py --sin-archivo

--sin-archivo omite "explica @ROADMAP.md" (la más larga: unos 3 minutos).
Al final imprime una tabla con la línea de tiempos de cada mensaje.
"""
import argparse
import io
import sys
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings_manager import SettingsManager
from core.paths import PROJECT_ROOT
from core.session import Session

Session.set_paths(project_root=PROJECT_ROOT, user_cwd=ROOT)

import launcher
from core.brain import Brain
from core.timing import SETTING

MESSAGES = ["hola", "qué es un grafo bipartito", "si", "explica @ROADMAP.md"]


class Tee(io.StringIO):
    """Guarda stderr y lo sigue mostrando."""

    def write(self, text):
        sys.__stderr__.write(text)
        return super().write(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin-archivo", action="store_true", help='omite "explica @ROADMAP.md"')
    args = parser.parse_args()

    messages = [m for m in MESSAGES if not (args.sin_archivo and m.startswith("explica @"))]
    SettingsManager.set_overrides({**SettingsManager.overrides, SETTING: True})
    lines = iter([*messages, "salir"])
    err = Tee()

    with redirect_stderr(err):
        launcher.interactive_mode(Brain(), read=lambda prompt: print(prompt, end="") or next(lines))

    timings = [line for line in err.getvalue().splitlines() if line.startswith("[tiempos]")]

    print("\n\n=== Resumen")
    for message, line in zip(messages, timings):
        print(f"{message!r}\n  {line}")

    if len(timings) != len(messages):
        print(f"(faltan líneas de tiempos: {len(timings)} de {len(messages)})")


if __name__ == "__main__":
    main()
