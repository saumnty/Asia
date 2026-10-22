"""Acción que elige el IntentEngine para mensajes fijos (requiere Ollama).

Sirve para medir antes y después de cambiar el prompt del IntentEngine:

    .venv\\Scripts\\python.exe test\\manual\\check_intents.py --out antes.json
    (cambiar el prompt)
    .venv\\Scripts\\python.exe test\\manual\\check_intents.py --compare antes.json

Cada mensaje se clasifica --runs veces (temperatura 0: debería salir igual).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.intent_engine import IntentEngine

MESSAGES = [
    "recuerda que mi color favorito es el verde",
    "abre el bloc de notas",
    "¿qué es una closure en Python?",
    "busca la palabra Ollama en el proyecto",
    "explícame el archivo tools/file_tool.py",
    "muéstrame un resumen del archivo core/brain.py",
    "corrige pruebas/buggy_calculator.py",
    "refactoriza pruebas/buggy_calculator.py",
    "mejora el estilo de tools/file_tool.py",
    "encuentra por qué aparece Asia None",
    "arregla el bug de Asia None",
    "revisa a fondo pruebas/buggy_calculator.py",
    "revisa la carpeta pruebas sin síntesis",
    "prueba el cambio pendiente",
]


def classify(engine, runs):
    results = {}

    for message in MESSAGES:
        intents = [engine.detect(message) for _ in range(runs)]
        actions = {i.get("action") for i in intents}
        results[message] = {"action": intents[0].get("action"), "params": intents[0].get("params"), "estable": len(actions) == 1}
        flag = "" if len(actions) == 1 else f"  INESTABLE: {sorted(map(str, actions))}"
        print(f"{intents[0].get('action'):22} {message}{flag}", flush=True)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--compare", type=Path, help="JSON de una medición anterior")
    args = parser.parse_args()

    results = classify(IntentEngine(), args.runs)

    if args.out:
        args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        changed = [m for m in MESSAGES if before.get(m, {}).get("action") != results[m]["action"]]
        print(f"\n{len(MESSAGES) - len(changed)} de {len(MESSAGES)} con la misma acción.")

        for message in changed:
            print(f"  CAMBIÓ: {message!r}: {before.get(message, {}).get('action')} -> {results[message]['action']}")


if __name__ == "__main__":
    main()
