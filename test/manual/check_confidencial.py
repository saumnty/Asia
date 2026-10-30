"""Comprobación a mano del modo confidencial (fase G).

Usa Asia de verdad (Brain, IntentEngine, ProviderRouter y Ollama local),
pero Gemini es SIMULADO: registra lo que recibiría y nunca se contacta el
servicio real, así que no hace falta la clave ni sale nada de la máquina.
La bitácora se escribe en una carpeta temporal.

    .venv\\Scripts\\python.exe test\\manual\\check_confidencial.py
    .venv\\Scripts\\python.exe test\\manual\\check_confidencial.py --sin-ollama

Cada caso imprime lo que respondió Asia, lo que habría recibido Gemini y
OK o FALLA. Con --sin-ollama solo corre los casos que no necesitan Ollama.
"""
import argparse
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings_manager import SettingsManager
from core import paths
from core.paths import PROJECT_ROOT
from core.session import Session

Session.set_paths(project_root=PROJECT_ROOT, user_cwd=ROOT)

import launcher
from core.brain import Brain

ATTACHMENT = "pruebas/buggy_calculator.py"
SECRET_KEY = "AIza" + "Z" * 35


class SimulatedGemini:
    """Ocupa el lugar de GeminiProvider: nada sale de la máquina."""

    def __init__(self):
        self.received = []

    def complete(self, messages, on_chunk=None, review=False, model=None, think=False):
        self.received.append(messages)
        answer = "(respuesta simulada de Gemini)"

        if on_chunk:
            on_chunk(answer)

        return answer

    def text(self):
        return "\n".join(m["content"] for msgs in self.received for m in msgs)


def new_brain():
    brain = Brain()
    gemini = SimulatedGemini()
    brain.provider_router.providers["gemini"] = gemini
    return brain, gemini


def session(lines, overrides):
    """Corre una sesión interactiva con esos mensajes y devuelve lo impreso."""
    SettingsManager.set_overrides({"stream_output": False, **overrides})
    brain, gemini = new_brain()
    lines = iter([*lines, "salir"])
    out = io.StringIO()

    with redirect_stdout(out):
        launcher.interactive_mode(brain, read=lambda prompt: next(lines))

    return out.getvalue(), gemini


def report(name, out, gemini, checks):
    print(f"\n=== {name}")
    print(out.strip()[:1500])
    print(f"--- Gemini (simulado) recibió {len(gemini.received)} envíos")

    failed = [label for label, ok in checks if not ok]

    for label, ok in checks:
        print(f"  {'OK   ' if ok else 'FALLA'} {label}")

    return not failed


def case_fallback(_):
    # Ollama "caído" (un puerto de esta máquina sin nada escuchando): sigue
    # siendo local, así que el fallback a Gemini es lo que se pone a prueba.
    out, gemini = session(
        [f"explica @{ATTACHMENT}"],
        {"ollama_host": "http://127.0.0.1:9", "default_provider": "ollama", "fallback_provider": "gemini"},
    )
    return report("Fallback a Gemini con un archivo adjunto", out, gemini, [
        ("Gemini no recibió nada", not gemini.received),
        ("dice que no usó el fallback y por qué", "no usé el fallback gemini" in out and "contenido local" in out),
        ("dice que no salió nada", "No salió nada de esta máquina" in out),
    ])


def case_attachment(_):
    out, gemini = session([f"explica @{ATTACHMENT} en dos frases"], {"default_provider": "gemini"})
    return report("Gemini por defecto + adjunto: responde el modelo local", out, gemini, [
        ("Gemini no recibió nada", not gemini.received),
        ("avisa por qué", "No envié esto a gemini: lleva contenido local (adjunto:" in out),
        ("responde el modelo local", "Respondo con el modelo local (ollama)" in out),
    ])


def case_authorization(_):
    out, gemini = session(
        [f"explica @{ATTACHMENT} en una frase", "envía esto a Gemini", "confirmar envío", "confirmar envío"],
        {"default_provider": "gemini"},
    )
    return report("Autorización de una sola vez", out, gemini, [
        ("muestra tipos y caracteres", "Saldría a gemini: adjunto:" in out),
        ("envía una sola vez", len(gemini.received) == 1),
        ("la segunda confirmación no envía", "No hay ningún envío por confirmar" in out),
        ("sin rutas absolutas", str(ROOT) not in gemini.text()),
    ])


def case_secret(_):
    # Una pregunta de charla: "por qué falla mi clave" iría a debug_project, que lee archivos.
    out, gemini = session([f"¿esta clave de Google tiene un formato válido? {SECRET_KEY}"], {"default_provider": "gemini"})
    return report("Secreto en lo tecleado", out, gemini, [
        ("la clave no sale", SECRET_KEY not in gemini.text()),
        ("se avisa la redacción", "Redacté antes de enviar a gemini" in out),
    ])


def case_local_mode(_):
    out, gemini = session(["modo local", "hola, ¿cómo estás?", "envía esto a Gemini"], {"default_provider": "gemini"})
    return report("Modo local", out, gemini, [
        ("Gemini no recibió nada", not gemini.received),
        ("no deja autorizar", "Estás en modo local: no envío nada afuera." in out),
    ])


def case_audit(_):
    out, gemini = session(["hola, PALABRA_TECLEADA", "qué has enviado afuera"], {"default_provider": "gemini"})
    log = paths.EXTERNAL_AUDIT_FILE.read_text(encoding="utf-8") if paths.EXTERNAL_AUDIT_FILE.exists() else ""
    entries = [json.loads(line) for line in log.splitlines()]
    return report("Bitácora sin texto", out, gemini, [
        ("hay entradas", bool(entries)),
        ("sin el texto", "PALABRA_TECLEADA" not in log),
        ("el resumen la muestra", "envíos externos" in out),
    ])


CASES = [
    (case_fallback, False),
    (case_attachment, True),
    (case_authorization, True),
    (case_secret, True),
    (case_local_mode, False),
    (case_audit, True),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin-ollama", action="store_true", help="solo los casos que no necesitan Ollama")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        paths.EXTERNAL_AUDIT_FILE = Path(tmp) / "external_audit.jsonl"
        print(f"Bitácora temporal: {paths.EXTERNAL_AUDIT_FILE}")
        results = [case(args) for case, needs_ollama in CASES if not (args.sin_ollama and needs_ollama)]

    print(f"\n{sum(results)} de {len(results)} casos OK.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
