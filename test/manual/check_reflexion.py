"""Comprobación de la reflexión (fase R) con el modelo real.

Todo va a una carpeta temporal: pendientes, resumen de sesión y una memoria de
prueba con duplicados y contradicciones. No toca data/reflexion ni
memory/memory.json. Hace una sesión corta con Ollama, mide el resumen al salir,
la apertura siguiente, el resumen sin modelo y /revisar memoria, respondiendo
"n" a todo: la memoria de prueba debe quedar igual.

    .venv\\Scripts\\python.exe test\\manual\\check_reflexion.py
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import paths
from core.session import Session

Session.set_paths(project_root=paths.PROJECT_ROOT, user_cwd=ROOT)

TMP = Path(tempfile.mkdtemp(prefix="asia_reflexion_"))
paths.TASKS_FILE = TMP / "pendientes.json"
paths.SESSION_SUMMARY_FILE = TMP / "ultima_sesion.json"

import launcher
from config.settings_manager import SettingsManager
from core.brain import Brain
from core.memory_review import find_proposals
from core.reflection import SessionLog, load_summary, local_model, opening_text, summarize
from memory.memory_manager import MemoryManager

MESSAGES = ["/pendiente Revisar el PID del Bolitabot", "qué es un grafo bipartito", "muestra el proyecto activo",
            "/pendientes"]

# Lo que las reglas deben encontrar, y lo que solo puede encontrar el modelo.
TEST_MEMORY = {
    "nombre": "Santiago",
    "universidad": "UAM",
    "mi_universidad": "UNAM",
    "color_favorito": "amarillo",
    "mi color favorito": "Amarillo",
    "ciudad": "Ciudad de México",
    "vivo_en": "Puebla",
    "proyecto": "Asia",
}


def section(title):
    print(f"\n=== {title} ===")


def session_with_model(brain):
    lines = iter([*MESSAGES, "salir"])
    start = []

    def read(prompt):
        line = next(lines)

        if line == "salir":
            start.append(time.perf_counter())

        print(f"{prompt.strip()} {line}")
        return line

    launcher.interactive_mode(launcher.with_confirmation(brain), read=read)
    return time.perf_counter() - start[0]


def main():
    print(f"Carpeta temporal: {TMP}")
    brain = Brain()

    section("Sesión y resumen al salir (modelo real)")
    seconds = session_with_model(brain)
    summary = load_summary()
    print(f"\nSalir tardó {seconds:.1f} s. Origen del resumen: {summary['origen']}.")

    section("Apertura siguiente (sin modelo)")
    start = time.perf_counter()
    text = opening_text()
    print(f"{text}\n({(time.perf_counter() - start) * 1000:.1f} ms)")

    section("Modelo que no responde a tiempo")
    log = SessionLog()
    log.add("qué es un grafo", "Un grafo es...", "chat")
    log.add("revisa core/brain.py", "Revisé...", "review_file")
    start = time.perf_counter()
    text, source = summarize(log, local_model(brain), 0.05)
    print(f"{source}: {text} ({time.perf_counter() - start:.1f} s)")

    section("/revisar memoria (memoria de prueba, respuestas: n)")
    memory = MemoryManager(TMP / "memory.json")
    memory.save(TEST_MEMORY)
    brain.memory = memory
    timeout = SettingsManager().get("reflection")["memory_review_timeout_s"]
    start = time.perf_counter()
    proposals, used = find_proposals(memory.load(), local_model(brain), timeout)
    print(f"{len(proposals)} casos en {time.perf_counter() - start:.1f} s (modelo: {'sí' if used else 'no'}).")
    print("(Solo las reglas: " + str(len(find_proposals(memory.load())[0])) + " casos.)")

    launcher.review_memory(brain, lambda prompt: print(prompt + "n") or "n", deep=True)

    same = memory.load() == TEST_MEMORY
    print(f"\nLa memoria de prueba quedó igual: {'sí' if same else 'NO'}.")
    print(json.dumps(memory.load(), ensure_ascii=False))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
